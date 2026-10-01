---
paths:
  - "client/core/accessible_speech.py"
  - "client/core/focus_cloak.py"
  - "client/ui/conversations.py"
  - "client/status_panel.py"
  - "client/status_tab/*.py"
  - "client/ui/conversation_panel/*.py"
  - "client/main_window/shortcuts.py"
  - "client/main_window/chat_list.py"
  - "client/main_window/chat_lock.py"
  - "client/ui/navigation.py"
---

# Screen reader speech

**Read `docs/traps/screen-reader-speech.md` before changing these files.** Short form:

Suppressing a focus announcement is done by the focus cloak (MSAA state without FOCUSED, disarmed after ~500 ms), never by cancelling speech. A list row must not be rewritten while focus is moving off it — hold repaints and release them when the sequence ends.

Switching to a chat panel (Alt+1, Alt+4, locked, navigation list) goes through `show_chat_panel()` only: the open conversation is shown only in its own panel, focus lands on the panel's chat list (never a message list), and hiding/showing never rebuilds or requests anything.
