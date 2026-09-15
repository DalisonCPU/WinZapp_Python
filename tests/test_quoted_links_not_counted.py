"""A reply's rendered row ends with the quoted message's preview, so a link
inside the message being answered was picked up as a link of the reply: it
became a Tab stop of its own, and together with one link of the reply's own
it crossed the two-or-more threshold and built the links list (issue #65's
control) out of a pair that never belonged to the same message.

_message_own_links() renders the row with the quoted clause suppressed, so
only what the message itself carries counts. The quoted message's own row is
where its link is reachable.

ConversationsPanel is a wx.Panel and cannot be instantiated without a running
wx.App, so the real _render_message_line()/_extract_links()/_message_own_links()
are bound onto a stub carrying only what they touch — same approach as
tests/test_forwarded_prefix_setting.py.
"""

from ui.conversations import ConversationsPanel


class _FakeI18n:
    _STRINGS = {
        "quoted_message_label": "mensagem citada",
        "replying_to": "respondendo a {name}",
        "status_edited": "Editada",
        "status_forwarded": "Encaminhada",
    }

    def t(self, key):
        return self._STRINGS.get(key, f"[{key}]")


class _Stub:
    _render_message_line = ConversationsPanel._render_message_line
    _message_own_links = ConversationsPanel._message_own_links
    _extract_links = staticmethod(ConversationsPanel._extract_links)
    _is_message_forwarded = ConversationsPanel._is_message_forwarded
    _is_system_event = staticmethod(ConversationsPanel._is_system_event)

    def __init__(self, body, quoted_preview=""):
        self.main_window = type("MW", (), {
            "settings": {"user_interface": {}},
            "i18n": _FakeI18n(),
        })()
        self._message_list_mode = "classic"
        self._body = body
        self._quoted_preview = quoted_preview

    def _is_separator(self, msg):
        return False

    def _extract_timestamp(self, msg):
        return 0

    def _format_date(self, ts):
        return ""

    def _get_message_content(self, msg):
        return self._body

    def _sender_label(self, msg):
        return "Fulano"

    def _map_status(self, msg):
        return ""

    def _get_context_info(self, msg):
        return msg.get("contextInfo") or None

    def _get_quoted_sender(self, ctx, msg):
        return "Beltrano" if ctx else ""

    def _get_quoted_preview(self, quoted_msg_obj):
        return self._quoted_preview

    def _reaction_counts(self, msg_id):
        return {}


def _reply(**overrides):
    msg = {
        "key": {"id": "MSG1"},
        "messageType": "extendedTextMessage",
        "message": {"extendedTextMessage": {"text": "corpo"}},
        "contextInfo": {"quotedMessage": {"conversation": "citada"}},
    }
    msg.update(overrides)
    return msg


class TestQuotedLinksDoNotCount:
    def test_a_link_only_in_the_quote_gives_the_reply_no_links(self):
        stub = _Stub("sem link aqui", quoted_preview="veja https://citada.com")
        assert stub._message_own_links(_reply()) == []

    def test_the_reply_keeps_its_own_single_link(self):
        stub = _Stub("olha https://minha.com", quoted_preview="veja https://citada.com")
        assert stub._message_own_links(_reply()) == ["https://minha.com"]

    def test_one_own_link_plus_one_quoted_stays_below_the_list_threshold(self):
        """The reported symptom: two links, so the panel built the list control."""
        stub = _Stub("olha https://minha.com", quoted_preview="veja https://citada.com")
        assert len(stub._message_own_links(_reply())) == 1

    def test_the_reply_still_reports_several_links_of_its_own(self):
        stub = _Stub(
            "https://a.com e https://b.com",
            quoted_preview="veja https://citada.com",
        )
        assert stub._message_own_links(_reply()) == ["https://a.com", "https://b.com"]

    def test_a_message_that_is_not_a_reply_is_unaffected(self):
        stub = _Stub("olha https://minha.com")
        assert stub._message_own_links(_reply(contextInfo={})) == ["https://minha.com"]


class TestTheRowItselfStillShowsTheQuote:
    def test_the_rendered_row_keeps_the_quoted_preview(self):
        stub = _Stub("corpo", quoted_preview="veja https://citada.com")
        line = stub._render_message_line(_reply())
        assert "mensagem citada: veja https://citada.com" in line

    def test_only_the_link_pass_suppresses_it(self):
        stub = _Stub("corpo", quoted_preview="veja https://citada.com")
        line = stub._render_message_line(_reply(), include_quoted_preview=False)
        assert "mensagem citada" not in line
        assert line.startswith("Fulano, respondendo a Beltrano: corpo")
