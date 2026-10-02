# macOS build (`macos/`)

A separate, Mac-only layer (`macos/winzapp_mac`) replaces Windows-only
pieces at startup; the Windows build never runs it. In `client/` the Mac
has only `<key>_macos` strings and `start.js`'s user agent. Its maintainer is
listed in `macos/README.md`; build and updater details are there too.

What it asks of a Windows change:

- A rename or removal of something the layer patches or reads fails
  `tests/test_macos_layer_contract.py` (fix the name in `macos/winzapp_mac`
  or tell its maintainer).
- A string that names Windows may get a `<key>_macos` variant beside it,
  kept in every locale like any key.
- Nothing else is constrained, and a Windows change never needs a Mac.

## Commit provenance

The Mac updater installs a build only if it is tied to a commit of
`gabrielhhaber/WinZapp_Python`, on top of the Apple Team ID, `codesign` and
`spctl` checks. Mac releases are published from another repository, so the
Apple signature alone says who built it, not which code. The pure verifier is
`macos/winzapp_mac/provenance.py`; its tests run in the normal `pytest`
(`tests/test_macos_provenance.py`). The threat model, the exact steps and the
release procedure are in `macos/README.md`, "Commit provenance". For a
Windows change: nothing, except that the official repository name is pinned
in `provenance.py` and the layer reads `version.__version__`.
