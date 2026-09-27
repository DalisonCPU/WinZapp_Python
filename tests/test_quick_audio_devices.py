"""Quick switch between audio devices: Ctrl+Alt+Shift+H (playback) and
Ctrl+Alt+Shift+G (recording), then a digit.

Win+digit combinations were ruled out first: every Win / Win+Alt / Win+Ctrl /
Win+Shift + 1..0 is registered by Explorer for the taskbar (RegisterHotKey
answers 1409, ERROR_HOTKEY_ALREADY_REGISTERED). Alt+8/Alt+9 are kept for
communities and channels. The choice is written to the general devices AND the
call devices. Nothing here opens a window.
"""

import inspect
import types

import pytest
import wx

import main_window.quick_audio_devices as quick_mod
from core.quick_audio_devices import (
    DIGIT_SLOTS,
    KIND_INPUT,
    KIND_OUTPUT,
    digit_for_slot,
    quick_device_rows,
    slot_for_digit,
)
from main import MainWindow
from ui.dialogs.quick_audio_device_dialog import QuickAudioDeviceDialog, typed_digit


# ── The list ──────────────────────────────────────────────────────────────────


def test_digits_follow_the_keyboard_row():
    assert [digit_for_slot(s) for s in range(10)] == list("1234567890")
    assert [slot_for_digit(d) for d in "1234567890"] == list(range(10))
    assert slot_for_digit("x") is None
    assert slot_for_digit("12") is None


def test_rows_number_ten_devices_then_the_default():
    names = [f"Dev {i}" for i in range(12)]
    rows, focus = quick_device_rows(names, "Dev 2", "Padrão", "(em uso)")
    labels = [label for label, _ in rows]
    assert labels[0] == "1. Dev 0"
    assert labels[2] == "3. Dev 2 (em uso)"
    assert labels[9] == "0. Dev 9"
    assert labels[10] == "Dev 10"          # past the tenth: no digit
    assert rows[-1] == ("Padrão", "")       # default last, value ""
    assert focus == 2
    assert DIGIT_SLOTS == 10


def test_the_default_is_marked_when_it_is_in_use():
    rows, focus = quick_device_rows(["A", "B"], "", "Padrão", "(em uso)")
    assert rows[-1] == ("Padrão (em uso)", "")
    assert focus == len(rows) - 1


def test_a_saved_device_that_is_unplugged_reads_as_the_default():
    """WinZapp is on the system default then, so that is what is in use."""
    rows, focus = quick_device_rows(["A", "B"], "Fone USB", "Padrão", "(em uso)")
    assert not any("(em uso)" in label for label, _ in rows[:-1])
    assert rows[focus] == ("Padrão (em uso)", "")


# ── The dialog's keys (a stub, never a window) ─────────────────────────────────


def test_typed_digit_reads_top_row_and_keypad():
    assert typed_digit(ord("3")) == "3"
    assert typed_digit(ord("0")) == "0"
    assert typed_digit(wx.WXK_NUMPAD7) == "7"
    assert typed_digit(ord("A")) is None


class _DialogStub:
    _on_char_hook = QuickAudioDeviceDialog._on_char_hook

    def __init__(self, rows, selected=0):
        self._rows = rows
        self.picked = []
        self.list = types.SimpleNamespace(GetSelection=lambda: selected)

    def _pick(self, index):
        self.picked.append(index)


def _key(code, modifiers=False):
    ev = types.SimpleNamespace(skipped=False)
    ev.GetKeyCode = lambda: code
    ev.HasAnyModifiers = lambda: modifiers
    ev.Skip = lambda: setattr(ev, "skipped", True)
    return ev


class TestDialogKeys:
    ROWS, _ = quick_device_rows(["A", "B", "C"], "A", "Padrão", "(em uso)")

    def test_a_digit_picks_its_device_at_once(self):
        d = _DialogStub(self.ROWS)
        d._on_char_hook(_key(ord("2")))
        assert d.picked == [1]

    def test_a_digit_with_no_device_behind_it_does_nothing(self):
        """"4" would land on the default row, which has no digit."""
        d = _DialogStub(self.ROWS)
        ev = _key(ord("4"))
        d._on_char_hook(ev)
        assert d.picked == [] and ev.skipped

    def test_enter_picks_the_focused_row(self):
        d = _DialogStub(self.ROWS, selected=3)
        d._on_char_hook(_key(wx.WXK_RETURN))
        assert d.picked == [3]

    def test_modified_keys_and_arrows_pass_through(self):
        d = _DialogStub(self.ROWS)
        for ev in (_key(ord("2"), modifiers=True), _key(wx.WXK_DOWN)):
            d._on_char_hook(ev)
            assert ev.skipped
        assert d.picked == []


# ── Applying the choice ────────────────────────────────────────────────────────


class _SoundSystem:
    def __init__(self, ok=True):
        self.ok = ok
        self.applied = []

    def apply_output_device(self, name, warn_on_failure=False):
        self.applied.append(name)
        return self.ok if name == "Novo" else True


class _Stub:
    apply_quick_audio_device = MainWindow.apply_quick_audio_device
    open_quick_audio_devices = MainWindow.open_quick_audio_devices

    def __init__(self, sound_ok=True, in_call=False):
        self.settings = {"audio_devices": {"output_device_name": "Antigo",
                                           "input_device_name": "Mic antigo"},
                         "call_audio_devices": {"output_device_name": "Antigo",
                                                "input_device_name": "Mic antigo"}}
        self.i18n = types.SimpleNamespace(t=lambda k: {"audio_device_default": "Padrão"}.get(k, k + "{device}"))
        self.sound_system = _SoundSystem(sound_ok)
        self._call_audio_session = object() if in_call else None
        self.events = []

    def load_sounds(self):
        self.events.append("load_sounds")

    def save_settings(self):
        self.events.append("save")

    def _restart_active_voice_call_audio(self):
        self.events.append("restart_call")

    def output(self, text, interrupt=False):
        self.events.append(("say", text))


class TestApply:
    def test_output_switches_live_reloads_sounds_and_covers_calls(self):
        s = _Stub()
        assert s.apply_quick_audio_device(KIND_OUTPUT, "Novo") is True
        assert s.sound_system.applied == ["Novo"]
        assert s.settings["audio_devices"]["output_device_name"] == "Novo"
        assert s.settings["call_audio_devices"]["output_device_name"] == "Novo"
        # Sounds are recreated after the BASS switch (docs/traps/audio-devices.md).
        assert s.events.index("load_sounds") < s.events.index("save")
        assert ("say", "quick_audio_output_setNovo") in s.events

    def test_an_output_that_will_not_open_changes_nothing(self):
        s = _Stub(sound_ok=False)
        assert s.apply_quick_audio_device(KIND_OUTPUT, "Novo") is False
        assert s.sound_system.applied == ["Novo", "Antigo"]   # put back
        assert s.settings["audio_devices"]["output_device_name"] == "Antigo"
        assert s.settings["call_audio_devices"]["output_device_name"] == "Antigo"
        assert "save" not in s.events
        assert ("say", "quick_audio_device_failedNovo") in s.events

    def test_input_is_tested_then_used_for_voice_messages_and_calls(self, monkeypatch):
        monkeypatch.setattr(quick_mod, "find_input_device_index", lambda name: 4)
        monkeypatch.setattr(quick_mod, "test_input_device", lambda idx: True)
        s = _Stub()
        assert s.apply_quick_audio_device(KIND_INPUT, "Mic novo") is True
        assert s.settings["audio_devices"]["input_device_name"] == "Mic novo"
        assert s.settings["call_audio_devices"]["input_device_name"] == "Mic novo"
        assert s.effective_input_device_name == "Mic novo"
        assert "load_sounds" not in s.events

    def test_an_input_that_will_not_open_changes_nothing(self, monkeypatch):
        monkeypatch.setattr(quick_mod, "find_input_device_index", lambda name: 4)
        monkeypatch.setattr(quick_mod, "test_input_device", lambda idx: False)
        s = _Stub()
        assert s.apply_quick_audio_device(KIND_INPUT, "Mic novo") is False
        assert s.settings["audio_devices"]["input_device_name"] == "Mic antigo"
        assert "save" not in s.events

    def test_the_default_needs_no_test(self, monkeypatch):
        monkeypatch.setattr(quick_mod, "find_input_device_index",
                            lambda name: pytest.fail("the default was probed"))
        s = _Stub()
        assert s.apply_quick_audio_device(KIND_INPUT, "") is True
        assert s.settings["call_audio_devices"]["input_device_name"] == ""
        assert ("say", "quick_audio_input_setPadrão") in s.events

    def test_a_call_in_progress_moves_without_being_dropped(self):
        s = _Stub(in_call=True)
        s.apply_quick_audio_device(KIND_OUTPUT, "Novo")
        assert "restart_call" in s.events


class _FakeDialog:
    answer = None

    def __init__(self, parent, title, rows, focus):
        type(self).seen = (title, rows, focus)
        self.chosen = type(self).answer

    def ShowModal(self):
        return wx.ID_OK if self.chosen is not None else wx.ID_CANCEL

    def Destroy(self):
        pass


class TestOpen:
    @pytest.fixture(autouse=True)
    def _fakes(self, monkeypatch):
        import ui.dialogs.quick_audio_device_dialog as dlg_mod
        monkeypatch.setattr(dlg_mod, "QuickAudioDeviceDialog", _FakeDialog)

    def test_the_pick_is_applied(self):
        s = _Stub()
        s._quick_device_names = lambda kind: ["Antigo", "Novo"]
        applied = []
        s.apply_quick_audio_device = lambda kind, name: applied.append((kind, name))
        _FakeDialog.answer = "Novo"

        s.open_quick_audio_devices(KIND_OUTPUT)

        assert applied == [(KIND_OUTPUT, "Novo")]
        title, rows, focus = _FakeDialog.seen
        assert title == "quick_audio_output_title{device}"
        assert rows[focus][1] == "Antigo"      # opens on the device in use

    def test_cancel_changes_nothing(self):
        s = _Stub()
        s._quick_device_names = lambda kind: ["Antigo"]
        s.apply_quick_audio_device = lambda *a: pytest.fail("applied on cancel")
        _FakeDialog.answer = None
        s.open_quick_audio_devices(KIND_INPUT)


def test_the_shortcuts_are_in_the_frame_table():
    src = inspect.getsource(MainWindow.create_accelerator_table)
    assert "ord('H'), self.ID_CTRL_ALT_SHIFT_H" in src
    assert "ord('G'), self.ID_CTRL_ALT_SHIFT_G" in src
    assert "self._on_quick_output_devices, id=self.ID_CTRL_ALT_SHIFT_H" in src
    assert "self._on_quick_input_devices, id=self.ID_CTRL_ALT_SHIFT_G" in src
