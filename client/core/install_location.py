"""Whether WinZapp is running from a network folder, where it cannot work.

WinZapp keeps its data, the WPPConnect Server it installs with npm and the
Chrome profile holding the WhatsApp login next to the program (app_paths).
From a network folder none of that holds up, and the failure a user sees
explains nothing:

- `npm install` runs package install scripts through cmd.exe, which refuses a
  UNC path as its current directory, falls back to C:\\Windows, and the
  script is then "not found" — reported from a Windows 11 ARM machine in
  Parallels, whose Downloads folder is the Mac's (\\\\Mac\\Home\\Downloads):
  a wall of npm output, twice, and no WinZapp.
- the message database is SQLite in WAL mode, which SQLite itself says not to
  use on a network filesystem (its locking is not reliable there), and the
  Chrome profile is the only copy of the login (docs/traps/profile-recovery.md).

The fix for the user is to install it (WinZappInstaller puts it under
%LOCALAPPDATA%) or move the folder to a local disk; this module only answers
the question, so MainWindow can say so before anything is installed.
"""

from __future__ import annotations

import ntpath
import sys

# GetDriveTypeW's answer for a drive letter mapped to a network share.
DRIVE_REMOTE = 4


def _windows_drive_type(root: str) -> int:
    import ctypes
    return int(ctypes.windll.kernel32.GetDriveTypeW(root))


def is_network_path(path: str, drive_type_of=None) -> bool:
    """True for a UNC path (\\\\server\\share\\..., \\\\?\\UNC\\...) or a
    drive letter mapped to a network share.

    `drive_type_of(root)` returns GetDriveTypeW for "X:\\"; None uses the real
    call on Windows and treats every drive as local elsewhere.
    """
    if not path:
        return False
    norm = str(path).replace("/", "\\")
    upper = norm.upper()
    if upper.startswith("\\\\?\\UNC\\"):
        return True
    if upper.startswith("\\\\?\\") or upper.startswith("\\\\.\\"):
        norm = norm[4:]
    elif norm.startswith("\\\\"):
        return True
    drive, _rest = ntpath.splitdrive(norm)
    if len(drive) != 2 or drive[1] != ":":
        return False
    if drive_type_of is None:
        if sys.platform != "win32":
            return False
        drive_type_of = _windows_drive_type
    try:
        return drive_type_of(drive.upper() + "\\") == DRIVE_REMOTE
    except Exception:
        # Could not tell: never refuse a start on a guess.
        return False
