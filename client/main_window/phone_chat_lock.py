"""PhoneChatLockMixin — part of MainWindow (see main_window/__init__.py).

WhatsApp's own Chat Lock, set on the phone and reported by WPPConnect in each
chat record's ``isLocked`` field (core/phone_chat_lock.py has the rules). WinZapp
treats such a chat exactly like one in its own locked-chats vault: it leaves the
main list, the archived list, notifications and the tray, and appears only in the
Locked chats panel after the vault is opened. ChatLockMixin.is_chat_locked() asks
this mixin, so every place that already hides a locked chat hides these too.

The one difference: WinZapp cannot undo it. The phone's code is the only thing
that unlocks it, so Unlock is not offered for these chats (see
ChatLockMixin.unlock_chat()).

The membership set is persisted next to archived_chats for the same reason: a
chat record never carries ``isLocked`` on disk, so after a restart nothing says
which chats the phone locked until the first list-chats answers. Without the
persisted set those chats would sit in the main list for that first moment.

Methods run with ``self`` bound to the MainWindow instance.
"""

import logging

from core import phone_chat_lock


class PhoneChatLockMixin:
    """State and lookups for chats locked with WhatsApp Chat Lock on the phone."""

    _PHONE_LOCK_KEY = "phone_locked_chats"

    def _load_phone_locked_chats(self):
        """Read the persisted membership at startup (see sync.py)."""
        self._phone_locked_chats = set(
            self.db.get_metadata_json(self._PHONE_LOCK_KEY, [])
        )

    def _persist_phone_locked_chats(self):
        db = getattr(self, "db", None)
        if db is None:
            return
        try:
            db.set_metadata_json(self._PHONE_LOCK_KEY, sorted(self._phone_locked_chats))
        except Exception as exc:
            # The type only: nothing here should put a JID in the log.
            logging.warning("[phone_chat_lock] could not persist: %s", type(exc).__name__)

    def _phone_lock_counterpart(self, jid: str) -> str:
        """The same conversation's other JID (LID <-> phone), normalized, or ""."""
        if jid.endswith("@lid"):
            alt = getattr(self, "_lid_to_phone", {}).get(jid, "")
        else:
            alt = getattr(self, "_phone_to_lid", {}).get(jid, "")
        return self._normalize_jid(alt) if alt else ""

    def _sync_phone_chat_lock(self, chat, jid: str, chats: dict) -> bool:
        """Mirror a chat record's stated ``isLocked`` onto the records and the
        persisted set. True when the set changed (the caller then persists).

        Whenever the record states the flag it wins, in both directions: a chat
        the phone unlocked leaves the set instead of staying hidden for ever, and
        a record that states nothing changes nothing.
        """
        flag = phone_chat_lock.stated_flag(chat)
        if flag is None:
            return False
        chat["isLocked"] = flag
        counterpart = self._phone_lock_counterpart(jid)
        for name in (jid, counterpart):
            record = chats.get(name) if name else None
            if isinstance(record, dict):
                record["isLocked"] = flag
        return phone_chat_lock.apply_flag(
            self._phone_locked_chats, (jid, counterpart), flag
        )

    def is_chat_phone_locked(self, jid: str) -> bool:
        """Whether the PHONE has this chat under WhatsApp Chat Lock.

        Same lookup as is_chat_archived(), for the same reasons: a chat's key
        and its remoteJid are not always the same string, and a chat can be filed
        under its LID or its phone JID. A record that states the flag settles it;
        the persisted set decides only when the record says nothing.
        """
        if not jid:
            return False
        members = self._phone_locked_chats
        for candidate in self._archived_lookup_jids(jid):
            key, chat = self._chat_entry_for_archive(candidate)
            flag = phone_chat_lock.stated_flag(chat)
            if flag is not None:
                return flag
            if phone_chat_lock.is_locked(None, (candidate, key), members):
                return True
        return False

    def has_phone_locked_chats(self) -> bool:
        """Whether any chat is locked on the phone right now (a stale member that
        no record backs does not count)."""
        return any(self.is_chat_phone_locked(jid) for jid in list(self._phone_locked_chats))

    def _require_pin_for_phone_locked_chats(self) -> bool:
        """Chats the phone locked must never be shown without a secret, so the
        Locked chats panel needs a PIN even when the person never set up the
        vault. Asks whether to create one (explaining why); True once the vault
        is configured, False if the person declines or cancels.
        """
        import wx

        answer = wx.MessageBox(
            self.i18n.t("chat_lock_phone_needs_pin"),
            self.app_name,
            wx.YES_NO | wx.YES_DEFAULT | wx.ICON_QUESTION,
            self,
        )
        if answer != wx.YES:
            return False
        return bool(self._configure_chat_lock_vault())
