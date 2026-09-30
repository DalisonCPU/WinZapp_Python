"""Log every message box WinZapp shows, with its text and caller.

Several dialogs have appeared that nothing in log.log accounts for (a
Portuguese pairing error on an English, already-paired install). WinZapp
calls wx.MessageBox directly in many places; logging each one with its text
and the call stack makes the next occurrence traceable.

log.log masks phone numbers and LIDs in its formatter
(core/pii_redaction.py); the separate file gets the same masking here,
since a message box can quote a contact's number.
"""

import logging
import os
import time
import traceback

import wx

_orig_message_box = wx.MessageBox
LOG_DIR = os.path.expanduser("~/Library/Logs/WinZapp")


def persistent_entry(caption, message, stack, when=None):
    """The message-boxes.log entry, phone numbers and LIDs masked."""
    from core.pii_redaction import redact_phone
    when = when or time.strftime("%Y-%m-%d %H:%M:%S")
    return redact_phone(f"{when} {caption!r} | {message!r}\n{stack}\n")


def _logged_message_box(message, caption=wx.MessageBoxCaptionStr, style=wx.OK | wx.CENTRE,
                        parent=None, x=wx.DefaultCoord, y=wx.DefaultCoord):
    try:
        stack = "".join(traceback.format_stack(limit=8)[:-1])
        logging.warning("[message-box] %r | %r\n%s", caption, message, stack)
        # log.log is truncated at every launch; keep these across restarts.
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(os.path.join(LOG_DIR, "message-boxes.log"), "a", encoding="utf-8") as fh:
            fh.write(persistent_entry(caption, message, stack))
    except Exception:
        pass
    return _orig_message_box(message, caption, style, parent, x, y)


def install():
    wx.MessageBox = _logged_message_box
