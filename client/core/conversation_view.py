"""Whether the open conversation is the one being shown.

ConversationsPanel keeps its conversation open while the user is on another
panel (Alt+4 archived, ...): coming back must not mean finding the chat
again. But an open conversation that is hidden is not being read, so it must
not be marked read, notified as "the current chat" or kept out of the unread
counts.
"""

MAIN, ARCHIVED, LOCKED = "main", "archived", "locked"


def conversation_in_view(panel) -> bool:
    """True when `panel` has a conversation open and it is on screen.

    IsShown() of the panel, not IsShownOnScreen(): the panel is a direct child
    of the content area and the panel switches Hide() it, while a window
    hidden to the tray or minimized must keep counting as "open" (the unread
    bookkeeping for a hidden window relies on that). The detail pane counts
    too: a conversation is shown only while the panel it was opened from is
    the visible one (see conversation_visible_in()), and the others hide just
    that pane, leaving the panel itself shown. A stand-in without either
    method counts as shown, so callers keep their old behaviour.
    """
    if panel is None or getattr(panel, "conversation", None) is None:
        return False
    for widget in (panel, getattr(panel, "conversation_panel", None)):
        shown = getattr(widget, "IsShown", None)
        if shown is None:
            continue
        try:
            if not shown():
                return False
        except RuntimeError:  # wx object already destroyed
            return False
    return True


def conversation_visible_in(origin, shown_panel) -> bool:
    """The one rule: an open conversation is on screen only while the panel it
    was opened from (main, archived or locked) is the panel being shown."""
    return origin is not None and origin == shown_panel


def resolve_origin(requested, current_origin, list_shown, detail_shown) -> str:
    """The panel a conversation being opened belongs to.

    An explicit request wins. Otherwise a chat opened from inside a
    conversation that sits alone in the panel (the chat list hidden, as it is
    for an archived or locked one: a bookmark, a mention) stays with that
    panel; anything else is the main panel's, an archived chat found through
    the main search box included.
    """
    if requested:
        return requested
    if current_origin in (ARCHIVED, LOCKED) and detail_shown and not list_shown:
        return current_origin
    return MAIN


def parked_chat_reopenable(origin, chat_locked, vault_unlocked) -> bool:
    """A conversation set aside while another took the shared panel comes back
    only if it may still be shown: a locked chat needs the vault open and any
    other must not have been locked since."""
    if origin == LOCKED:
        return bool(chat_locked and vault_unlocked)
    return not chat_locked


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
