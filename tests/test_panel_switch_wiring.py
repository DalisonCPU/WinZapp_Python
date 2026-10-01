"""Switching to a chat panel, through the real methods of every entry point.

#339 made an open conversation visible only in the panel it was opened from,
but tested it against stubs that re-implemented the callers. Here Alt+1, Alt+4,
the locked-chats panel, the navigation list and Alt+2/3/M run the real
MainWindow / NavigationPanel / ConversationsPanel methods against widgets that
only record Show/Hide/SetFocus, so the call order is the shipped one.

The rules pinned, for origin {main, archived, locked, none} x target panel:
  * the open conversation's detail pane is shown only in its own panel;
  * keyboard focus goes to that panel's chat list, never to a message list
    or the composer (the regression in #339: Alt+4 with an archived
    conversation open landed in its messages);
  * hiding and showing never rebuilds the message list or asks the network
    for anything; only a conversation displaced by another one is reopened,
    right after the switch, without the requests its first open made.

No window is created.
"""

import itertools
from unittest.mock import MagicMock

import pytest

from core.conversation_view import ARCHIVED, LOCKED, MAIN, panel_layout
from main import MainWindow
from ui.conversation_panel import conversation_navigation as nav_module
from ui.conversation_panel.conversation_navigation import ConversationNavigationMixin
from ui.conversation_panel.panel_visibility import ConversationPanelVisibilityMixin
from ui.navigation import NavigationPanel

A = "a@s.whatsapp.net"
B = "b@s.whatsapp.net"
G = "g@g.us"


class _Widget:
    def __init__(self, name, log, shown=False):
        self.name, self.log, self.shown = name, log, shown

    def Show(self, show=True):
        self.shown = bool(show)
        self.log.append((self.name, "Show", bool(show)))

    def Hide(self):
        self.shown = False
        self.log.append((self.name, "Hide"))

    def IsShown(self):
        return self.shown

    def Layout(self):
        pass

    def SetFocus(self):
        self.log.append((self.name, "SetFocus"))

    def Focus(self, idx):
        pass

    def Select(self, idx, on=True):
        pass

    def EnsureVisible(self, idx):
        pass

    def GetItemCount(self):
        return 3

    def GetFocusedItem(self):
        return 0

    def GetItemText(self, idx):
        return "row"


class _ListPanel(_Widget):
    """Archived / locked list panel: restore_selection() focuses its list."""

    def restore_selection(self):
        self.log.append((self.name, "SetFocus"))


class _Note:
    note = "last seen"

    def GetNote(self):
        return self.note

    def SetNote(self, text):
        self.note = text

    def SetLabel(self, text):
        pass


class _MW:
    """MainWindow stand-in: the real entry-point methods, recording widgets."""

    on_alt_1 = MainWindow.on_alt_1
    on_alt_4 = MainWindow.on_alt_4
    show_locked_chats_panel = MainWindow.show_locked_chats_panel
    _ensure_conversations_panel_visible = MainWindow._ensure_conversations_panel_visible
    _on_global_alt2 = MainWindow._on_global_alt2

    def __init__(self, log):
        self.log = log
        self.requests = []          # every network-facing call, by name
        self.chats = {A: {"remoteJid": A}, B: {"remoteJid": B},
                      G: {"remoteJid": G}}
        self.locked = set()
        self.settings = {}
        self._chat_lock_vault = None
        self._chat_lock_unlocked = True
        self._locked_chat_rows = ([], [])
        self.content_panel = _Widget("content_panel", log, True)
        self.archived_conversations_panel = _ListPanel("archived_list_panel", log)
        self.locked_conversations_panel = _ListPanel("locked_list_panel", log)
        self.locked_conversations_panel.set_all_chats = lambda c, n: None
        self.status_panel = _Widget("status_panel", log)
        self.calls_panel = _Widget("calls_panel", log)
        self.db = MagicMock()
        self.db.get_messages.return_value = []
        self.db.get_message_count.return_value = 0
        self.i18n = MagicMock()
        self.conversations_panel = _Panel(self, log)

    def lock_chat_vault(self, **kwargs):
        pass

    def touch_chat_lock_timeout(self):
        pass

    def is_chat_locked(self, jid):
        return jid in self.locked

    def chat_display_name(self, chat):
        return "name"

    def _is_group_send_restricted(self, chat):
        return False

    def _note_conversation_opened(self, jid):
        self.requests.append("note_opened")

    def subscribe_presence(self, jid):
        self.requests.append("subscribe_presence")

    def get_group_info_recent(self, jid):
        self.requests.append("group_info")
        return {}

    def mark_conversation_as_read(self, jid):
        self.requests.append("mark_read")

    def __getattr__(self, name):
        value = MagicMock()
        setattr(self, name, value)
        return value


class _Panel(ConversationPanelVisibilityMixin):
    """ConversationsPanel: real visibility + navigation methods, widgets that
    record. populate_messages and the reaction backfill are counted."""

    _restore_conversation_selection = ConversationNavigationMixin._restore_conversation_selection
    navigate_to_conversation = ConversationNavigationMixin.navigate_to_conversation
    _open_focus_target = ConversationNavigationMixin._open_focus_target
    _conversation_note_text = ConversationNavigationMixin._conversation_note_text
    _message_label_text = ConversationNavigationMixin._message_label_text
    _apply_composer_permissions = lambda self, jid, conv: None
    _fetch_and_update_profile = lambda self, conv: None
    _fetch_group_participants = lambda self, jid: None

    def __init__(self, mw, log):
        self.main_window = mw
        self.log = log
        self.conversation = None
        self._conversation_origin = None
        self._shown_panel = None
        self._parked_by_origin = {}
        self._group_participants_cache = []
        self._last_list_focus_jid = ""
        self._last_open_jid = ""
        self._last_msg = 4
        self.chats_list = [{"remoteJid": A}]
        self._sorted_messages = []
        self._outgoing_virtual_messages = {}
        self._msg_temp_bookmarks = set()
        self.selected_messages = set()
        self._current_audio_id = None
        self._audio_stream = None
        self._pending_mentions = []
        self._pending_mention_display_names = {}
        self.search_field = MagicMock()
        self.search_field.GetValue.return_value = ""
        self.counts = {"populate": 0, "backfill": 0}
        self.threads = []
        self.panel_shown = True
        self.conversation_panel = _Widget("detail", log)
        self.conversations_label = _Widget("own_label", log, True)
        self.conversations_list = _Widget("own_list", log, True)
        self.messages_list = _Widget("messages_list", log, True)
        self.message_field = _Widget("message_field", log, True)
        self.message_field.IsEnabled = lambda: True
        self.message_field.IsEditable = lambda: True
        self._conv_data_btn = _Note()

    # ConversationsPanel is a wx.Panel; its own Show/Layout record too.
    def Show(self, show=True):
        self.panel_shown = bool(show)
        self.log.append(("panel", "Show", bool(show)))

    def Hide(self):
        self.Show(False)

    def IsShown(self):
        return self.panel_shown

    def Layout(self):
        pass

    def populate_messages(self, preserve_focus=False):
        self.counts["populate"] += 1

    def _backfill_reactions_for_open_conversation(self):
        self.counts["backfill"] += 1

    def _focused_msg_id(self):
        return "msg-%d" % self._last_msg

    def _is_separator(self, msg):
        return False

    def _sync_pending_document_gauge(self):
        pass

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        value = MagicMock()
        setattr(self, name, value)
        return value


@pytest.fixture
def world(monkeypatch):
    log = []
    queued = []
    started = []

    class _Thread:
        def __init__(self, target=None, args=(), daemon=None):
            self.target = target

        def start(self):
            started.append(getattr(self.target, "__name__", str(self.target)))

    monkeypatch.setattr(nav_module.threading, "Thread", _Thread)
    import ui.conversation_panel.panel_visibility as pv
    monkeypatch.setattr(pv.wx, "CallAfter", lambda fn, *a: queued.append((fn, a)))
    monkeypatch.setattr(nav_module.wx, "CallAfter", lambda fn, *a: queued.append((fn, a)))
    mw = _MW(log)
    mw.started, mw.queued = started, queued
    return mw


def _open(mw, jid, origin, *, hidden=True):
    """Open a chat the way its panel's list does, then settle."""
    panel = mw.conversations_panel
    if origin in (ARCHIVED, LOCKED):
        panel.conversations_list.Hide()
        panel.conversations_label.Hide()
    panel.navigate_to_conversation(mw.chats[jid], origin=origin)
    mw.queued.clear()


def _flush(mw):
    """Run what the switch deferred (the reopen), like the event loop."""
    while mw.queued:
        fn, args = mw.queued.pop(0)
        fn(*args)


def _enter(mw, target):
    """Every real way of making `target` the visible chat panel."""
    nav = type("_Nav", (), {"main_window": mw, "_nav_keys": [
        "conversations", "archived", "locked", "status", "calls", "settings"]})()
    nav.on_nav_item_selected = lambda e: NavigationPanel.on_nav_item_selected(nav, e)
    idx = {MAIN: 0, ARCHIVED: 1, LOCKED: 2}[target]
    event = type("_E", (), {"GetIndex": lambda self: idx})()
    return {
        MAIN: [("alt1", lambda: mw.on_alt_1(None)), ("nav", lambda: nav.on_nav_item_selected(event))],
        ARCHIVED: [("alt4", lambda: mw.on_alt_4(None)), ("nav", lambda: nav.on_nav_item_selected(event))],
        LOCKED: [("locked", lambda: mw.show_locked_chats_panel())],
    }[target]


def _focus_calls(mw):
    return [e[0] for e in mw.log if e[1] == "SetFocus"]


CHAT_LIST_FOCUS = {MAIN: "own_list", ARCHIVED: "archived_list_panel",
                   LOCKED: "locked_list_panel"}
ORIGINS = [MAIN, ARCHIVED, LOCKED, None]
TARGETS = [MAIN, ARCHIVED, LOCKED]


class TestPanelLayoutRule:
    @pytest.mark.parametrize("origin,target", list(itertools.product(ORIGINS, TARGETS)))
    def test_detail_only_in_own_panel(self, origin, target):
        layout = panel_layout(origin, target, True)
        assert layout["detail"] == (origin == target)
        assert layout["panel"] == (target == MAIN or origin == target)
        assert layout["list_panel"] == (target != MAIN)
        assert not panel_layout(origin, target, False)["detail"]
        # the main list is hidden only when a conversation sits under another list
        assert layout["own_list"] == (target == MAIN or origin != target)


ENTRIES = [(MAIN, "alt1"), (MAIN, "nav"), (ARCHIVED, "alt4"),
           (ARCHIVED, "nav"), (LOCKED, "locked")]


class TestEveryEntryPointByOriginAndTarget:
    @pytest.mark.parametrize("origin", ORIGINS)
    @pytest.mark.parametrize("target,label", ENTRIES)
    def test_with_an_open_conversation(self, world, origin, target, label):
        panel = world.conversations_panel
        _open(world, A, origin or MAIN)
        panel._conversation_origin = origin   # None: opened some other way
        world.log.clear()

        dict(_enter(world, target))[label]()
        _flush(world)

        visible = origin == target
        assert panel.conversation_panel.shown == visible, (label, origin, target)
        assert panel.conversation is not None  # hidden, never closed
        if target == MAIN:
            assert panel.panel_shown and panel.conversations_list.shown
            assert not world.archived_conversations_panel.shown
        elif visible:
            assert panel.panel_shown and not panel.conversations_list.shown
        else:
            assert not panel.panel_shown, "another panel's conversation stayed on screen"
        list_panel = {ARCHIVED: world.archived_conversations_panel,
                      LOCKED: world.locked_conversations_panel}.get(target)
        if list_panel is not None:
            assert list_panel.shown
        focused = _focus_calls(world)
        assert focused and focused[-1] == CHAT_LIST_FOCUS[target]
        assert "messages_list" not in focused and "message_field" not in focused

    @pytest.mark.parametrize("target,label", ENTRIES)
    def test_without_a_conversation(self, world, target, label):
        world.status_panel.shown = True
        world.log.clear()

        dict(_enter(world, target))[label]()

        panel = world.conversations_panel
        assert not panel.conversation_panel.shown
        assert panel.panel_shown == (target == MAIN)
        assert not world.status_panel.shown
        assert _focus_calls(world)[-1] == CHAT_LIST_FOCUS[target]
        assert not world.queued

    def test_alt_2_brings_the_conversation_forward_in_its_own_panel_without_moving_focus(self, world):
        for origin in (MAIN, ARCHIVED, LOCKED):
            fresh = _MW([])
            fresh.started, fresh.queued = world.started, world.queued
            _open(fresh, A, origin)
            fresh.status_panel.shown = True
            fresh.conversations_panel.Hide()
            fresh.conversations_panel.conversation_panel.Hide()
            fresh.conversations_panel._on_accel_jump_last = lambda e: None
            fresh._on_global_alt2(None)
            panel = fresh.conversations_panel
            assert panel.panel_shown and panel.conversation_panel.shown
            assert not fresh.status_panel.shown
            assert _focus_calls(fresh) == []  # the caller moves focus to the messages

    def test_alt_4_with_an_archived_conversation_focuses_the_archived_list(self, world):
        _open(world, A, ARCHIVED)
        world.log.clear()
        world.on_alt_4(None)
        panel = world.conversations_panel
        assert world.archived_conversations_panel.shown
        assert panel.conversation_panel.shown  # shown again, beneath the list
        assert _focus_calls(world) == ["archived_list_panel"]

    def test_alt_4_with_a_main_conversation_hides_it(self, world):
        _open(world, A, MAIN)
        world.on_alt_4(None)
        panel = world.conversations_panel
        assert not panel.panel_shown and not panel.conversation_panel.shown
        assert world.archived_conversations_panel.shown

    def test_alt_1_with_an_archived_conversation_hides_it(self, world):
        _open(world, A, ARCHIVED)
        world.on_alt_1(None)
        panel = world.conversations_panel
        assert panel.panel_shown and panel.conversations_list.shown
        assert not panel.conversation_panel.shown
        assert _focus_calls(world)[-1] == "own_list"


class TestHideShowNeverRebuilds:
    def test_a_hide_show_cycle_costs_no_rebuild_and_no_request(self, world):
        _open(world, A, MAIN)
        panel = world.conversations_panel
        before = (dict(panel.counts), list(world.requests), list(world.started),
                  world.db.get_messages.call_count)
        for _ in range(3):
            world.on_alt_4(None)
            world.on_alt_1(None)
            world.show_locked_chats_panel()
            world.on_alt_1(None)
        _flush(world)
        assert (dict(panel.counts), list(world.requests), list(world.started),
                world.db.get_messages.call_count) == before
        assert panel.conversation_panel.shown  # back in its own panel

    def test_message_list_state_is_untouched_by_a_cycle(self, world):
        _open(world, A, ARCHIVED)
        panel = world.conversations_panel
        world.log.clear()
        world.on_alt_1(None)
        world.on_alt_4(None)
        assert not any(e[0] == "messages_list" for e in world.log)


class TestReopeningADisplacedConversation:
    def _displace(self, world):
        """Main conversation A is displaced by archived B in the shared widget."""
        _open(world, A, MAIN)
        world.on_alt_4(None)
        world.archived_conversations_panel.Hide()
        world.conversations_panel.Show()
        _open(world, B, ARCHIVED)

    def test_open_costs_one_populate_and_each_request_once(self, world):
        _open(world, G, MAIN)
        panel = world.conversations_panel
        assert panel.counts == {"populate": 1, "backfill": 1}
        assert world.requests == ["note_opened", "subscribe_presence"]
        assert sorted(world.started) == ["<lambda>", "<lambda>"]  # profile + participants
        assert world.db.get_messages.call_count == 1

    def test_switch_returns_at_once_and_reopens_without_refetching(self, world):
        self._displace(world)
        panel = world.conversations_panel
        panel.counts.update(populate=0, backfill=0)
        world.requests.clear()
        world.started.clear()
        world.db.get_messages.reset_mock()
        world.on_alt_1(None)
        # nothing rebuilt yet: the list is on screen and focused first
        assert panel.counts["populate"] == 0 and world.queued
        assert _focus_calls(world)[-1] == "own_list"
        _flush(world)
        assert panel.conversation["remoteJid"] == A
        assert panel.counts == {"populate": 1, "backfill": 0}
        assert world.requests == []          # no presence, group-info, reactions
        assert world.started == []           # no profile / participants threads
        assert world.db.get_messages.call_count == 1
        assert panel.conversation_panel.shown and panel.panel_shown
        assert _focus_calls(world)[-1] == "own_list"  # reopen never took focus

    def test_a_reopen_restores_what_the_first_open_fetched(self, world):
        _open(world, G, MAIN)
        panel = world.conversations_panel
        panel._group_participants_cache = [("Ann", "ann@s.whatsapp.net")]
        panel._conv_data_btn.note = "Group, 5 participants"
        world.on_alt_4(None)
        world.archived_conversations_panel.Hide()
        world.conversations_panel.Show()
        _open(world, B, ARCHIVED)
        panel._conv_data_btn.note = "other"
        world.on_alt_1(None)
        _flush(world)
        assert panel._group_participants_cache == [("Ann", "ann@s.whatsapp.net")]
        assert panel._conv_data_btn.note == "Group, 5 participants"

    def test_a_deferred_reopen_is_dropped_when_the_user_moved_on(self, world):
        self._displace(world)
        panel = world.conversations_panel
        panel.counts["populate"] = 0
        world.on_alt_1(None)
        world.status_panel.Show()
        panel.Hide()                     # went to Status before the reopen ran
        _flush(world)
        assert panel.counts["populate"] == 0
        assert not panel.panel_shown

    def test_the_displaced_conversations_return_in_their_own_panels(self, world):
        self._displace(world)
        world.on_alt_1(None)
        _flush(world)
        assert world.conversations_panel.conversation["remoteJid"] == A
        world.on_alt_4(None)
        _flush(world)
        assert world.conversations_panel.conversation["remoteJid"] == B
        assert world.conversations_panel.conversation_panel.shown
        assert _focus_calls(world)[-1] == "archived_list_panel"

    def test_the_displaced_conversation_is_parked_with_its_row_and_comes_back_unread_and_unfocused(self, world):
        self._displace(world)
        parked = world.conversations_panel._parked_conversations()[MAIN]
        assert (parked["jid"], parked["msg_id"]) == (A, "msg-4")
        world.requests.clear()
        world.log.clear()
        world.on_alt_1(None)
        _flush(world)
        assert "mark_read" not in world.requests and not world.queued
        assert "messages_list" not in _focus_calls(world)
        assert "message_field" not in _focus_calls(world)

    def test_a_parked_chat_locked_in_the_meantime_is_not_reopened(self, world):
        self._displace(world)
        world.locked.add(A)
        world.on_alt_1(None)
        _flush(world)
        assert world.conversations_panel.conversation["remoteJid"] == B
        assert not world.conversations_panel.conversation_panel.shown

    def test_opening_the_same_chat_from_another_panel_changes_its_owner(self, world):
        _open(world, A, MAIN)
        world.on_alt_4(None)
        _open(world, A, ARCHIVED)
        panel = world.conversations_panel
        assert panel._conversation_origin == ARCHIVED
        assert panel._parked_conversations() == {}
