"""An open conversation is on screen only while the panel it was opened from
(main, archived or locked) is the one shown.

ConversationsPanel is a wx.Panel, so the mixin methods are bound onto a plain
stub; no window is created.
"""

from core.conversation_view import (
    ARCHIVED, LOCKED, MAIN, conversation_visible_in, parked_chat_reopenable,
    resolve_origin,
)
from ui.conversation_panel.panel_visibility import ConversationPanelVisibilityMixin

A = "a@s.whatsapp.net"
B = "b@s.whatsapp.net"


def test_a_conversation_is_visible_only_in_its_own_panel():
    assert conversation_visible_in(ARCHIVED, ARCHIVED)
    assert not conversation_visible_in(ARCHIVED, MAIN)
    assert not conversation_visible_in(MAIN, ARCHIVED)
    assert not conversation_visible_in(LOCKED, MAIN)
    assert not conversation_visible_in(None, MAIN)


def test_origin_defaults_to_main_even_for_an_archived_chat_from_the_search_box():
    assert resolve_origin(None, None, True, False) == MAIN
    assert resolve_origin(None, MAIN, True, True) == MAIN


def test_origin_is_kept_for_a_chat_opened_from_inside_a_detail_only_conversation():
    assert resolve_origin(None, ARCHIVED, False, True) == ARCHIVED
    assert resolve_origin(None, LOCKED, False, True) == LOCKED
    # the archived chat is parked behind the main list: that is not inside it
    assert resolve_origin(None, ARCHIVED, True, False) == MAIN


def test_an_explicit_origin_wins():
    assert resolve_origin(ARCHIVED, MAIN, True, True) == ARCHIVED


def test_parked_chat_reopen_rules():
    assert parked_chat_reopenable(MAIN, False, False)
    assert not parked_chat_reopenable(MAIN, True, True)
    assert parked_chat_reopenable(LOCKED, True, True)
    assert not parked_chat_reopenable(LOCKED, True, False)
    assert not parked_chat_reopenable(LOCKED, False, True)


class _Widget:
    def __init__(self, shown=True):
        self.shown = shown
        self.focus_calls = 0

    def Show(self, show=True):
        self.shown = bool(show)

    def Hide(self):
        self.shown = False

    def IsShown(self):
        return self.shown

    def Layout(self):
        pass

    def SetFocus(self):
        self.focus_calls += 1


class _List(_Widget):
    focused = 3

    def GetItemCount(self):
        return 5


class _MW:
    def __init__(self):
        self.chats = {A: {"remoteJid": A}, B: {"remoteJid": B}}
        self.locked = set()
        self._chat_lock_unlocked = False
        self.content_panel = _Widget()

    def is_chat_locked(self, jid):
        return jid in self.locked


class _Panel(ConversationPanelVisibilityMixin):
    """The ConversationsPanel surface the mixin touches."""

    _sorted_messages = []

    def __init__(self):
        self.main_window = _MW()
        self.conversation = None
        self.conversation_panel = _Widget(shown=False)
        self.conversations_label = _Widget()
        self.conversations_list = _Widget()
        self.messages_list = _List()
        self.message_field = _Widget()
        self.shown = True
        self.navigated = []

    def Show(self, show=True):
        self.shown = bool(show)

    def Layout(self):
        pass

    def _focused_msg_id(self):
        return "msg-%d" % self.messages_list.focused

    def _is_separator(self, msg):
        return False

    def navigate_to_conversation(self, chat, *, origin=None, take_focus=True,
                                 mark_read=True):
        self._begin_conversation_visit(chat, origin)
        self.navigated.append((chat["remoteJid"], origin, take_focus, mark_read))
        self.conversation = chat
        self.conversation_panel.Show()

    def open(self, jid, origin=None):
        """What opening a chat does to the visible layout."""
        if origin in (ARCHIVED, LOCKED):
            self.conversations_list.Hide()
            self.conversations_label.Hide()
        self.navigate_to_conversation(self.main_window.chats[jid], origin=origin)


def test_main_conversation_is_hidden_in_archived_and_back_unchanged():
    p = _Panel()
    p.open(A)
    row = p.messages_list.focused
    assert p.reveal_conversation_for_panel(ARCHIVED) is False
    assert not p.conversation_panel.shown and not p.shown
    assert p.conversation is not None  # still open, not closed
    assert p.reveal_conversation_for_panel(MAIN) is False
    assert p.conversation_panel.shown and p.shown
    assert p.messages_list.focused == row


def test_archived_conversation_is_hidden_in_main_and_back_unchanged():
    p = _Panel()
    p.open(A, ARCHIVED)
    assert p.reveal_conversation_for_panel(MAIN) is False
    assert p.shown and p.conversations_list.shown
    assert not p.conversation_panel.shown
    assert p.conversation["remoteJid"] == A
    # back in the archived panel it takes the list's place again
    assert p.reveal_conversation_for_panel(ARCHIVED) is True
    assert p.conversation_panel.shown and p.shown
    assert not p.conversations_list.shown and not p.conversations_label.shown


def test_archived_chat_opened_from_the_main_search_belongs_to_main():
    p = _Panel()
    p.open(A)  # default origin: what the main list and its search box use
    assert p._conversation_origin == MAIN
    p.reveal_conversation_for_panel(ARCHIVED)
    assert not p.conversation_panel.shown
    p.reveal_conversation_for_panel(MAIN)
    assert p.conversation_panel.shown


def test_locked_conversation_follows_the_same_rule():
    p = _Panel()
    p.open(A, LOCKED)
    assert p.reveal_conversation_for_panel(MAIN) is False
    assert not p.conversation_panel.shown
    assert p.reveal_conversation_for_panel(LOCKED) is True
    assert p.conversation_panel.shown


def test_a_conversation_displaced_by_another_panel_comes_back_with_its_row():
    p = _Panel()
    p.open(A)                      # main conversation, row 3 reached
    p.reveal_conversation_for_panel(ARCHIVED)
    p.open(B, ARCHIVED)            # replaces it in the shared widget
    assert p._parked_conversations() == {MAIN: {"jid": A, "msg_id": "msg-3"}}
    p.reveal_conversation_for_panel(MAIN)
    assert p.conversation["remoteJid"] == A
    assert p.navigated[-1] == (A, MAIN, False, False)  # no focus grab, no read
    # the archived one was parked in turn and returns on its own panel
    assert p.reveal_conversation_for_panel(ARCHIVED) is True
    assert p.conversation["remoteJid"] == B


def test_a_parked_chat_locked_in_the_meantime_is_not_reopened():
    p = _Panel()
    p.open(A)
    p.reveal_conversation_for_panel(ARCHIVED)
    p.open(B, ARCHIVED)
    p.main_window.locked.add(A)
    p.reveal_conversation_for_panel(MAIN)
    assert p.conversation["remoteJid"] == B
    assert not p.conversation_panel.shown


def test_forgetting_the_parked_locked_conversation():
    p = _Panel()
    p._parked_conversations()[LOCKED] = {"jid": A, "msg_id": ""}
    p.forget_parked_conversation(LOCKED)
    assert LOCKED not in p._parked_conversations()


def test_reopening_the_same_chat_from_another_panel_changes_its_owner():
    p = _Panel()
    p.open(A)
    p.reveal_conversation_for_panel(ARCHIVED)
    p.open(A, ARCHIVED)
    assert p._conversation_origin == ARCHIVED
    assert p._parked_conversations() == {}


def test_switching_to_the_archived_panel_focuses_its_conversation_not_the_list():
    p = _Panel()
    arch = _Widget()
    arch.restore_selection = lambda: setattr(arch, "restored", True)
    p.open(A, ARCHIVED)
    assert p.switch_to_chat_panel(ARCHIVED, arch) is True
    assert not arch.shown
    assert p.messages_list.focus_calls == 1
    assert not hasattr(arch, "restored")


def test_switching_to_the_archived_panel_without_its_conversation_shows_the_list():
    p = _Panel()
    arch = _Widget(shown=False)
    arch.restore_selection = lambda: setattr(arch, "restored", True)
    p.open(A)
    assert p.switch_to_chat_panel(ARCHIVED, arch) is False
    assert arch.shown and arch.restored
    assert not p.conversation_panel.shown


def _esc(monkeypatch, origin, jid=A, unlocked=True):
    import wx
    from ui.conversation_panel.conversation_navigation import ConversationNavigationMixin

    queued = []
    monkeypatch.setattr(wx, "CallAfter", lambda fn, *a: queued.append(fn.__name__))

    class _Stub:
        _conversation_origin = origin
        main_window = type("MW", (), {
            "_chat_lock_unlocked": unlocked,
            "archived_conversations_panel": object(),
            "locked_conversations_panel": object(),
        })()

        def _close_conversation_core(self):
            return True, jid

        def _restore_to_archived_list(self, jid): pass
        def _restore_to_locked_list(self, jid): pass
        def _restore_conversation_selection(self): pass

    ConversationNavigationMixin.close_conversation(_Stub())
    return queued


def test_esc_returns_to_the_list_the_conversation_was_opened_from(monkeypatch):
    assert _esc(monkeypatch, ARCHIVED) == ["_restore_to_archived_list"]
    assert _esc(monkeypatch, LOCKED) == ["_restore_to_locked_list"]
    assert _esc(monkeypatch, MAIN) == ["_restore_conversation_selection"]


def test_esc_on_a_locked_origin_with_a_closed_vault_goes_to_the_main_list(monkeypatch):
    assert _esc(monkeypatch, LOCKED, unlocked=False) == ["_restore_conversation_selection"]
