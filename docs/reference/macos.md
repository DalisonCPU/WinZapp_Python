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
