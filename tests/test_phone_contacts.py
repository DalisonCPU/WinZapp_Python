"""Contacts saved to WhatsApp and synced to the phone (core/phone_contacts.py).

The request shapes, the answer-to-message mapping and the contact records are
plain functions over an injected ``post``: no network, no wx.
"""

from types import SimpleNamespace

from core import phone_contacts as pc


def _resp(status=200, body=None):
    return SimpleNamespace(ok=status < 400, status_code=status, json=lambda: body or {})


class _Post:
    def __init__(self, response=None, raises=None):
        self.calls, self._response, self._raises = [], response, raises

    def __call__(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self._raises:
            raise self._raises
        return self._response


class TestSaveContact:
    def test_the_request_asks_for_the_phone_sync(self):
        post = _Post(_resp(200, {"status": "success"}))
        assert pc.save_contact("http://127.0.0.1:6300", "tok", "+55 (11) 99999-9999",
                               "Ana", "Silva", post=post) == (True, "")
        url, kwargs = post.calls[0]
        assert url == "http://127.0.0.1:6300/api/tok/save-contact"
        assert kwargs["json"] == {"phone": "5511999999999", "name": "Ana",
                                  "lastName": "Silva", "syncAddressBook": True}
        assert kwargs["headers"]["Authorization"] == "Bearer tok"

    def test_a_number_too_short_is_refused_without_a_request(self):
        post = _Post(_resp())
        assert pc.save_contact("b", "t", "12345", "Ana", post=post) == (False, pc.ERR_INVALID)
        assert post.calls == []

    def test_a_number_that_is_not_on_whatsapp(self):
        """The server's contact validation answers 400 with no code."""
        post = _Post(_resp(400, {"status": "error", "message": "O número não existe."}))
        assert pc.save_contact("b", "t", "5511999999999", "Ana", post=post) == (
            False, pc.ERR_NOT_ON_WHATSAPP)

    def test_the_servers_invalid_contact_code(self):
        post = _Post(_resp(400, {"status": "error", "code": "contact_invalid"}))
        assert pc.save_contact("b", "t", "5511999999999", "Ana", post=post) == (
            False, pc.ERR_INVALID)

    def test_any_other_failure_is_the_generic_message(self):
        for response in (_resp(502, {"code": "contact_operation_failed"}),
                         _resp(404, {"status": "Disconnected"}),
                         _resp(503, {"code": "contact_not_available"})):
            assert pc.save_contact("b", "t", "5511999999999", "Ana",
                                   post=_Post(response)) == (False, pc.ERR_FAILED)

    def test_a_network_error_is_the_generic_message(self):
        post = _Post(raises=ConnectionError("down"))
        assert pc.save_contact("b", "t", "5511999999999", "Ana", post=post) == (
            False, pc.ERR_FAILED)

    def test_the_error_keys_are_the_ones_the_locales_define(self):
        import json
        from app_paths import resource_path
        with open(resource_path("languages", "pt-BR.json"), encoding="utf-8") as f:
            strings = json.load(f)
        assert {pc.ERR_INVALID, pc.ERR_NOT_ON_WHATSAPP, pc.ERR_FAILED} <= set(strings)


class TestRemoveContact:
    def test_it_asks_the_server_to_remove_it(self):
        post = _Post(_resp(200))
        assert pc.remove_contact("http://h:1", "tok", "5511999999999", post=post) is True
        assert post.calls[0][0] == "http://h:1/api/tok/remove-contact"
        assert post.calls[0][1]["json"] == {"phone": "5511999999999"}

    def test_a_contact_that_is_already_gone_counts_as_removed(self):
        for code in ("contact_not_found", "number_is_not_your_contact"):
            assert pc.remove_contact("b", "t", "5511999999999",
                                     post=_Post(_resp(400, {"code": code}))) is True

    def test_a_failure_is_not_removal(self):
        assert pc.remove_contact("b", "t", "5511999999999",
                                 post=_Post(_resp(502, {"code": "contact_operation_failed"}))) is False
        assert pc.remove_contact("b", "t", "5511999999999",
                                 post=_Post(raises=OSError("x"))) is False

    def test_a_short_number_sends_nothing(self):
        post = _Post(_resp())
        assert pc.remove_contact("b", "t", "123", post=post) is False
        assert post.calls == []


class TestRecords:
    def test_a_synced_entry_is_marked_and_saved(self):
        entry = pc.synced_entry("5511@s.whatsapp.net", "Ana Silva")
        assert entry["isSaved"] is True and entry[pc.SYNCED_KEY] is True
        assert entry["name"] == entry["pushName"] == "Ana Silva"

    def test_a_local_entry_is_not_marked_as_synced(self):
        entry = pc.local_entry("5511@s.whatsapp.net", "Ana")
        assert entry["isSaved"] is True and pc.SYNCED_KEY not in entry

    def test_is_phone_synced(self):
        assert pc.is_phone_synced(pc.synced_entry("j", "n")) is True
        assert pc.is_phone_synced(pc.local_entry("j", "n")) is False
        assert pc.is_phone_synced(None) is False


class TestMainWindowCalls:
    """ContactsMixin runs the request on a thread and answers on the wx thread."""

    class _MW:
        wpp_server, wpp_port, token = "http://127.0.0.1", 6300, "tok"
        save_phone_synced_contact = __import__(
            "main_window.contacts", fromlist=["ContactsMixin"]).ContactsMixin.save_phone_synced_contact
        remove_phone_synced_contact = __import__(
            "main_window.contacts", fromlist=["ContactsMixin"]).ContactsMixin.remove_phone_synced_contact

    @staticmethod
    def _inline(monkeypatch):
        from main_window import contacts

        class _Thread:
            def __init__(self, target, **kwargs): self._target = target
            def start(self): self._target()

        monkeypatch.setattr(contacts.threading, "Thread", _Thread)
        monkeypatch.setattr(contacts.wx, "CallAfter", lambda fn, *a: fn(*a))
        return contacts

    def test_save_answers_with_the_result(self, monkeypatch):
        contacts = self._inline(monkeypatch)
        seen = []
        monkeypatch.setattr(contacts.phone_contacts, "save_contact",
                            lambda base, token, jid, first, last: seen.append(
                                (base, token, jid, first, last)) or (True, ""))
        answers = []
        self._MW().save_phone_synced_contact("5511999999999@s.whatsapp.net", "Ana", "Silva",
                                             lambda ok, key: answers.append((ok, key)))
        assert seen == [("http://127.0.0.1:6300", "tok", "5511999999999@s.whatsapp.net", "Ana", "Silva")]
        assert answers == [(True, "")]

    def test_remove_answers_with_the_result(self, monkeypatch):
        contacts = self._inline(monkeypatch)
        monkeypatch.setattr(contacts.phone_contacts, "remove_contact",
                            lambda base, token, jid: False)
        answers = []
        self._MW().remove_phone_synced_contact("5511999999999@s.whatsapp.net", answers.append)
        assert answers == [False]


class TestWhichContactsAreInThePhoneBook:
    def test_whatsapp_marking_a_contact_as_synced_counts(self):
        """Added on the phone, or in WhatsApp Web: WinZapp never wrote its own
        marker, but WhatsApp says it is saved and synced."""
        assert pc.is_phone_synced({"isMyContact": True, "syncToAddressbook": True}) is True

    def test_saved_in_whatsapp_only_does_not_count(self):
        assert pc.is_phone_synced({"isMyContact": True, "syncToAddressbook": False}) is False
        assert pc.is_phone_synced({"isMyContact": False, "syncToAddressbook": True}) is False
        assert pc.is_phone_synced({"name": "Ana"}) is False

    def test_the_lookup_is_tolerant_of_the_brazilian_ninth_digit(self):
        entry = {"isMyContact": True, "syncToAddressbook": True}

        class _MW:
            contacts = {"551199999999@s.whatsapp.net": entry}

            def _get_contact_tolerant(self, jid):
                return self.contacts.get(jid.replace("5511999999999", "551199999999"))

        assert pc.existing_contact(_MW(), "5511999999999@s.whatsapp.net") is entry

    def test_a_window_without_the_tolerant_lookup_falls_back_to_a_plain_get(self):
        entry = {"isMyContact": True}
        mw = SimpleNamespace(contacts={"j": entry})
        assert pc.existing_contact(mw, "j") is entry
        assert pc.existing_contact(SimpleNamespace(), "j") is None

    def test_a_synced_contact_leaves_only_the_synced_tab(self):
        both = ("local", "phone")
        synced = {"isMyContact": True, "syncToAddressbook": True}
        assert pc.available_modes(synced, both, "phone") == ("phone",)
        assert pc.available_modes(pc.synced_entry("j", "n"), both, "phone") == ("phone",)
        assert pc.available_modes(pc.local_entry("j", "n"), both, "phone") == both
        assert pc.available_modes(None, both, "phone") == both


class TestASyncedContactReplacesTheLocalOne:
    """One record per number: saving it as synced overwrites the local one, on
    the phone JID and on the @lid copy, so no local-only copy is left."""

    def test_the_local_record_becomes_the_synced_one(self, monkeypatch):
        import main
        from tests.test_local_contact_sync import LID, PHONE, _Mw
        monkeypatch.setattr(main.wx, "CallAfter", lambda fn, *a, **k: fn(*a, **k))
        mw = _Mw()
        mw.save_local_contact(PHONE, pc.local_entry(PHONE, "Ana (local)"))
        assert not pc.is_phone_synced(mw.contacts[PHONE])

        mw.save_local_contact(PHONE, pc.synced_entry(PHONE, "Ana Silva"))

        for jid in (PHONE, LID):
            assert mw.contacts[jid]["name"] == "Ana Silva"
            assert pc.is_phone_synced(mw.contacts[jid])
        assert mw.db.upserted[PHONE][pc.SYNCED_KEY] is True
