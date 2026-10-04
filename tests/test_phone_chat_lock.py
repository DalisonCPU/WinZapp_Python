"""WhatsApp Chat Lock set on the phone (``isLocked``), treated like a locked chat.

No window is opened (CLAUDE.md): the rules are plain functions, the state is
exercised on a lightweight stub of MainWindow, and what needs wx is checked
from the source text.
"""

import json
import re
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from core import phone_chat_lock as rules
from core.chat_lock_vault import ChatLockVault
from main import MainWindow

ROOT = Path(__file__).resolve().parent.parent / "client"
LOCALES = sorted(
    p.stem for p in (ROOT / "languages").glob("*.json") if p.stem != "language_map"
)

PHONE = "5511999990000@s.whatsapp.net"
LID = "123456789012345@lid"


def _read(*parts):
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


# ── the plain rules ──────────────────────────────────────────────────────────


class TestStatedFlag:
    @pytest.mark.parametrize("value, expected", [
        (True, True), (False, False), ("true", True), ("false", False),
        (1, True), (0, False),
    ])
    def test_a_stated_value_is_read(self, value, expected):
        assert rules.stated_flag({"isLocked": value}) is expected

    @pytest.mark.parametrize("chat", [None, "x", [], {}, {"isLocked": None}, {"isLocked": "maybe"}])
    def test_a_record_that_states_nothing_is_none(self, chat):
        assert rules.stated_flag(chat) is None


class TestIsLocked:
    def test_a_stated_flag_settles_it_over_the_persisted_set(self):
        assert rules.is_locked(False, [PHONE], {PHONE}) is False
        assert rules.is_locked(True, [PHONE], set()) is True

    def test_the_persisted_set_decides_only_when_the_record_says_nothing(self):
        assert rules.is_locked(None, [PHONE], {PHONE}) is True
        assert rules.is_locked(None, [PHONE], set()) is False

    def test_any_of_the_names_of_the_chat_counts(self):
        assert rules.is_locked(None, [PHONE, LID], {LID}) is True


class TestApplyFlag:
    def test_true_adds_every_name_and_reports_a_change(self):
        members = set()
        assert rules.apply_flag(members, [PHONE, LID], True) is True
        assert members == {PHONE, LID}

    def test_true_again_changes_nothing(self):
        members = {PHONE}
        assert rules.apply_flag(members, [PHONE], True) is False

    def test_false_removes_every_name(self):
        members = {PHONE, LID, "other@s.whatsapp.net"}
        assert rules.apply_flag(members, [PHONE, LID], False) is True
        assert members == {"other@s.whatsapp.net"}

    def test_false_for_a_chat_never_in_the_set_changes_nothing(self):
        assert rules.apply_flag({"x"}, [PHONE], False) is False

    def test_none_leaves_the_set_alone(self):
        members = {PHONE}
        assert rules.apply_flag(members, [PHONE, LID], None) is False
        assert members == {PHONE}

    def test_an_empty_name_is_skipped(self):
        members = set()
        assert rules.apply_flag(members, ["", PHONE], True) is True
        assert members == {PHONE}


# ── the state on a stub main window ──────────────────────────────────────────


class _Db:
    def __init__(self, stored=None):
        self.stored = dict(stored or {})
        self.writes = []

    def get_metadata_json(self, key, default):
        return self.stored.get(key, default)

    def set_metadata_json(self, key, value):
        self.writes.append((key, value))
        self.stored[key] = value


class _Stub:
    _PHONE_LOCK_KEY = MainWindow._PHONE_LOCK_KEY
    _CHAT_LOCK_INDEX_KEY = MainWindow._CHAT_LOCK_INDEX_KEY
    _normalize_jid = staticmethod(MainWindow._normalize_jid)
    _load_phone_locked_chats = MainWindow._load_phone_locked_chats
    _persist_phone_locked_chats = MainWindow._persist_phone_locked_chats
    _phone_lock_counterpart = MainWindow._phone_lock_counterpart
    _sync_phone_chat_lock = MainWindow._sync_phone_chat_lock
    is_chat_phone_locked = MainWindow.is_chat_phone_locked
    has_phone_locked_chats = MainWindow.has_phone_locked_chats
    _archived_lookup_jids = MainWindow._archived_lookup_jids
    _chat_entry_for_archive = MainWindow._chat_entry_for_archive
    _chat_lock_candidates = MainWindow._chat_lock_candidates
    _chat_lock_vault_holds = MainWindow._chat_lock_vault_holds
    is_chat_locked = MainWindow.is_chat_locked

    def __init__(self, chats=None, vault=None, stored=None):
        self.key = Fernet.generate_key()
        self.chats = chats if chats is not None else {}
        self.db = _Db(stored)
        self._phone_locked_chats = set()
        self._lid_to_phone = {}
        self._phone_to_lid = {}
        self._chat_lock_vault = vault
        self._chat_lock_fingerprints = set()


class TestSync:
    def test_a_locked_record_is_remembered_under_both_names(self):
        mw = _Stub(chats={PHONE: {"remoteJid": PHONE}, LID: {"remoteJid": LID}})
        mw._phone_to_lid = {PHONE: LID}
        chat = {"remoteJid": PHONE, "isLocked": "true"}
        assert mw._sync_phone_chat_lock(chat, PHONE, mw.chats) is True
        assert mw._phone_locked_chats == {PHONE, LID}
        assert mw.chats[LID]["isLocked"] is True and chat["isLocked"] is True

    def test_an_unlock_on_the_phone_takes_the_chat_out_again(self):
        mw = _Stub()
        mw._phone_locked_chats = {PHONE}
        assert mw._sync_phone_chat_lock({"isLocked": False}, PHONE, mw.chats) is True
        assert mw._phone_locked_chats == set()

    def test_a_record_that_states_nothing_changes_nothing(self):
        mw = _Stub()
        mw._phone_locked_chats = {PHONE}
        assert mw._sync_phone_chat_lock({"remoteJid": PHONE}, PHONE, mw.chats) is False
        assert mw._phone_locked_chats == {PHONE}

    def test_the_set_is_stored_sorted_under_one_key(self):
        mw = _Stub()
        mw._phone_locked_chats = {LID, PHONE}
        mw._persist_phone_locked_chats()
        assert mw.db.writes == [("phone_locked_chats", sorted([LID, PHONE]))]

    def test_it_comes_back_after_a_restart(self):
        mw = _Stub(stored={"phone_locked_chats": [PHONE]})
        mw._load_phone_locked_chats()
        assert mw._phone_locked_chats == {PHONE}

    def test_a_failing_database_never_breaks_the_sync_and_logs_no_jid(self, caplog):
        mw = _Stub()
        mw._phone_locked_chats = {PHONE}

        def boom(key, value):
            raise RuntimeError(PHONE)

        mw.db.set_metadata_json = boom
        mw._persist_phone_locked_chats()
        assert PHONE not in caplog.text


class TestLookup:
    def test_a_chat_the_record_says_is_locked(self):
        mw = _Stub(chats={PHONE: {"remoteJid": PHONE, "isLocked": True}})
        assert mw.is_chat_phone_locked(PHONE) is True

    def test_the_record_beats_a_stale_set_entry(self):
        mw = _Stub(chats={PHONE: {"remoteJid": PHONE, "isLocked": False}})
        mw._phone_locked_chats = {PHONE}
        assert mw.is_chat_phone_locked(PHONE) is False

    def test_on_a_cold_start_the_persisted_set_hides_it_before_any_sync(self):
        mw = _Stub(chats={PHONE: {"remoteJid": PHONE}})  # no isLocked on disk
        mw._phone_locked_chats = {PHONE}
        assert mw.is_chat_phone_locked(PHONE) is True

    def test_it_is_found_under_the_other_name_of_the_same_chat(self):
        mw = _Stub(chats={LID: {"remoteJid": LID, "isLocked": True}})
        mw._phone_to_lid = {PHONE: LID}
        assert mw.is_chat_phone_locked(PHONE) is True

    def test_an_unknown_or_empty_jid_is_not_locked(self):
        mw = _Stub(chats={PHONE: {"remoteJid": PHONE, "isLocked": True}})
        assert mw.is_chat_phone_locked("other@s.whatsapp.net") is False
        assert mw.is_chat_phone_locked("") is False

    def test_a_stale_member_no_record_backs_is_not_counted_as_a_locked_chat(self):
        mw = _Stub(chats={PHONE: {"remoteJid": PHONE, "isLocked": False}})
        mw._phone_locked_chats = {PHONE}
        assert mw.has_phone_locked_chats() is False

    def test_a_locked_one_is_counted(self):
        mw = _Stub(chats={PHONE: {"remoteJid": PHONE, "isLocked": True}})
        mw._phone_locked_chats = {PHONE}
        assert mw.has_phone_locked_chats() is True


class TestEveryPlaceThatHidesALockedChat:
    """is_chat_locked() is the one question the list, the tray, the
    notifications and the calls list ask; it must answer yes for both locks."""

    def test_the_phone_lock_hides_a_chat_with_no_vault_at_all(self):
        mw = _Stub(chats={PHONE: {"remoteJid": PHONE, "isLocked": True}})
        assert mw.is_chat_locked(PHONE) is True

    def test_the_vault_still_hides_a_chat(self):
        key = Fernet.generate_key()
        vault = ChatLockVault(key)
        vault.configure("246810", "gizli-kod")
        vault.lock_chat(PHONE)
        mw = _Stub(chats={PHONE: {"remoteJid": PHONE}}, vault=vault)
        mw.key = key
        assert mw.is_chat_locked(PHONE) is True
        assert mw.is_chat_phone_locked(PHONE) is False

    def test_a_chat_nobody_locked_is_visible(self):
        mw = _Stub(chats={PHONE: {"remoteJid": PHONE, "isLocked": False}})
        assert mw.is_chat_locked(PHONE) is False


# ── Unlock and the panel ─────────────────────────────────────────────────────


class _I18n:
    @staticmethod
    def t(key):
        return key


class _UnlockStub(_Stub):
    unlock_chat = MainWindow.unlock_chat
    _chat_lock_unlocked = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.said = []
        self.i18n = _I18n()
        self.persisted = 0
        self.refreshed = 0

    def output(self, text, interrupt=False):
        self.said.append(text)

    def _persist_chat_lock_vault(self):
        self.persisted += 1

    def _schedule_set_chats(self):
        self.refreshed += 1

    def touch_chat_lock_timeout(self):
        pass


def _vault_with(key, jid):
    vault = ChatLockVault(key)
    vault.configure("246810", "gizli-kod")
    vault.lock_chat(jid)
    return vault


class TestUnlock:
    def test_a_vault_chat_is_unlocked_and_announced(self):
        key = Fernet.generate_key()
        mw = _UnlockStub(chats={PHONE: {"remoteJid": PHONE}}, vault=_vault_with(key, PHONE))
        mw.key = key
        mw.unlock_chat(PHONE)
        assert mw.said == ["chat_lock_chat_unlocked"]
        assert mw.is_chat_locked(PHONE) is False

    def test_a_chat_locked_on_the_phone_is_not_announced_as_unlocked(self):
        key = Fernet.generate_key()
        vault = ChatLockVault(key)
        vault.configure("246810", "gizli-kod")
        mw = _UnlockStub(chats={PHONE: {"remoteJid": PHONE, "isLocked": True}}, vault=vault)
        mw.key = key
        mw.unlock_chat(PHONE)
        assert mw.said == ["chat_lock_phone_only"]
        assert mw.is_chat_locked(PHONE) is True

    def test_a_chat_in_both_locks_keeps_hidden_after_the_vault_lets_go(self):
        key = Fernet.generate_key()
        mw = _UnlockStub(
            chats={PHONE: {"remoteJid": PHONE, "isLocked": True}},
            vault=_vault_with(key, PHONE),
        )
        mw.key = key
        mw.unlock_chat(PHONE)
        assert mw.said == ["chat_lock_phone_only"]
        assert mw._chat_lock_vault_holds(PHONE) is False
        assert mw.is_chat_locked(PHONE) is True


class _PanelStub(_Stub):
    show_locked_chats_panel = MainWindow.show_locked_chats_panel
    _require_pin_for_phone_locked_chats = MainWindow._require_pin_for_phone_locked_chats
    _chat_lock_unlocked = False

    class _Vault:
        configured = False

    def __init__(self, chats, pin_answer):
        super().__init__(chats=chats)
        self._chat_lock_vault = self._Vault()
        self.pin_answer = pin_answer
        self.asked = 0
        self.unlock_attempts = 0
        self.panel_filled = False
        self.locked_conversations_panel = self
        self.conversations_panel = self
        self._locked_chat_rows = ([], [])

    def _require_pin_for_phone_locked_chats(self):
        self.asked += 1
        return self.pin_answer

    def unlock_chat_lock_vault(self, show_panel=True):
        self.unlock_attempts += 1
        return False

    def set_all_chats(self, chats, names):
        self.panel_filled = True

    def show_chat_panel(self, which):
        pass

    def touch_chat_lock_timeout(self):
        pass


class TestThePanelNeedsAPinForChatsTheVaultDoesNotHold:
    def test_a_never_set_up_vault_asks_for_a_pin_when_the_phone_locked_something(self):
        mw = _PanelStub({PHONE: {"remoteJid": PHONE, "isLocked": True}}, pin_answer=False)
        mw._phone_locked_chats = {PHONE}
        mw.show_locked_chats_panel()
        assert mw.asked == 1
        assert mw.panel_filled is False  # declined: nothing was listed

    def test_with_nothing_locked_on_the_phone_the_old_behaviour_is_untouched(self):
        mw = _PanelStub({PHONE: {"remoteJid": PHONE}}, pin_answer=False)
        mw.show_locked_chats_panel()
        assert mw.asked == 0
        assert mw.panel_filled is True  # the empty list of a never-set-up vault


# ── the source and the wiring ────────────────────────────────────────────────


class TestWiring:
    MAIN = _read("main.py")
    STORE = _read("main_window", "chats_store.py")
    SYNC = _read("main_window", "sync.py")
    PANEL_UI = _read("ui", "chat_lock.py")

    def test_the_mixin_is_part_of_the_main_window(self):
        assert self.MAIN.count("PhoneChatLockMixin") == 2  # import + base class

    def test_it_is_loaded_at_startup_and_cleared_on_a_wipe(self):
        assert "self._load_phone_locked_chats()" in self.SYNC
        assert "self._phone_locked_chats = set()" in self.STORE

    def test_both_sync_paths_mirror_the_flag_and_persist_only_on_change(self):
        assert self.STORE.count("self._sync_phone_chat_lock(") == 2
        assert self.STORE.count("self._persist_phone_locked_chats()") == 2
        assert self.STORE.count("phone_lock_changed = False") == 2

    def test_unlock_is_not_offered_for_a_chat_only_the_phone_can_unlock(self):
        assert "is_chat_phone_locked(jid)" in self.PANEL_UI
        assert "_chat_lock_vault_holds(jid)" in self.PANEL_UI

    def test_the_bulk_unlock_does_not_claim_a_chat_was_unlocked_when_it_was_not(self):
        assert "if not any(self.main_window.is_chat_locked(jid) for jid in jids):" in self.PANEL_UI

    def test_the_mixin_never_logs_a_jid(self):
        source = _read("main_window", "phone_chat_lock.py")
        assert "type(exc).__name__" in source
        assert not re.search(r"logging\.\w+\([^)]*jid", source)


class TestStringsInEveryLocale:
    NEEDED = ("chat_lock_phone_needs_pin", "chat_lock_phone_only")

    @pytest.mark.parametrize("locale", LOCALES)
    def test_every_string_exists_and_is_not_empty(self, locale):
        strings = json.loads(_read("languages", f"{locale}.json"))
        assert [k for k in self.NEEDED if not str(strings.get(k, "")).strip()] == []
