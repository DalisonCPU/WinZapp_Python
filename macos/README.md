# WinZapp for macOS

A native macOS build of WinZapp, made for VoiceOver users. Everything
Mac-specific lives in this folder; WinZapp's Windows code is unchanged and
the Windows build is unaffected.

Maintained by Rocco Fiorentino (@rfiorentino1). Windows changes never need
to be tested on a Mac; see "What Windows changes can break" below.

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
| `strings_mac.py` | Mac wording: a string that describes Windows has a Mac variant beside it in `client/languages` (`<key>_macos`), used in its place on the Mac. |
| `focus_mac.py` | WinZapp's quiet-hours gate follows macOS Focus (Developer ID builds with the Communication Notifications entitlement). |
| `updater_mac.py` | Signed release builds update from the macOS release feed named in their Info.plist; without one the updater is off. |

## Building

Needs Python 3.13 and Homebrew's PortAudio (`brew install portaudio`).

    python3 macos/build_app.py --zip

builds `macos/dist/WinZapp.app` for the Mac it runs on (Apple Silicon or
Intel) and `WinZapp-macOS-<arch>.zip`. It installs the Python
dependencies into `.pydeps/`, downloads the pinned Node.js and ffmpeg
(SHA-256 checked), runs `setup_api.py`, and bundles the WPPConnect server
and its headless Chrome inside the app. `.github/workflows/build-macos.yml`
does this for both architectures on pull requests that touch the Mac build.

Development run without building: `python3 macos/launcher.py`.

Tests: `PYTHONPATH=.pydeps python3 -m pytest macos/tests -c /dev/null --rootdir macos/tests`.
They never show a window.

## What Windows changes can break

The layer never edits WinZapp's files; it replaces WinZapp functions and
methods at startup. So on the Windows side:

- **Renaming or removing** a function, class or method the layer patches or
  reads fails `tests/test_macos_layer_contract.py` in the normal `pytest`
  run, on any platform, naming the file and line in `macos/winzapp_mac` to
  update. Nothing else in `client/` is constrained.
- **A new string that mentions Windows** shows "macOS" in its place on the
  Mac. For better wording, add `<key>_macos` next to it in every locale
  (checked by the same tests as any other key).
- Everything else, including behaviour changes inside a patched method, is
  the Mac maintainer's to follow up; the Windows build never runs Mac code.

## Not yet on the Mac

- **Recording microphone + computer audio.** Windows uses WASAPI; the Mac
  needs a Core Audio process-tap recorder (macOS 14.2+), which would also
  allow a separate VoiceOver volume like the NVDA one. The button is shown
  dimmed and says so.

## Opening a downloaded build

A build without `WINZAPP_SIGN_IDENTITY` (such as the pull-request workflow's)
is ad-hoc signed, not notarized. macOS blocks a downloaded copy the first time: open it once, then allow it
in System Settings, Privacy & Security ("Open Anyway").

## Commit provenance

Mac releases are published from the maintainer's fork, so the Apple
signature proves who built an update, not that its code went through this
repository. The updater therefore also requires the release to be tied to a
commit of `gabrielhhaber/WinZapp_Python`. Code: `winzapp_mac/provenance.py`
(pure standard library, tested on any platform by
`tests/test_macos_provenance.py`).

**Threat model.** The attacker controls the releases repository (its assets,
its CI secrets) and can publish any zip and any provenance there. They cannot
push a tag to the official repository. A tag in the official repository
exists only because someone with write access there created it, which is the
same trust the Windows releases rest on. A Mac release that never went
through the official repository must not install.

**What is verified, in this order.** Any failure, or any answer that is not a
clean 200 (offline, timeout, rate limit, redirect, oversized, malformed), is a
refusal: nothing is downloaded or installed, the dialog says "could not
verify commit provenance" and the next update check tries again.

1. The release has `WinZapp-macOS-provenance-<arch>.json` (fetched from the
   releases repository by tag; untrusted content). It must have exactly the
   fields `schema` (1), `version`, `source_repo`, `source_commit`,
   `artifacts`, with `source_repo` equal to the official repository
   (pinned in the code), `source_commit` 40 lowercase hex, `version` a
   release tag (`v1.2.3.4`, optionally `alpha`/`beta`), at most 8 artifacts of
   name to 64-hex sha256, at most 16 KB.
2. `version` equals the tag of the release being installed, is newer than the
   running version, and `source_commit` is not the commit already running
   (`WinZappSourceCommit` in Info.plist). A genuine provenance of an older
   release cannot ride on a newer tag.
3. Over HTTPS to `api.github.com/repos/gabrielhhaber/WinZapp_Python` only,
   unauthenticated, no redirects, 15 s timeout, 256 KB cap: `git/ref/tags/<tag>`
   exists, and, peeled through annotated tag objects (`git/tags/<sha>`), is
   exactly `source_commit`.
4. The downloaded zip's sha256 equals the provenance's and the release's
   `SHA256SUMS.txt`.
5. As before: the app inside has the running app's Apple Team ID, passes
   `codesign --verify --deep --strict`, and `spctl` (notarized).

**Why the tag and not "the commit exists in our repo".** GitHub serves a
fork's commits through the parent's `/commits/<sha>` API, so that answers 200
for code that was never in our repository. The tag is fork-proof. A compare
against `main` (ancestor, "behind"/"identical") would also prove "reachable
from main", but costs another call against the 60 an hour unauthenticated
limit and would refuse a hotfix tag on another branch, so it is not used.
Provenance is one file per architecture (`-arm64`, `-x86_64`) so the two build
jobs never merge or overwrite a shared file.

**What it does not prove.** That the zip was built from that commit. A
releaser can build a modified tree and name an honest commit. `build_app.py`
refuses a dirty tracked tree and a HEAD that is not the tag, but that runs on
the releaser's machine. Only a reproducible build, or an attestation verified
by the updater, would prove it. Tags can be moved by anyone with write access
to the official repository (protect `v*` with a tag ruleset); a compromised
maintainer account is out of scope here as it is for Windows. The check is
also only as live as GitHub's API: it cannot run offline.

**How a release is produced (Rocco).** On a clean checkout of the commit the
maintainer tagged in the official repository (`git fetch` the official tags,
check out the tag; or set `WINZAPP_RELEASE_TAG=v2.0.0.5` when the checkout has
no tags, but HEAD must still be that tag's commit):

    WINZAPP_MAC_RELEASES_REPO=rocco-labs/WinZapp_Python \
    WINZAPP_SIGN_IDENTITY=... python3 macos/build_app.py --zip

`build_app.py` resolves the tag against the official API *before* building and
stops if HEAD differs, tracked files are modified, or a release build has no
tag. It writes the commit into Info.plist (`WinZappSourceCommit`, before
signing) and, next to the zip, `macos/dist/WinZapp-macOS-provenance-<arch>.json`.
Upload to the release named by that tag (same tag name as the official one):
`WinZapp-macOS-<arch>.zip`, `WinZapp-macOS-provenance-<arch>.json` and
`SHA256SUMS.txt` covering the zips, for both architectures. An untagged build
makes no provenance and does not self-update (development builds never do).
The app's running version (`client/version.py`) must be stamped to the tag's
version before building, or the updater sees every release as not newer.

**What the maintainer does.** Nothing new: tag as today. The tag is the
approval.

**Optional, recommended: artifact attestations.** In the workflow that builds
the release, `actions/attest-build-provenance` (pinned by SHA, with
`id-token: write` and `attestations: write` on that job only) signs the zip's
digest with the workflow's identity, and `gh attestation verify <zip> --repo
<releases repo>` checks it. That would show which workflow built the zip, and
a future updater could require it. It needs no secret, but whether a release
workflow exists is decided in issue #343; nothing here adds one.
