"""The open conversation's message list is never cleared and rewritten.

A native ListView row is one MSAA object: DeleteAllItems() plus re-Append()ing
every row hands NVDA a new list and re-announces the focused message although
nothing about it changed (the 60 s poll did this whenever a live message and a
reaction arrived together, or after the user's own send). Every write now goes
through MessageRowsMixin._sync_message_rows(), which deletes/inserts only the
rows that differ and rewrites a row's text only when it differs.

ConversationsPanel is a wx.Panel and cannot be built without a wx.App, so the
mixin method is bound onto a plain stub carrying a recording fake list.
"""

import random
from pathlib import Path

from core.list_row_diff import plan_row_diff
from ui.conversations import ConversationsPanel

ROOT = Path(__file__).resolve().parents[1]


def _apply(old, new):
    """Run plan_row_diff() against a plain list, the way the control is driven."""
    deletes, inserts = plan_row_diff(old, new)
    work = list(old)
    for i in deletes:
        del work[i]
    for j in inserts:
        work.insert(j, new[j])
    return work, deletes, inserts


class TestPlanRowDiff:
    def test_identical_lists_need_nothing(self):
        assert plan_row_diff(list("abcde"), list("abcde")) == ([], [])

    def test_a_row_appended_at_the_tail_is_one_insert(self):
        work, deletes, inserts = _apply(list("abc"), list("abcd"))
        assert work == list("abcd") and deletes == [] and inserts == [3]

    def test_a_row_removed_from_the_middle_is_one_delete(self):
        work, deletes, inserts = _apply(list("abcde"), list("abde"))
        assert work == list("abde") and deletes == [2] and inserts == []

    def test_older_rows_prepended_are_inserts_only(self):
        work, deletes, inserts = _apply(list("cde"), list("abcde"))
        assert work == list("abcde") and deletes == [] and inserts == [0, 1]

    def test_a_replaced_row_is_a_delete_and_an_insert_not_a_rewrite(self):
        work, deletes, inserts = _apply(list("abc"), ["a", "X", "c"])
        assert work == ["a", "X", "c"] and deletes == [1] and inserts == [1]

    def test_from_and_to_empty(self):
        assert _apply([], list("ab"))[0] == list("ab")
        assert _apply(list("ab"), [])[0] == []

    def test_the_surviving_rows_are_never_touched(self):
        """Only the rows that differ are in the plan: the others (the focused
        one among them) appear in neither list."""
        old, new = list("abcdefgh"), list("abcXefgh")
        deletes, inserts = plan_row_diff(old, new)
        assert deletes == [3] and inserts == [3]

    def test_fuzz_always_reaches_the_target(self):
        rng = random.Random(7)
        for _ in range(400):
            old = rng.sample(range(30), rng.randint(0, 20))
            new = rng.sample(range(30), rng.randint(0, 20))
            assert _apply(old, new)[0] == new


def _msg(mid, text=None):
    return {"key": {"id": mid}, "_text": text if text is not None else mid}


class _RecordingList:
    """Enough of the messages list to see exactly what was done to it."""

    def __init__(self, rows):
        self.rows = list(rows)
        self.log = []

    def GetItemCount(self):
        return len(self.rows)

    def GetItemText(self, index, col=0):
        return self.rows[index]

    def SetItemText(self, index, text):
        self.log.append(("set", index, text))
        self.rows[index] = text

    def InsertItem(self, index, text):
        self.log.append(("insert", index, text))
        self.rows.insert(index, text)

    def DeleteItem(self, index):
        self.log.append(("delete", index))
        del self.rows[index]

    def Append(self, entry):
        self.log.append(("append", entry[0]))
        self.rows.append(entry[0])

    def DeleteAllItems(self):
        self.log.append(("delete_all",))
        self.rows.clear()


class _Stub:
    _sync_message_rows = ConversationsPanel._sync_message_rows
    _message_row_key = ConversationsPanel._message_row_key

    def __init__(self, shown):
        self.messages_list = _RecordingList([m["_text"] for m in shown])

    def _render_message_line(self, msg, index=None, total=None):
        return msg["_text"]


class TestSyncMessageRows:
    def test_nothing_changed_touches_nothing(self):
        rows = [_msg("a"), _msg("b"), _msg("c")]
        stub = _Stub(rows)
        stub._sync_message_rows(rows, [dict(m) for m in rows])
        assert stub.messages_list.log == []

    def test_the_combo_that_used_to_rebuild_touches_only_the_decorated_row(self):
        """A live message already on screen plus a reaction record that changes
        another row's text: neither tail-append nor in-place repaint covered
        the mix, so the poll fell through to the full rebuild. Now only the
        decorated row's text is written; the focused row is not touched."""
        old = [_msg("a"), _msg("b"), _msg("c"), _msg("live")]
        new = [_msg("a"), _msg("b", "b reagido"), _msg("c"), _msg("live")]
        stub = _Stub(old)
        stub._sync_message_rows(old, new)
        assert stub.messages_list.log == [("set", 1, "b reagido")]

    def test_a_new_tail_message_is_one_insert(self):
        old = [_msg("a"), _msg("b")]
        new = old + [_msg("c")]
        stub = _Stub(old)
        stub._sync_message_rows(old, new)
        assert stub.messages_list.log == [("insert", 2, "c")]

    def test_a_message_removed_is_one_delete(self):
        old = [_msg("a"), _msg("b"), _msg("c")]
        new = [_msg("a"), _msg("c")]
        stub = _Stub(old)
        stub._sync_message_rows(old, new)
        assert stub.messages_list.log == [("delete", 1)]
        assert stub.messages_list.rows == ["a", "c"]

    def test_a_pending_send_replaced_by_its_echo(self):
        pending = {"key": {"id": ""}, "_text": "oi, pendente"}
        old = [_msg("a"), pending]
        new = [_msg("a"), _msg("real", "oi, enviada")]
        stub = _Stub(old)
        stub._sync_message_rows(old, new)
        assert stub.messages_list.rows == ["a", "oi, enviada"]
        assert ("delete_all",) not in stub.messages_list.log

    def test_the_unread_separator_keeps_its_identity_across_refreshes(self):
        sep = {"_type": "unread_separator", "count": 2, "_text": "2 nao lidas"}
        old = [_msg("a"), dict(sep), _msg("b")]
        new = [_msg("a"), {**sep, "count": 3, "_text": "3 nao lidas"}, _msg("b")]
        stub = _Stub(old)
        stub._sync_message_rows(old, new)
        assert stub.messages_list.log == [("set", 1, "3 nao lidas")]

    def test_a_list_out_of_step_with_its_backing_is_resynced_not_patched(self):
        old = [_msg("a"), _msg("b")]
        stub = _Stub(old)
        stub.messages_list.rows.append("stray")
        stub._sync_message_rows(old, [_msg("a")])
        assert stub.messages_list.rows == ["a"]

    def test_clearing_to_nothing_deletes_row_by_row(self):
        old = [_msg("a"), _msg("b")]
        stub = _Stub(old)
        stub._sync_message_rows(old, [])
        assert stub.messages_list.rows == []
        assert ("delete_all",) not in stub.messages_list.log


class TestNothingElseClearsTheList:
    def test_only_the_resync_fallback_calls_delete_all_on_the_message_list(self):
        """Structural guard: a new DeleteAllItems() on messages_list anywhere in
        the panel's modules brings the re-announcement bug back."""
        offenders = []
        files = [ROOT / "client" / "ui" / "conversations.py"]
        files += sorted((ROOT / "client" / "ui" / "conversation_panel").glob("*.py"))
        for path in files:
            if path.name == "message_rows.py":
                continue
            lines = path.read_text(encoding="utf-8").splitlines()
            for number, line in enumerate(lines, 1):
                if "messages_list.DeleteAllItems" in line:
                    offenders.append(f"{path.name}:{number}")
        assert offenders == []


class TestARealListControlKeepsTheFocusedRow:
    """The fake lists above prove what is called; this proves what the native
    control then does with it. Uses a hidden frame (tests/conftest.py), so no
    window is ever visible to the desktop."""

    def _list(self, frame, texts):
        import wx
        lst = wx.ListCtrl(frame, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        lst.InsertColumn(0, "m", width=200)
        for text in texts:
            lst.Append((text,))
        return lst

    def test_focus_and_selection_follow_the_row_through_inserts_and_deletes(self, wx_app):
        import wx
        from tests.conftest import hidden_frame

        frame = hidden_frame()
        try:
            old = [_msg(f"r{i}") for i in range(6)]
            lst = self._list(frame, [m["_text"] for m in old])
            lst.Focus(3)
            lst.Select(3)
            focus_events = []
            lst.Bind(wx.EVT_LIST_ITEM_FOCUSED, lambda e: focus_events.append(e.GetIndex()))

            # r0 disappears, r1 gets a reaction, a new message lands at the tail.
            new = [_msg("r1", "r1 reagido"), _msg("r2"), _msg("r3"), _msg("r4"),
                   _msg("r5"), _msg("r6")]
            stub = _Stub(old)
            stub.messages_list = lst
            stub._sync_message_rows(old, new)

            assert [lst.GetItemText(i) for i in range(lst.GetItemCount())] == [
                "r1 reagido", "r2", "r3", "r4", "r5", "r6"]
            assert lst.GetFocusedItem() == 2          # still on r3
            assert lst.GetItemText(lst.GetFocusedItem()) == "r3"
            assert lst.GetFirstSelected() == 2
            assert focus_events == []                 # nothing re-announced
        finally:
            frame.Destroy()
