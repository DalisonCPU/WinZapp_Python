"""NewContactDialog: a local-contact tab and a phone-synced tab.

The synced tab is the default. Saving there goes to WhatsApp first and keeps
the local record only once WhatsApp has the contact. The dialog is a
wx.Dialog, so its methods are called on a plain stub (never a real window).
"""

import inspect
from types import SimpleNamespace

import pytest
import wx

from core import phone_contacts
from ui.dialogs import new_contact
from ui.dialogs.new_contact import (
    MODE_LOCAL, MODE_PHONE, NewContactDialog, resolve_initial_mode)


class _Field:
    def __init__(self, value=""):
        self.value, self.focused = value, False

    def GetValue(self): return self.value
    def ChangeValue(self, value): self.value = value
    def SetFocus(self): self.focused = True


class _Notebook:
    def __init__(self, selection=1):
        self.selection, self.enabled = selection, True

    def GetSelection(self): return self.selection
    def SetSelection(self, index): self.selection = index
    def Enable(self, on): self.enabled = on


class _Control:
    def __init__(self): self.label, self.enabled = "", True
    def SetLabel(self, text): self.label = text
    def Enable(self, on): self.enabled = on


class _MW:
    i18n = SimpleNamespace(t=lambda key: key)

    def __init__(self):
        self.local_saved, self.spoken, self.requests = [], [], []
        self.contacts = {}

    def save_local_contact(self, jid, entry): self.local_saved.append((jid, entry))
    def output(self, text, **kwargs): self.spoken.append(text)

    def save_phone_synced_contact(self, jid, first, last, on_done):
        self.requests.append((jid, first, last))
        self.on_done = on_done


class _Dialog:
    _mode = NewContactDialog._mode
    _refresh_ok_label = NewContactDialog._refresh_ok_label
    _on_tab_changed = NewContactDialog._on_tab_changed
    _set_busy = NewContactDialog._set_busy
    _on_add = NewContactDialog._on_add
    _save_synced = NewContactDialog._save_synced
    _jid_of = staticmethod(NewContactDialog._jid_of)

    def __init__(self, mode=MODE_PHONE):
        self._mw = _MW()
        self._modes = (MODE_LOCAL, MODE_PHONE)
        self._notebook = _Notebook(self._modes.index(mode))
        self._fields = {m: {"name": _Field(), "surname": _Field(), "phone": _Field()}
                        for m in self._modes}
        self._ok_btn, self._status = _Control(), _Control()
        self._busy = False
        self.result_jid = self.result_name = ""
        self.ended, self.closed = [], False

    def Layout(self): pass
    def EndModal(self, code): self.ended.append(code)
    def __bool__(self): return not self.closed

    def fill(self, mode, name="Ana", surname="Silva", phone="+55 11 99999-9999"):
        for key, value in (("name", name), ("surname", surname), ("phone", phone)):
            self._fields[mode][key].value = value


@pytest.fixture
def boxes(monkeypatch):
    shown = []
    monkeypatch.setattr(new_contact.wx, "MessageBox", lambda *a, **k: shown.append(a[0]))
    return shown


class TestWhichTabOpens:
    def test_the_phone_synced_tab_is_the_default(self):
        assert inspect.signature(NewContactDialog).parameters["initial_mode"].default == MODE_PHONE
        assert resolve_initial_mode((MODE_LOCAL, MODE_PHONE), MODE_PHONE) == MODE_PHONE

    def test_a_requested_tab_that_exists_is_used(self):
        assert resolve_initial_mode((MODE_LOCAL, MODE_PHONE), MODE_LOCAL) == MODE_LOCAL

    def test_a_tab_that_does_not_exist_falls_back_to_the_synced_one(self):
        assert resolve_initial_mode((MODE_PHONE,), MODE_LOCAL) == MODE_PHONE

    def test_the_tabs_are_local_first_then_synced(self):
        assert inspect.signature(NewContactDialog).parameters["modes"].default == (
            MODE_LOCAL, MODE_PHONE)


class TestTabs:
    def test_the_button_says_what_the_tab_does(self):
        d = _Dialog(MODE_PHONE)
        d._refresh_ok_label()
        assert d._ok_btn.label == "create_contact_phone"
        d._notebook.selection = 0
        d._refresh_ok_label()
        assert d._ok_btn.label == "create_contact"

    def test_what_was_typed_follows_to_the_other_tab(self):
        d = _Dialog(MODE_LOCAL)
        d.fill(MODE_PHONE, "Ana", "Silva", "5511999999999")
        d._notebook.selection = 0
        event = SimpleNamespace(GetOldSelection=lambda: 1, GetSelection=lambda: 0,
                                Skip=lambda: None)
        d._on_tab_changed(event)
        assert [d._fields[MODE_LOCAL][k].value for k in ("name", "surname", "phone")] == [
            "Ana", "Silva", "5511999999999"]


class TestLocalTab:
    def test_a_local_contact_is_stored_without_asking_whatsapp(self, boxes):
        d = _Dialog(MODE_LOCAL)
        d.fill(MODE_LOCAL)
        d._on_add(None)
        jid = "5511999999999@s.whatsapp.net"
        assert d._mw.requests == []
        assert d._mw.local_saved == [(jid, phone_contacts.local_entry(jid, "Ana Silva"))]
        assert d.ended == [wx.ID_OK] and d.result_jid == jid and d.result_name == "Ana Silva"

    def test_a_missing_name_or_a_short_number_is_refused(self, boxes):
        d = _Dialog(MODE_LOCAL)
        d.fill(MODE_LOCAL, name="")
        d._on_add(None)
        d.fill(MODE_LOCAL, phone="123")
        d._on_add(None)
        assert d.ended == [] and d._mw.local_saved == [] and len(boxes) == 2


class TestSyncedTab:
    def test_it_asks_whatsapp_and_waits_before_storing(self, boxes):
        d = _Dialog(MODE_PHONE)
        d.fill(MODE_PHONE)
        d._on_add(None)
        assert d._mw.requests == [("5511999999999@s.whatsapp.net", "Ana", "Silva")]
        assert d._mw.local_saved == [] and d.ended == []
        assert d._busy and not d._ok_btn.enabled and d._status.label == "new_contact_phone_saving"

    def test_when_whatsapp_has_it_the_record_is_kept_and_the_dialog_closes(self, boxes):
        d = _Dialog(MODE_PHONE)
        d.fill(MODE_PHONE)
        d._on_add(None)
        d._mw.on_done(True, "")
        jid = "5511999999999@s.whatsapp.net"
        assert d._mw.local_saved == [(jid, phone_contacts.synced_entry(jid, "Ana Silva"))]
        assert d.ended == [wx.ID_OK] and d.result_jid == jid
        assert "new_contact_phone_saved" in d._mw.spoken

    def test_a_refusal_keeps_the_dialog_open_and_says_why(self, boxes):
        d = _Dialog(MODE_PHONE)
        d.fill(MODE_PHONE)
        d._on_add(None)
        d._mw.on_done(False, "new_contact_phone_not_on_whatsapp")
        assert d._mw.local_saved == [] and d.ended == []
        assert not d._busy and d._ok_btn.enabled
        assert boxes == ["new_contact_phone_not_on_whatsapp"]
        assert d._mw.spoken[-1] == "new_contact_phone_not_on_whatsapp"
        assert d._fields[MODE_PHONE]["phone"].focused

    def test_closed_meanwhile_the_record_is_still_kept(self, boxes):
        """WhatsApp has the contact by then; WinZapp must not forget it."""
        d = _Dialog(MODE_PHONE)
        d.fill(MODE_PHONE)
        d._on_add(None)
        d.closed = True
        d._mw.on_done(True, "")
        assert len(d._mw.local_saved) == 1 and d.ended == []

    def test_a_second_press_while_saving_does_nothing(self, boxes):
        d = _Dialog(MODE_PHONE)
        d.fill(MODE_PHONE)
        d._on_add(None)
        d._on_add(None)
        assert len(d._mw.requests) == 1


SYNCED = {"isMyContact": True, "syncToAddressbook": True}


class TestANumberAlreadyInThePhoneBook:
    def test_the_local_tab_cannot_hide_it(self, boxes):
        d = _Dialog(MODE_LOCAL)
        d._mw.contacts["5511999999999@s.whatsapp.net"] = dict(SYNCED)
        d.fill(MODE_LOCAL)
        d._on_add(None)
        assert d._mw.local_saved == [] and d._mw.requests == [] and d.ended == []
        assert boxes == ["new_contact_local_blocked"]
        assert d._notebook.selection == d._modes.index(MODE_PHONE)

    def test_a_number_that_is_not_synced_still_saves_locally(self, boxes):
        d = _Dialog(MODE_LOCAL)
        d._mw.contacts["5511999999999@s.whatsapp.net"] = {"isMyContact": True,
                                                         "syncToAddressbook": False}
        d.fill(MODE_LOCAL)
        d._on_add(None)
        assert len(d._mw.local_saved) == 1 and d.ended == [wx.ID_OK]

    def test_the_jid_a_typed_number_names(self):
        assert NewContactDialog._jid_of("+55 (11) 99999-9999") == "5511999999999@s.whatsapp.net"
        assert NewContactDialog._jid_of("") == ""
