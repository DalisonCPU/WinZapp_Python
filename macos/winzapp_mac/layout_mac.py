"""Keep the messages list on screen when the conversation shows more controls.

The messages list is the only stretchable item in the conversation panel's
sizer. Playing or recording a voice message, quoting a message, the message
action buttons and the composer all show extra controls and then call only
``self.conversation_panel.Layout()``: the inner panel keeps its size, so the
list gives up every pixel those controls take. A read-only AX walk of the
running app found it at 90 px while audio played (Chats list: 310 px), and
it reaches 0 px. VoiceOver drops a zero-height scroll area from the window,
so the whole messages table vanishes after replying with or playing a voice
message.

Two changes, no control touched beyond its size:

* the messages list keeps a minimum height of a few rows, so the inner
  panel's minimum grows with every control shown beside it;
* the conversation panel's ``Layout()`` also lays out ConversationsPanel,
  whose sizer then gives the conversation panel that larger minimum and
  takes the space from the Chats list instead.

The second is an instance attribute on ``conversation_panel``: only
WinZapp's Python calls see it. wx's own size handling lays the inner panel
out in C++, so laying out the outer panel (which resizes the inner one)
cannot come back here; a guard covers any other path anyway.
"""

import logging

MIN_MESSAGE_ROWS = 4

# An NSTableView row is the text height plus its intercell spacing; the
# scroll view adds a border. Slightly generous rather than a row short.
_ROW_PADDING = 4
_BORDER = 4


def min_messages_height(char_height, rows=MIN_MESSAGE_ROWS):
    """Minimum height in px of a messages list showing *rows* rows."""
    return rows * (int(char_height) + _ROW_PADDING) + _BORDER


def keep_messages_list_tall(panel):
    """Give every messages-list control (classic and listbox, only one of
    them shown) a minimum height of MIN_MESSAGE_ROWS rows."""
    for control in getattr(panel, "_message_list_controls", {}).values():
        control.SetMinSize((-1, min_messages_height(control.GetCharHeight())))


def chain_layout_to_outer(panel):
    """Make ``panel.conversation_panel.Layout()`` re-lay out *panel* too."""
    inner = panel.conversation_panel
    inner_layout = inner.Layout     # wx's own bound method
    busy = []

    def layout():
        result = inner_layout()
        if not busy:
            busy.append(True)
            try:
                panel.Layout()
            except Exception:
                logging.debug("[layout_mac] outer layout failed", exc_info=True)
            finally:
                busy.clear()
        return result

    inner.Layout = layout


def install():
    from ui import conversations
    cls = conversations.ConversationsPanel
    orig_init_ui = cls.init_UI

    def init_ui(self, *a, **k):
        result = orig_init_ui(self, *a, **k)
        keep_messages_list_tall(self)
        chain_layout_to_outer(self)
        return result

    cls.init_UI = init_ui
