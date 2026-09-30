"""Whether the open conversation's panel is the one being shown.

ConversationsPanel keeps its conversation open while the user is on another
panel (Alt+4 archived, Alt+5 status, ...): coming back must not mean finding
the chat again. But an open conversation whose panel is hidden is not being
read, so it must not be marked read, notified as "the current chat" or kept
out of the unread counts.
"""


def conversation_in_view(panel) -> bool:
    """True when `panel` has a conversation open and is itself shown.

    IsShown() of the panel, not IsShownOnScreen(): the panel is a direct child
    of the content area and the panel switches (Alt+4/5/6) Hide() it, while a
    window hidden to the tray or minimized must keep counting as "open" (the
    unread bookkeeping for a hidden window relies on that). A stand-in
    without the method counts as shown, so callers keep their old behaviour.
    """
    if panel is None or getattr(panel, "conversation", None) is None:
        return False
    shown = getattr(panel, "IsShown", None)
    if shown is None:
        return True
    try:
        if not shown():
            return False
    except RuntimeError:  # wx object already destroyed
        return False
    # The archived list can sit next to the open conversation (Alt+4 keeps it
    # visible). Then the conversation is being read only while focus is
    # inside it (Tab, Alt+2, Alt+M all move it there); on the list it is
    # visible but not read.
    if not archived_panel_is_shown(getattr(panel, "main_window", None)):
        return True
    return _focus_is_inside(panel)


def _focused_window():
    try:
        import wx
        return wx.Window.FindFocus()
    except Exception:
        return None


def _focus_is_inside(panel) -> bool:
    window = _focused_window()
    while window is not None:
        if window is panel:
            return True
        try:
            window = window.GetParent()
        except RuntimeError:  # wx object already destroyed
            return False
    return False


def archived_chat_stays_silent(is_current_conv: bool, archived_panel_shown: bool) -> bool:
    """An archived chat announces only while it is the conversation in view or
    the archived list itself is on screen; from any other panel it is silent
    (neither the current-chat nor the foreground sound)."""
    return not is_current_conv and not archived_panel_shown


def archived_panel_is_shown(main_window) -> bool:
    panel = getattr(main_window, "archived_conversations_panel", None)
    if panel is None:
        return False
    try:
        return bool(panel.IsShown())
    except RuntimeError:  # wx object already destroyed
        return False
