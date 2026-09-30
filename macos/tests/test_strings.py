"""Every WinZapp locale has every Mac string (WinZapp rule 2)."""

import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [os.path.join(ROOT, "macos"), os.path.join(ROOT, "client")]

from winzapp_mac import strings_mac  # noqa: E402

LOCALES = sorted(json.load(open(os.path.join(ROOT, "client", "languages", "language_map.json"),
                                encoding="utf-8")))
EN = strings_mac.load_overlay("en-US")


@pytest.mark.parametrize("locale", LOCALES)
def test_overlay_exists_with_every_key(locale):
    overlay = strings_mac.load_overlay(locale)
    assert set(overlay) == set(EN), f"{locale}: missing {set(EN) - set(overlay)}"


@pytest.mark.parametrize("locale", LOCALES)
def test_overlay_keeps_placeholders_and_names_no_windows(locale):
    overlay = strings_mac.load_overlay(locale)
    for key, text in overlay.items():
        assert "Windows" not in text, (locale, key)
        assert ("{device}" in text) == ("{device}" in EN[key]), (locale, key)


@pytest.mark.parametrize("locale", LOCALES)
def test_overridden_keys_exist_upstream(locale):
    with open(os.path.join(ROOT, "client", "languages", f"{locale}.json"), encoding="utf-8") as fh:
        upstream = json.load(fh)
    own = {"mac_not_yet_available"}
    stale = [k for k in strings_mac.load_overlay(locale) if k not in upstream and k not in own]
    assert not stale, f"{locale}: overlay keys no longer in WinZapp: {stale}"


def test_overlay_wins_and_other_windows_mentions_become_macos():
    out = strings_mac.mac_wording("pt-BR", {"autostart_ask_title": "Iniciar o WinZapp com o Windows",
                                             "x": "padrão do Windows"})
    assert out["autostart_ask_title"] == "Iniciar o WinZapp ao iniciar sessão"
    assert out["x"] == "padrão do macOS"


def test_text_follows_the_users_language_even_before_get_language():
    from core import i18n
    strings_mac.install()

    class MW:
        settings = {"general": {"language": "en-US"}}

    tr = i18n.I18n(MW())                     # never told to get_language()
    assert "Não" not in tr.t("no_pairing_code_received")
    assert tr.t("no_pairing_code_received").startswith("Could not connect") or "pairing" in tr.t("no_pairing_code_received").lower()
