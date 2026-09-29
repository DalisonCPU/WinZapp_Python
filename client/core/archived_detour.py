"""Remember the main-list conversation while the user visits an archived one.

ConversationsPanel is shared: opening an archived chat replaces whatever main
conversation was open. Coming back to the main panel must show that main
conversation again, not the archived one the user never closed.
"""


class ArchivedDetour:
    def __init__(self):
        self.active = False
        self.resume_jid = None

    def enter(self, current_jid):
        """Start a detour, remembering the open main conversation (or none).

        A second archived chat opened during the same detour must not
        overwrite it: the archived chat that is open then is not a main one.
        """
        if not self.active:
            self.active = True
            self.resume_jid = current_jid or None

    def leave(self):
        """End the detour; return the jid to reopen, or None."""
        jid = self.resume_jid
        self.active = False
        self.resume_jid = None
        return jid

    clear = leave
