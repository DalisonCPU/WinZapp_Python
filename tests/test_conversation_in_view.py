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
