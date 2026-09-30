"""Mac wording for WinZapp's user-facing strings, in every locale.

macos/languages/<locale>.json overlays WinZapp's client/languages files:
Mac phrasing for strings that describe Windows ("Start WinZapp with
Windows" -> "Start WinZapp at login"), plus the Mac layer's own strings.
Kept beside the layer rather than edited into client/languages so upstream
translation updates merge cleanly. macos/tests/test_strings.py checks every
locale in client/languages/language_map.json has every overlay key.

Any other string that still names Windows gets "macOS" as a fallback.
"""

import json
import os
import re
import sys

_WINDOWS = re.compile(r"\bWindows\b")


def overlay_dir():
    if getattr(sys, "frozen", False):
        return os.path.join(sys._MEIPASS, "macos_languages")
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "languages")


def load_overlay(lang_code):
    path = os.path.join(overlay_dir(), f"{lang_code}.json")
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def mac_wording(lang_code, data):
    overlay = load_overlay(lang_code)
    for k, v in list(data.items()):
        if isinstance(v, str) and k not in overlay and "Windows" in v:
            data[k] = _WINDOWS.sub("macOS", v)
    data.update(overlay)
    return data


def install():
    from core import i18n
    orig = i18n._load_translations

    def load(lang_code):
        return mac_wording(lang_code, orig(lang_code))

    i18n._load_translations = load

    # Each I18n starts at "pt-BR" and only follows the user's language once
    # something calls get_language(); a message produced before that (seen
    # live: a pairing error on an English install) came out in Portuguese.
    # Read the setting on every lookup — it is a dict access.
    orig_t = i18n.I18n.t

    def t(self, key):
        try:
            self.get_language()
        except Exception:
            pass
        return orig_t(self, key)

    i18n.I18n.t = t
