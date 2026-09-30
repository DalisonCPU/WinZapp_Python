"""An open conversation behind another panel is not being read."""
from core.conversation_view import conversation_in_view
from main_window.shortcuts import ShortcutsMixin


class _Panel:
    def __init__(self, conversation, shown=True):
        self.conversation = conversation
        self._shown = shown

    def IsShown(self):
        return self._shown


def test_shown_panel_with_open_conversation_is_in_view():
    assert conversation_in_view(_Panel({"remoteJid": "1@s.whatsapp.net"}))


def test_panel_hidden_by_a_panel_switch_is_not_in_view():
    # Alt+4 Hide()s conversations_panel but leaves its conversation open.
    assert not conversation_in_view(_Panel({"remoteJid": "1@s.whatsapp.net"}, shown=False))


def test_no_conversation_or_no_panel_is_not_in_view():
    assert not conversation_in_view(_Panel(None))
    assert not conversation_in_view(None)


def test_stand_in_without_is_shown_keeps_old_behaviour():
    class Bare:
        conversation = {"remoteJid": "1@s.whatsapp.net"}
    assert conversation_in_view(Bare())


def test_destroyed_panel_is_not_in_view():
    class Dead(_Panel):
        def IsShown(self):
            raise RuntimeError("wrapped C/C++ object has been deleted")
    assert not conversation_in_view(Dead({"remoteJid": "1@s.whatsapp.net"}))


class _Stub:
    def __init__(self, conversation):
        self.calls = []
        self.conversations_panel = self
        self.conversation = conversation

    def _ensure_conversations_panel_visible(self):
        self.calls.append("show")

    def _on_accel_focus_list(self, event):
        self.calls.append("focus")


def test_alt_m_from_the_archived_panel_shows_the_conversation_and_focuses_messages():
    stub = _Stub({"remoteJid": "1@s.whatsapp.net"})
    ShortcutsMixin._on_global_focus_messages(stub, None)
    assert stub.calls == ["show", "focus"]


def test_alt_m_without_an_open_conversation_only_asks_the_panel_to_announce():
    stub = _Stub(None)
    ShortcutsMixin._on_global_focus_messages(stub, None)
    assert stub.calls == ["focus"]


def test_archived_chat_is_silent_unless_current_or_archived_list_visible():
    from core.conversation_view import archived_chat_stays_silent
    assert archived_chat_stays_silent(False, False)      # status/main panel
    assert not archived_chat_stays_silent(False, True)   # archived list shown
    assert not archived_chat_stays_silent(True, False)   # open and in view


def test_archived_panel_is_shown_reads_the_panel_flag():
    from core.conversation_view import archived_panel_is_shown

    class _MW:
        archived_conversations_panel = _Panel(None, shown=True)
    assert archived_panel_is_shown(_MW())
    _MW.archived_conversations_panel = _Panel(None, shown=False)
    assert not archived_panel_is_shown(_MW())
    assert not archived_panel_is_shown(object())


def test_open_conversation_beside_the_archived_list_is_visible_but_not_in_view():
    class _MW:
        archived_conversations_panel = _Panel(None, shown=True)
    panel = _Panel({"remoteJid": "1@s.whatsapp.net"})
    panel.main_window = _MW()
    assert not conversation_in_view(panel)
    _MW.archived_conversations_panel = _Panel(None, shown=False)
    assert conversation_in_view(panel)


def test_alt_4_keeps_the_open_conversation_on_screen_without_the_main_list():
    class _Widget:
        def __init__(self):
            self.calls = []
        def Hide(self):
            self.calls.append("hide")
        def Show(self):
            self.calls.append("show")

    class _CP(_Widget):
        def __init__(self, conversation):
            super().__init__()
            self.conversation = conversation
            self.conversations_label, self.conversations_list = _Widget(), _Widget()

    class _Stub:
        pass

    for conversation, expected in (({"remoteJid": "1@s.whatsapp.net"}, ["show"]), (None, [])):
        stub = _Stub()
        stub.conversations_panel = _CP(conversation)
        ShortcutsMixin._keep_open_conversation_beside_archived(stub)
        cp = stub.conversations_panel
        assert cp.calls == expected
        assert cp.conversations_list.calls == (["hide"] if conversation else [])
        assert cp.conversations_label.calls == (["hide"] if conversation else [])


def test_closing_beside_the_archived_list_returns_focus_to_that_list(monkeypatch):
    import wx
    from ui.conversation_panel.conversation_navigation import ConversationNavigationMixin

    queued = []
    monkeypatch.setattr(wx, "CallAfter", lambda fn, *a: queued.append((fn.__name__, a)))

    class _MW:
        archived_conversations_panel = _Panel(None, shown=True)
        def is_chat_locked(self, jid): return False
        def is_chat_archived(self, jid): return False

    class _Stub:
        main_window = _MW()
        def _close_conversation_core(self): return True, "1@s.whatsapp.net"
        def _return_to_shown_archived_list(self): pass
        def _restore_conversation_selection(self): pass

    ConversationNavigationMixin.close_conversation(_Stub())
    assert queued == [("_return_to_shown_archived_list", ())]
