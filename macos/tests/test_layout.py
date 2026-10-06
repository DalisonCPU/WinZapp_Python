"""The messages list keeps its height (layout_mac), checked on stubs: no wx
window is created. A zero-height list is dropped by VoiceOver, which is how
the whole messages table vanished after playing or recording a voice
message."""

import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [os.path.join(ROOT, "macos"), os.path.join(ROOT, "client")]

from winzapp_mac import layout_mac  # noqa: E402


class _Control:
    def __init__(self, char_height=16):
        self.char_height = char_height
        self.min_size = None

    def GetCharHeight(self):
        return self.char_height

    def SetMinSize(self, size):
        self.min_size = size


class _Window:
    """Records Layout() calls in a log shared by the inner and outer panel."""

    def __init__(self, name, log):
        self.name = name
        self.log = log
        self.on_layout = None

    def Layout(self):
        self.log.append(self.name)
        if self.on_layout:
            self.on_layout()
        return True


def _panel():
    log = []
    panel = _Window("outer", log)
    panel.conversation_panel = _Window("inner", log)
    panel._message_list_controls = {"classic": _Control(), "listbox": _Control(20)}
    return panel, log


def test_minimum_height_is_four_rows_of_text():
    assert layout_mac.MIN_MESSAGE_ROWS == 4
    assert layout_mac.min_messages_height(16) == 4 * (16 + 4) + 4
    assert layout_mac.min_messages_height(20, rows=2) == 2 * (20 + 4) + 4


def test_both_messages_list_controls_get_the_minimum():
    panel, _log = _panel()
    layout_mac.keep_messages_list_tall(panel)
    assert panel._message_list_controls["classic"].min_size == (-1, 84)
    assert panel._message_list_controls["listbox"].min_size == (-1, 100)


def test_panel_without_message_lists_is_left_alone():
    layout_mac.keep_messages_list_tall(types.SimpleNamespace())


def test_inner_layout_also_lays_out_the_outer_panel():
    panel, log = _panel()
    layout_mac.chain_layout_to_outer(panel)
    assert panel.conversation_panel.Layout() is True     # wx's return value kept
    assert log == ["inner", "outer"]


def test_outer_layout_reaching_the_inner_one_does_not_recurse():
    panel, log = _panel()
    layout_mac.chain_layout_to_outer(panel)
    panel.on_layout = panel.conversation_panel.Layout
    panel.conversation_panel.Layout()
    assert log == ["inner", "outer", "inner"]
    log.clear()
    panel.conversation_panel.Layout()                     # the guard is released
    assert log == ["inner", "outer", "inner"]


def test_a_failing_outer_layout_does_not_break_the_inner_one():
    panel, log = _panel()
    layout_mac.chain_layout_to_outer(panel)

    def boom():
        raise RuntimeError("wrapped C/C++ object has been deleted")

    panel.on_layout = boom
    assert panel.conversation_panel.Layout() is True
    panel.on_layout = None
    panel.conversation_panel.Layout()
    assert log == ["inner", "outer", "inner", "outer"]


def test_install_applies_both_after_winzapps_init_ui(monkeypatch):
    panel, log = _panel()

    class ConversationsPanel:
        def init_UI(self):
            log.append("init_UI")
            return "built"

    conversations = types.SimpleNamespace(ConversationsPanel=ConversationsPanel)
    monkeypatch.setitem(sys.modules, "ui", types.SimpleNamespace(conversations=conversations))
    monkeypatch.setitem(sys.modules, "ui.conversations", conversations)
    layout_mac.install()

    assert ConversationsPanel.init_UI(panel) == "built"
    assert panel._message_list_controls["classic"].min_size == (-1, 84)
    panel.conversation_panel.Layout()
    assert log == ["init_UI", "inner", "outer"]
