"""Returning to the main panel shows the main conversation, not the archived one."""
from core.archived_detour import ArchivedDetour
from ui.conversation_panel.conversation_navigation import ConversationNavigationMixin


def test_detour_remembers_the_main_conversation_once():
    detour = ArchivedDetour()
    detour.enter("main@s.whatsapp.net")
    detour.enter("")  # a second archived chat opened during the same visit
    assert detour.active
    assert detour.leave() == "main@s.whatsapp.net"
    assert not detour.active
    assert detour.leave() is None


def test_detour_started_with_no_main_conversation_open_resumes_nothing():
    detour = ArchivedDetour()
    detour.enter("")
    assert detour.active
    assert detour.leave() is None


class _MW:
    def __init__(self):
        self.chats = {"main@s.whatsapp.net": {"remoteJid": "main@s.whatsapp.net"},
                      "arch@s.whatsapp.net": {"remoteJid": "arch@s.whatsapp.net"}}
        self.archived = {"arch@s.whatsapp.net"}

    def is_chat_archived(self, jid):
        return jid in self.archived


class _Panel:
    def __init__(self, conversation):
        self.main_window = _MW()
        self.conversation = conversation
        self.calls = []

    def close_conversation_for_panel_switch(self):
        self.calls.append("close")
        self.conversation = None

    def navigate_to_conversation(self, chat, **kwargs):
        self.calls.append(("navigate", chat["remoteJid"], kwargs))
        self.conversation = chat


def _panel(conversation, resume):
    stub = _Panel(conversation)
    stub._archived_detour_state = lambda d=ArchivedDetour(): d
    detour = stub._archived_detour_state()
    detour.enter(resume)
    stub._detour = detour
    return stub


def _resume(stub):
    ConversationNavigationMixin.resume_main_after_archived(stub)


def test_returning_replaces_the_open_archived_chat_with_the_main_one():
    stub = _panel({"remoteJid": "arch@s.whatsapp.net"}, "main@s.whatsapp.net")
    _resume(stub)
    assert stub.calls == ["close", ("navigate", "main@s.whatsapp.net",
                                    {"take_focus": False, "mark_read": False})]
    assert stub.conversation["remoteJid"] == "main@s.whatsapp.net"
    assert not stub._detour.active


def test_returning_after_the_archived_chat_was_closed_still_restores_main():
    stub = _panel(None, "main@s.whatsapp.net")
    _resume(stub)
    assert stub.calls == [("navigate", "main@s.whatsapp.net",
                           {"take_focus": False, "mark_read": False})]


def test_returning_with_no_main_conversation_just_drops_the_archived_one():
    stub = _panel({"remoteJid": "arch@s.whatsapp.net"}, "")
    _resume(stub)
    assert stub.calls == ["close"]
    assert stub.conversation is None


def test_resume_target_that_became_archived_or_vanished_is_not_reopened():
    for target in ("arch@s.whatsapp.net", "gone@s.whatsapp.net"):
        stub = _panel(None, target)
        _resume(stub)
        assert stub.calls == []


def test_no_detour_means_nothing_changes():
    stub = _panel({"remoteJid": "main@s.whatsapp.net"}, "x@s.whatsapp.net")
    stub._detour.leave()
    _resume(stub)
    assert stub.calls == []
    assert stub.conversation["remoteJid"] == "main@s.whatsapp.net"
