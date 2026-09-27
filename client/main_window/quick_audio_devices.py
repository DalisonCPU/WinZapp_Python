"""QuickAudioDevicesMixin — part of MainWindow (see main_window/__init__.py).

Ctrl+Alt+Shift+H opens the list of output devices, Ctrl+Alt+Shift+G the list
of recording devices; a digit (or arrows + Enter) switches at once. The choice
is the same one Settings > Audio devices and the call device settings make, so
it is written to both: audio_devices (sounds, playback, voice-message
recording) and call_audio_devices (calls). A call in progress moves to it
without being dropped.

Output goes through SoundSystem.apply_output_device() and then load_sounds(),
exactly as the Settings dialog does it: switching the one BASS device
invalidates every stream created before (docs/traps/audio-devices.md).
"""

import logging

import wx

from core.audio_devices import (
    enumerate_input_devices,
    enumerate_output_devices,
    find_input_device_index,
    test_input_device,
)
from core.quick_audio_devices import KIND_INPUT, KIND_OUTPUT, quick_device_rows


class QuickAudioDevicesMixin:
    """Quick switch between the audio output and recording devices."""

    def _on_quick_output_devices(self, event=None):
        self.open_quick_audio_devices(KIND_OUTPUT)

    def _on_quick_input_devices(self, event=None):
        self.open_quick_audio_devices(KIND_INPUT)

    def _quick_device_names(self, kind: str) -> list:
        devices = enumerate_output_devices() if kind == KIND_OUTPUT else enumerate_input_devices()
        return [name for _, name in devices]

    def open_quick_audio_devices(self, kind: str):
        """Show the quick list for *kind* and apply what the user picks."""
        from ui.dialogs.quick_audio_device_dialog import QuickAudioDeviceDialog

        t = self.i18n.t
        try:
            names = self._quick_device_names(kind)
        except Exception:
            logging.exception("[quick-audio] listing %s devices failed", kind)
            names = []
        current = self.settings.get("audio_devices", {}).get(
            "output_device_name" if kind == KIND_OUTPUT else "input_device_name", "")
        rows, focus = quick_device_rows(
            names, current, t("audio_device_default"), t("quick_audio_device_current"))
        title = t("quick_audio_output_title" if kind == KIND_OUTPUT else "quick_audio_input_title")
        dialog = QuickAudioDeviceDialog(self, title, rows, focus)
        try:
            if dialog.ShowModal() != wx.ID_OK or dialog.chosen is None:
                return
            chosen = dialog.chosen
        finally:
            dialog.Destroy()
        self.apply_quick_audio_device(kind, chosen)

    def apply_quick_audio_device(self, kind: str, name: str) -> bool:
        """Switch *kind* to device *name* ("" = system default) for everything
        that uses one, then say so. A device that will not open changes
        nothing and says that instead."""
        t = self.i18n.t
        shown = name or t("audio_device_default")
        key = "output_device_name" if kind == KIND_OUTPUT else "input_device_name"

        if kind == KIND_OUTPUT:
            if not self.sound_system.apply_output_device(name):
                # apply_output_device() already fell back to the system
                # default; put the device that was working back.
                self.sound_system.apply_output_device(
                    self.settings.get("audio_devices", {}).get(key, ""))
                self.load_sounds()
                self.output(t("quick_audio_device_failed").format(device=shown), interrupt=True)
                return False
            self.load_sounds()
        elif name:
            idx = find_input_device_index(name)
            if idx is None or not test_input_device(idx):
                self.output(t("quick_audio_device_failed").format(device=shown), interrupt=True)
                return False

        self.settings.setdefault("audio_devices", {})[key] = name
        self.settings.setdefault("call_audio_devices", {})[key] = name
        if kind == KIND_INPUT:
            self.effective_input_device_name = name
        self.save_settings()
        logging.info("[quick-audio] %s device set to %r", kind, name or "(default)")

        if getattr(self, "_call_audio_session", None) is not None:
            self._restart_active_voice_call_audio()

        self.output(
            t("quick_audio_output_set" if kind == KIND_OUTPUT else "quick_audio_input_set")
            .format(device=shown),
            interrupt=True,
        )
        return True
