"""Spelling suggestions/sound keep correct offsets without a UIA provider."""

from types import SimpleNamespace
import pytest
from core.text_offsets import native_offset, text_index


@pytest.mark.parametrize("text", ["hello", "😀 wrong\nword", "olá\n\n😀fim", ""])
@pytest.mark.parametrize("newline_width", [1, 2])
def test_windows_offsets_roundtrip(text, newline_width):
    for index in range(len(text) + 1):
        assert text_index(text, native_offset(text, index, newline_width), newline_width) == index


def test_sound_is_played_by_winzapp():
    from ui.conversation_panel.composer import ComposerMixin
    played = []
    stub = SimpleNamespace(main_window=SimpleNamespace(
        spelling_error_sound=SimpleNamespace(play=lambda: played.append(True))))
    ComposerMixin._play_spelling_error_sound(stub)
    assert played == [True]


def test_cursor_cues_checker_without_being_moved():
    from ui.conversation_panel.composer import ComposerMixin
    calls = []
    stub = SimpleNamespace(
        _spell_check_enabled=lambda: True,
        _spell_checker=SimpleNamespace(caret_moved=lambda *args: calls.append(args)),
        message_field=SimpleNamespace(GetValue=lambda: "😀 wrng", GetInsertionPoint=lambda: 4),
    )
    ComposerMixin._cue_spelling_at_caret(stub)
    import os
    assert calls == [("😀 wrng", 3 if os.name == "nt" else 4)]
