# WinZapp for macOS

A native macOS build of WinZapp, made for VoiceOver users. Everything
Mac-specific lives in this folder; WinZapp's Windows code is unchanged and
the Windows build is unaffected.

## How it works

`winzapp_mac/` is a compatibility layer installed before WinZapp's
`client/main.py` runs (by `launcher.py` in development, by a PyInstaller
runtime hook in the app). It swaps Windows-only pieces for Mac equivalents
and adapts WinZapp's UI to how Mac apps and VoiceOver behave:

| Module | What it does on the Mac |
|---|---|
| `listctrl.py`, `native_rows.py` | `wx.ListCtrl` is invisible to VoiceOver on macOS (wxGenericListCtrl, custom-drawn). Every list becomes a native table; rows answer VO-Space (activate, like Enter), VO-Shift-M (the row's context menu) and offer the context-menu items as VoiceOver actions (VO-Command-Space), read from WinZapp's own menu handlers so new items appear automatically. |
| `accessibility_mac.py` | `wx.Accessible` does nothing on macOS; its names, descriptions and shortcuts are bridged to NSAccessibility, and unlabelled fields take the label before them, as NVDA does. |
| `speech.py` | Speech goes to VoiceOver as NSAccessibility announcements (no AppleScript setting needed); the system voice is the fallback instead of SAPI. |
| `keymap_mac.py` | Shortcuts follow one rule — Ctrl becomes Command, Alt becomes Command-Option, Ctrl+Alt becomes Control-Command — with exceptions where the rule would hit a macOS command (e.g. Exit is Command-Q, archive is Control-Command-A). Menus, hints and the shortcuts help speak the Mac keys. Option+letter keeps typing characters. |
| `menubar_mac.py` | Settings, About and Quit in the application menu; Chats and Messages menus mirroring the selected row's context menu; the Windows self-updater is off. |
| `notify_mac.py` | Native notifications with reply and quick reactions as actions; Focus modes apply. |
| `lifecycle_mac.py` | Closing the window keeps WinZapp running (it still receives messages); the Dock icon brings it back; quitting leaves the Dock immediately. |
| `server_mac.py` | Stops the Node server on quit (the Mac equivalent of `taskkill /F /T`). |
| `paths_mac.py` | Data and the paired session live in `~/Library/Application Support/WinZapp`; the app installs its bundled server runtime there at launch. |
| `sound_mac.py`, `audio_mac.py` | Universal BASS dylibs and the Opus plugin; bundled ffmpeg; the microphone recovers when CoreAudio restarts. |
| `spell_mac.py`, `camera_mac.py`, `hotkey_mac.py`, `platform_mac.py` | Spell checking with the Mac's dictionaries, the camera through AVFoundation, the global hotkey through Carbon's RegisterEventHotKey (no Accessibility permission), Show in Finder, macOS region and language. |
| `strings_mac.py`, `languages/` | Mac wording in all seven locales (overlay on `client/languages`). |

## Building

Needs Python 3.13 and Homebrew's PortAudio (`brew install portaudio`).

    python3 macos/build_app.py --zip

builds `macos/dist/WinZapp.app` for the Mac it runs on (Apple Silicon or
Intel) and `WinZapp-macOS-<arch>.zip`. It installs the Python
dependencies into `.pydeps/`, downloads the pinned Node.js and ffmpeg
(SHA-256 checked), runs `setup_api.py`, and bundles the WPPConnect server
and its headless Chrome inside the app. `.github/workflows/build-macos.yml`
does this for both architectures on every pull request.

Development run without building: `python3 macos/launcher.py`.

Tests: `PYTHONPATH=.pydeps python3 -m pytest macos/tests -c /dev/null --rootdir macos/tests`.
They never show a window.

## Not yet on the Mac

- **Recording microphone + computer audio.** Windows uses WASAPI; the Mac
  needs a Core Audio process-tap recorder (macOS 14.2+), which would also
  allow a separate VoiceOver volume like the NVDA one. The button is shown
  dimmed and says so.
- **Do Not Disturb for WinZapp's own sounds.** Mac notifications follow
  Focus, but macOS offers no public way for an app to read Focus, so
  WinZapp's sounds still play.
- **Updates.** WinZapp's updater installs Windows releases and is off on the
  Mac. Mac builds would need a macOS asset in the releases and the updater
  taught to install it.

## Opening a downloaded build

The app is ad-hoc signed, not notarized (that needs an Apple Developer ID).
macOS blocks a downloaded copy the first time: open it once, then allow it
in System Settings, Privacy & Security ("Open Anyway").
