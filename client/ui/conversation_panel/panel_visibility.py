"""ConversationPanelVisibilityMixin — part of ConversationsPanel (see ui/conversation_panel/__init__.py).

One ConversationsPanel serves three chat lists (main, archived, locked), so
at most one conversation is open at a time. The rule for what is on screen is
the same for all three: a conversation belongs to the panel it was opened
from, and is visible only while that panel is the one shown. Switching to
another panel hides it (it stays open, message list untouched); switching back
shows it again. A conversation opened meanwhile in the shared widget parks the
one it displaces, to be reopened when its own panel comes back.
"""

import logging
from core.conversation_view import (
    MAIN,
    conversation_visible_in,
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
            parked[current_origin] = {
                "jid": current.get("remoteJid", ""), "msg_id": msg_id}
        self._conversation_origin = origin
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
        # Reopening is not reading: no focus grab and no mark-as-read.
        self.navigate_to_conversation(
            chat, origin=origin, take_focus=False, mark_read=False)
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

    def reveal_conversation_for_panel(self, shown: str) -> bool:
        """Lay this panel out for `shown` (MAIN, ARCHIVED or LOCKED) being the
        visible chat list. Returns True when the conversation takes the place
        of that list (an archived or locked one: the list stays hidden, as it
        is when such a chat is first opened) and False when the list shows.
        """
        if self.conversation is None or not conversation_visible_in(
                getattr(self, "_conversation_origin", None), shown):
            try:
                self._reopen_parked_conversation(shown)
            except Exception:
                logging.exception("[conversations] could not reopen the parked conversation")
        visible = (self.conversation is not None and conversation_visible_in(
            getattr(self, "_conversation_origin", None), shown))
        takes_over = visible and shown != MAIN
        if self.conversation is not None:
            self.conversation_panel.Show(visible)
        self.conversations_label.Show(not takes_over)
        self.conversations_list.Show(not takes_over)
        self.Show(shown == MAIN or takes_over)
        self.Layout()
        return takes_over

    def _focus_revealed_conversation(self):
        """Keyboard focus into a conversation that was just shown again: the
        message list on the row it was left on (its focused item is unchanged,
        so only that row is announced), the composer when it has no rows."""
        if self.messages_list.GetItemCount() > 0:
            self.messages_list.SetFocus()
        else:
            self.message_field.SetFocus()

    def switch_to_chat_panel(self, shown: str, list_panel=None) -> bool:
        """Finish a switch to the archived or locked list `list_panel`: show
        the list, or the conversation that belongs to it in the list's place,
        and put focus there. The caller has already hidden every other panel.
        """
        takes_over = self.reveal_conversation_for_panel(shown)
        if list_panel is not None:
            list_panel.Show(not takes_over)
        self.main_window.content_panel.Layout()
        if takes_over:
            self._focus_revealed_conversation()
        elif list_panel is not None:
            list_panel.restore_selection()
        return takes_over
