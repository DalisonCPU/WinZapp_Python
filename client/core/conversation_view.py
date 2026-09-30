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
        return bool(shown())
    except RuntimeError:  # wx object already destroyed
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
