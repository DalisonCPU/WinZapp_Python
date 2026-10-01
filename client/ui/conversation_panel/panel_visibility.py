"""ConversationPanelVisibilityMixin — part of ConversationsPanel (see ui/conversation_panel/__init__.py).

One ConversationsPanel serves three chat lists (main, archived, locked), so
at most one conversation is open at a time. The rule for what is on screen is
the same for all three: a conversation belongs to the panel it was opened
from, and is visible only while that panel is the one shown. Switching to
another panel hides it (it stays open, message list untouched); switching back
shows it again. A conversation opened meanwhile in the shared widget parks the
one it displaces, to be reopened when its own panel comes back.

Every way of making one of the three chat panels visible goes through
show_chat_panel(): it shows or hides the detail pane by origin and puts focus
on that panel's chat list, never in a message list. Hiding and showing is only
Show/Hide/Layout; the one thing that rebuilds is reopening a displaced
conversation, and that skips every network request the first open made.
"""

import logging
import wx
from core.conversation_view import (
    ARCHIVED,
    LOCKED,
    conversation_visible_in,
    panel_layout,
    parked_chat_reopenable,
    resolve_origin,
)


class ConversationPanelVisibilityMixin:

    def _parked_conversations(self) -> dict:
        parked = getattr(self, "_parked_by_origin", None)
        if parked is None:
            parked = self._parked_by_origin = {}
        return parked

    def forget_parked_conversation(self, origin: str):
        self._parked_conversations().pop(origin, None)

    def _begin_conversation_visit(self, conversation, origin=None) -> str:
        """Record which panel `conversation` is being opened for and park the
        conversation it displaces when that one belongs to another panel."""
        current_origin = getattr(self, "_conversation_origin", None)
        origin = resolve_origin(
            origin, current_origin,
            self.conversations_list.IsShown(), self.conversation_panel.IsShown())
        parked = self._parked_conversations()
        parked.pop(origin, None)  # what is opened here supersedes it
        current = self.conversation
        if (current is not None and current_origin
                and current_origin != origin
                and current.get("remoteJid") != conversation.get("remoteJid")):
            try:
                msg_id = self._focused_msg_id()
            except Exception:
                msg_id = ""
            try:
                note = self._conv_data_btn.GetNote()
            except Exception:
                note = None
            # What the open fetched in the background (participants for the
            # @mention list, the last-seen/size note), so the reopen need not.
            parked[current_origin] = {
                "jid": current.get("remoteJid", ""), "msg_id": msg_id,
                "participants": list(getattr(self, "_group_participants_cache", [])),
                "note": note}
        self._conversation_origin = origin
        self._shown_panel = origin
        return origin

    def _reopen_parked_conversation(self, origin: str) -> bool:
        entry = self._parked_conversations().pop(origin, None)
        if not entry:
            return False
        mw = self.main_window
        jid = entry["jid"]
        chat = mw.chats.get(jid)
        if chat is None or not parked_chat_reopenable(
                origin, mw.is_chat_locked(jid),
                getattr(mw, "_chat_lock_unlocked", False)):
            return False
        # Reopening is not reading: no focus grab and no mark-as-read, and not
        # opening either: resume=True skips the presence subscription, the
        # profile/group-info/reactions requests and the participants fetch.
        self.navigate_to_conversation(
            chat, origin=origin, take_focus=False, mark_read=False, resume=True)
        self._group_participants_cache = entry.get("participants") or []
        if entry.get("note"):
            self._conv_data_btn.SetNote(entry["note"])
        self._refocus_message(entry.get("msg_id"))
        return True

    def _refocus_message(self, msg_id):
        """Put the list's current row back on the message the user had reached
        (no SetFocus: the caller decides where keyboard focus goes)."""
        if not msg_id:
            return
        for idx, msg in enumerate(self._sorted_messages):
            if not self._is_separator(msg) and msg.get("key", {}).get("id") == msg_id:
                self.messages_list.Focus(idx)
                self.messages_list.Select(idx, True)
                self.messages_list.EnsureVisible(idx)
                return

    def _list_panel_for(self, shown: str):
        """The archived or locked list panel that `shown` stands for (None for
        MAIN: its list is ConversationsPanel's own)."""
        name = {ARCHIVED: "archived_conversations_panel",
                LOCKED: "locked_conversations_panel"}.get(shown)
        return getattr(self.main_window, name, None) if name else None

    def _apply_panel_layout(self, shown: str, list_panel) -> None:
        """Show and hide this panel's parts for `shown` being the chat list on
        screen (see panel_layout()). Only Show/Hide/Layout: hiding or showing
        an open conversation never rebuilds it or asks the network for
        anything."""
        layout = panel_layout(
            getattr(self, "_conversation_origin", None), shown,
            self.conversation is not None)
        if self.conversation is not None:
            self.conversation_panel.Show(layout["detail"])
        self.conversations_label.Show(layout["own_list"])
        self.conversations_list.Show(layout["own_list"])
        self.Show(layout["panel"])
        if list_panel is not None:
            list_panel.Show(layout["list_panel"])
        self.Layout()
        self.main_window.content_panel.Layout()

    def _still_on_panel(self, shown: str, list_panel) -> bool:
        """Whether `shown` is still the panel on screen (a deferred step must
        not bring a panel back after the user has moved on)."""
        if getattr(self, "_shown_panel", None) != shown:
            return False
        return bool((list_panel or self).IsShown())

    def show_chat_panel(self, shown: str, *, focus: bool = True) -> None:
        """The one way a chat panel (main, archived, locked) becomes the
        visible one: every other panel is hidden, the open conversation is
        shown only if it belongs to `shown`, and keyboard focus goes to that
        panel's chat list, never into a message list. A conversation set
        aside by another one is reopened right after (see
        _finish_panel_reopen), so the switch itself costs only Show/Hide.
        `focus=False` for callers that place focus themselves."""
        mw = self.main_window
        list_panel = self._list_panel_for(shown)
        for name in ("archived_conversations_panel", "locked_conversations_panel",
                     "status_panel", "calls_panel"):
            other = getattr(mw, name, None)
            if other is not None and other is not list_panel:
                other.Hide()
        self._shown_panel = shown
        reopen_due = shown in self._parked_conversations() and (
            self.conversation is None or not conversation_visible_in(
                getattr(self, "_conversation_origin", None), shown))
        self._apply_panel_layout(shown, list_panel)
        if focus:
            if list_panel is None:
                self._restore_conversation_selection()
            else:
                list_panel.restore_selection()
        if reopen_due:
            wx.CallAfter(self._finish_panel_reopen, shown)

    def _finish_panel_reopen(self, shown: str) -> None:
        list_panel = self._list_panel_for(shown)
        if not self._still_on_panel(shown, list_panel):
            return
        try:
            self._reopen_parked_conversation(shown)
        except Exception:
            logging.exception("[conversations] could not reopen the parked conversation")
        self._apply_panel_layout(shown, list_panel)
