"""Editing and deleting a contact saved to the phone (ConversationDataDialog).

A synced contact is edited as one, so no "local" copy is left next to the
WhatsApp one, and it is deleted from WhatsApp and the phone first: when that
fails the contact stays in WinZapp, which is what is still true.
"""

from types import SimpleNamespace

import wx

from core import phone_contacts
from ui.dialogs import new_contact
from ui.dialogs.conversation_data_dialog import ConversationDataDialog

JID = "5511999999999@s.whatsapp.net"


class _MW:
    def __init__(self, entry):
        self.contacts = {JID: entry}
        self._lid_to_phone = {}
        self.removed_local, self.requests, self.spoken = [], [], []

    def remove_local_contact(self, jid): self.removed_local.append(jid)
    def output(self, text, **kwargs): self.spoken.append(text)

    def remove_phone_synced_contact(self, jid, on_done):
        self.requests.append(jid)
        self.on_done = on_done


class _Stub:
    _resolve_contact_phone_jid = ConversationDataDialog._resolve_contact_phone_jid
    _local_contact_entry = ConversationDataDialog._local_contact_entry
    _on_delete_contact = ConversationDataDialog._on_delete_contact
    _finish_delete_contact = ConversationDataDialog._finish_delete_contact
    _on_edit_contact = ConversationDataDialog._on_edit_contact

    def __init__(self, entry):
        self._jid, self._name = JID, "Ana Silva"
        self._i18n = SimpleNamespace(t=lambda key: key)
        self._mw = _MW(entry)
        self.repopulated = 0

    def _populate_contact_action_buttons(self): self.repopulated += 1
    def _fetch_data(self): pass
    def __bool__(self): return True


def _answer(monkeypatch, result):
    shown = []

    def _box(message, title="", style=0, parent=None):
        shown.append((message, title))
        return result

    monkeypatch.setattr(wx, "MessageBox", _box)
    return shown


class TestDelete:
    def test_a_local_contact_is_deleted_here_only(self, monkeypatch):
        stub = _Stub(phone_contacts.local_entry(JID, "Ana Silva"))
        shown = _answer(monkeypatch, wx.YES)
        stub._on_delete_contact(None)
        assert shown[0][0] == "delete_contact_local_confirm_msg"
        assert stub._mw.requests == [] and stub._mw.removed_local == [JID]
        assert stub.repopulated == 1

    def test_a_synced_contact_asks_whatsapp_and_warns_it_leaves_the_phone(self, monkeypatch):
        stub = _Stub(phone_contacts.synced_entry(JID, "Ana Silva"))
        shown = _answer(monkeypatch, wx.YES)
        stub._on_delete_contact(None)
        assert shown[0][0] == "delete_contact_phone_confirm_msg"
        assert stub._mw.requests == [JID] and stub._mw.removed_local == []

    def test_it_is_dropped_here_only_once_whatsapp_removed_it(self, monkeypatch):
        stub = _Stub(phone_contacts.synced_entry(JID, "Ana Silva"))
        _answer(monkeypatch, wx.YES)
        stub._on_delete_contact(None)
        stub._mw.on_done(True)
        assert stub._mw.removed_local == [JID] and stub.repopulated == 1

    def test_a_failure_keeps_the_contact_and_says_so(self, monkeypatch):
        stub = _Stub(phone_contacts.synced_entry(JID, "Ana Silva"))
        shown = _answer(monkeypatch, wx.YES)
        stub._on_delete_contact(None)
        stub._mw.on_done(False)
        assert stub._mw.removed_local == [] and stub.repopulated == 0
        assert stub._mw.spoken == ["delete_contact_phone_failed"]
        assert shown[-1][0] == "delete_contact_phone_failed"

    def test_declining_the_confirmation_changes_nothing(self, monkeypatch):
        stub = _Stub(phone_contacts.synced_entry(JID, "Ana Silva"))
        _answer(monkeypatch, wx.NO)
        stub._on_delete_contact(None)
        assert stub._mw.requests == [] and stub._mw.removed_local == []


class TestEdit:
    def _edit(self, monkeypatch, entry):
        seen = {}

        class _Fake:
            def __init__(self, *args, **kwargs):
                seen.update(kwargs)

            def SetTitle(self, title): pass
            def ShowModal(self): return wx.ID_CANCEL
            def Destroy(self): pass

        monkeypatch.setattr(new_contact, "NewContactDialog", _Fake)
        _Stub(entry)._on_edit_contact(None)
        return seen

    def test_a_synced_contact_is_edited_only_as_a_synced_one(self, monkeypatch):
        seen = self._edit(monkeypatch, phone_contacts.synced_entry(JID, "Ana Silva"))
        assert seen["modes"] == (new_contact.MODE_PHONE,)
        assert seen["initial_mode"] == new_contact.MODE_PHONE

    def test_a_local_contact_opens_on_its_own_tab_and_may_become_synced(self, monkeypatch):
        seen = self._edit(monkeypatch, phone_contacts.local_entry(JID, "Ana Silva"))
        assert seen["modes"] == (new_contact.MODE_LOCAL, new_contact.MODE_PHONE)
        assert seen["initial_mode"] == new_contact.MODE_LOCAL
