"""Keyboard mnemonics of the WhatsApp lists buttons, in every locale.

The two buttons on the chat screen and the buttons of the lists dialog each
carry an Alt+letter. A mnemonic that repeats inside its window, or that
repeats a menu-bar mnemonic or a global Alt shortcut, activates the wrong
thing or nothing, and no screen reader says so. Which letter a locale picks is
its own decision; this checks only that the picks do not collide.
"""

import json
import re
from types import SimpleNamespace

import pytest

from app_paths import resource_path
from ui.dialogs.chat_lists import _manage_title

#: Buttons on the chat screen (WhatsAppListFilterMixin).
MAIN_KEYS = ("wa_lists_reload", "wa_lists_manage")
#: Buttons of WhatsAppListsDialog. "manage" is its title, not a button.
DIALOG_KEYS = ("wa_lists_reload", "wa_lists_create", "wa_lists_rename",
               "wa_lists_delete", "wa_lists_add", "wa_lists_remove")
#: What the main window's menu bar opens with Alt.
MENU_KEYS = ("menu_file", "menu_sync", "menu_help")
#: Global Alt+letter shortcuts of the main window (the shortcut_* strings).
RESERVED = set("bcelmrt")


def _load(name):
    with open(resource_path("languages", f"{name}.json"), "r", encoding="utf-8") as f:
        return json.load(f)


LOCALES = sorted(_load("language_map"))


def _mnemonic(text):
    found = re.search(r"&([^&])", text.replace("&&", ""))
    return found.group(1).casefold() if found else None


@pytest.fixture(params=LOCALES)
def strings(request):
    return _load(request.param)


def test_every_lists_button_has_a_mnemonic(strings):
    missing = [k for k in set(MAIN_KEYS + DIALOG_KEYS) if _mnemonic(strings[k]) is None]
    assert not missing


def test_the_dialog_buttons_do_not_share_a_letter(strings):
    letters = [_mnemonic(strings[k]) for k in DIALOG_KEYS]
    assert len(set(letters)) == len(letters), letters


def test_the_chat_screen_buttons_do_not_collide_with_the_menu_or_shortcuts(strings):
    letters = [_mnemonic(strings[k]) for k in MAIN_KEYS]
    taken = {_mnemonic(strings[k]) for k in MENU_KEYS} | RESERVED
    assert len(set(letters)) == len(letters), letters
    assert not set(letters) & taken, (letters, taken)


def test_the_dialog_title_has_no_mnemonic_marker():
    i18n = SimpleNamespace(t=lambda key: "Mana&ge WhatsApp lists")
    assert _manage_title(i18n) == "Manage WhatsApp lists"


NEW_CONTACT_KEYS = ("contact_name", "contact_surname", "create_contact", "cancel")


def test_the_save_to_phone_button_shares_no_letter_with_the_new_contact_dialog(strings):
    """create_contact_phone is the main button of the synced tab; a letter it
    shares with a field or another button would make Alt+letter ambiguous."""
    letter = _mnemonic(strings["create_contact_phone"])
    assert letter is not None
    assert letter not in {_mnemonic(strings[k]) for k in NEW_CONTACT_KEYS}
