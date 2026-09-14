"""WhatsApp Web's edit protocol message: recognise it, never store it.

WPP.chat.editMessage() (wa-js) does not only change a message in place. It
also builds a second message — ``type: "protocol"``, ``subtype:
"message_edit"``, a **new id**, ``protocolMessageKey`` naming the original,
``body`` holding the new text — and WhatsApp Web keeps that model in the
chat's message collection, so ``WAPI.getMessages`` returns it alongside the
real messages.

``_normalize_wpp_message()`` had no branch for ``protocol``, so its generic
"unmapped type with body text → conversation" fallback turned it into an
ordinary text message under an id nothing had stored, and every id-based merge
appended it. Reproduced on a real install (2026-09-14): a reply edited at
01:33:26 came back through the live socket under its ORIGINAL id and was
handled correctly; the next periodic get-messages, 43 s later, brought in a
record never seen on the socket — ``conversation``, fromMe, stamped 12 s after
the reply, no quote, text identical to the edited reply. That is the "a few
seconds later a second, unquoted copy appears under it, only on my side".

Cleaning up copies stored before the fix is opportunistic, not a migration:
a stored copy is removed when the edit event behind it is seen again (a sync
or scroll-up that fetches it, or a live re-delivery). The set of seen event ids
lives in memory, so after a restart a chat must be fetched again first, and a
copy whose event has left every window WinZapp fetches stays. On disk it is an
ordinary own ``conversation`` with nothing marking it, so there is no safe way
to find it without the event.

Not proven: why only edits of replies were noticed. The mechanism above does
not depend on the message being a reply, so do not read this module as
confirming that it is limited to them.

**The event is dropped, never applied.** The same edit always reaches Python a
second way that carries the full, current original: wa-js emits
``chat.msg_edited`` on the original model's ``change:latestEditMsgKey`` and
WinZapp re-emits it under the original id (createSessionUtil.ts), which
``_apply_possible_edit()`` already handles — edits made on other devices
included. Applying the protocol event as well would only add ways to be wrong:
stale mentions copied from the stored record, an older edit replayed over a
newer text by a history batch, a deleted chat brought back by an edit of an old
message in it.
"""

from __future__ import annotations

import copy
import json
import time

from urllib3.exceptions import NewConnectionError

#: How the normaliser tags an edit inside message.protocolMessage.type.
MESSAGE_EDIT = "MESSAGE_EDIT"

#: How long after sending WhatsApp still OFFERS to edit a message.
#:
#: Measured, not remembered — read out of the running WhatsApp Web
#: (2026-09-14) over the page's DevTools protocol. WPP.chat.editMessage()
#: refuses through WhatsApp Web's own canEditMsg(), which requires
#: WAWebMessageEditUtils.isParentWithinEditProcessingWindow(): the message's
#: age must be under the remote config `message_edit_window_duration_seconds`
#: (1200 on that session, and 1200 when the config is absent). The UI offers
#: editing for less, through isParentWithinEditUIWindow(): probed with
#: synthetic ages it answered true up to 899 s and false from 900 s. The five
#: minutes between the two let an edit started near the limit still be sent.
#:
#: WinZapp used to allow three hours, so every edit between 20 minutes and 3
#: hours changed the row locally and was refused by WhatsApp (reproduced: a
#: 59-minute-old message, "Cannot edit this message"). The config is remote
#: and can change without a WinZapp update, which is why a refused edit is
#: also rolled back rather than trusting this number alone.
EDIT_UI_WINDOW_SECONDS = 900


def edit_window_open(message_ts, now=None) -> bool:
    """Whether a message sent at *message_ts* may still be offered for editing.

    Accepts seconds or milliseconds, as a number or a numeric string. A missing
    or unreadable timestamp closes the window: offering an edit WhatsApp will
    refuse is the failure this exists to prevent.
    """
    try:
        ts = float(message_ts)
    except (TypeError, ValueError):
        return False
    if ts <= 0:
        return False
    if ts > 1_000_000_000_000:
        ts /= 1000.0
    current = time.time() if now is None else now
    return (current - ts) < EDIT_UI_WINDOW_SECONDS


def response_not_sent(body_text) -> bool:
    """Whether a WPPConnect error body proves the request never reached WhatsApp.

    statusConnection.ts answers ``{"status": "Disconnected"}`` (HTTP 404) for
    every route while the session is not connected, before any controller
    runs — including ``reason: "probe_timeout"``, which is still a request
    that never reached a controller. Read without side effects on purpose:
    MainWindow._check_wa_connection_closed() recognises the same body but also
    flips the app's connection state, which an edit has no business doing.
    """
    try:
        body = json.loads(body_text or "")
    except (TypeError, ValueError):
        return False
    return isinstance(body, dict) and body.get("status") == "Disconnected"


def connection_refused(exc) -> bool:
    """Whether a requests ConnectionError is a refused connection — the one
    shape that proves nothing was sent.

    requests wraps every urllib3 failure while ``urlopen`` runs into
    ConnectionError, including RemoteDisconnected after the request already
    went out; only a ``NewConnectionError`` reason means the socket never
    opened. The same ambiguity MainWindow._classify_send_exception() already
    respects for sends.
    """
    inner = exc.args[0] if getattr(exc, "args", None) else None
    reason = getattr(inner, "reason", None)
    return isinstance(reason, NewConnectionError) or isinstance(inner, NewConnectionError)


#: Raw WPPConnect types that must never carry the "Editada" marker: a revoke
#: renders as "Mensagem apagada", and a protocol message is not a row at all.
_NEVER_MARKED_EDITED_TYPES = frozenset({"revoked", "protocol"})


def server_marks_edited(wpp_msg) -> bool:
    """Whether WhatsApp Web itself says this message was edited.

    ``_edited`` used to be set only by WinZapp (a local edit, or a live edit
    echo), so it was lost the moment a sync replaced the stored record with
    the server's copy — every edited message went back to looking unedited.
    WhatsApp Web keeps the fact on the message model: read over DevTools from
    the running app (2026-09-14), an edited reply came back from
    WAPI.getMessages — the call get-messages uses — with ``latestEditMsgKey``
    (an object) and ``latestEditSenderTimestampMs`` (a number), and 4 of the 60
    messages fetched carried them. Reading it here also marks edits made on
    another device and survives a reinstall, which no local flag can.

    Measured over the whole loaded store on the same session: 2670 messages,
    14 with ``latestEditMsgKey`` — 12 text messages and 2 image captions (a
    caption edit is a real edit) — and none carrying ``botEditType``. Not
    verified: Meta AI replies, which WhatsApp streams as a series of bot edits.
    That account had no bot chat to read, so whether those models carry
    ``latestEditMsgKey`` (and would read ", Editada") is unknown.
    """
    if not isinstance(wpp_msg, dict):
        return False
    if (wpp_msg.get("type") or "") in _NEVER_MARKED_EDITED_TYPES:
        return False
    return bool(wpp_msg.get("latestEditMsgKey"))


def carry_over_edited_marker(new_msgs, old_msgs) -> int:
    """Copy ``_edited`` from *old_msgs* onto the same message in *new_msgs*
    when the incoming copy lacks it. Returns how many were carried.

    The second line of defence behind server_marks_edited(): a sync replaces a
    chat's records with the server's copies, so a marker the server copy does
    not restate — an optimistic local edit whose echo has not landed, or a
    model that simply lacks the field — would still vanish. Being edited is
    one-way, so the marker is safe to keep for the id; the exception is a
    message since deleted for everyone, which renders as "Mensagem apagada"
    and must not read ", Editada" (_apply_remote_revoke() drops it for the
    same reason). The sync writes the merged records to the database, so this
    reaches the disk without a per-message lookup there.
    """
    marked = {
        (m.get("key") or {}).get("id")
        for m in (old_msgs or ())
        if isinstance(m, dict) and m.get("_edited")
    }
    marked.discard(None)
    marked.discard("")
    if not marked:
        return 0
    carried = 0
    for m in new_msgs or ():
        if not isinstance(m, dict) or m.get("_edited"):
            continue
        if m.get("messageType") == "protocolMessage":
            continue
        if (m.get("key") or {}).get("id") in marked:
            m["_edited"] = True
            carried += 1
    return carried


_EDIT_STATE_FIELDS = ("message", "messageType", "contextInfo", "_edited")
_ABSENT = "__absent__"


def snapshot_edit_state(msg: dict) -> dict:
    """Copy of the fields an optimistic edit rewrites, for a later rollback."""
    return {
        field: copy.deepcopy(msg[field]) if field in msg else _ABSENT
        for field in _EDIT_STATE_FIELDS
    }


def restore_edit_state(msg: dict, snapshot: dict, applied_message) -> bool:
    """Put *msg* back to *snapshot* if it still carries the edit that failed.

    *applied_message* is the body the optimistic edit wrote. When the record no
    longer holds it — a sync or a genuine later edit has replaced it since —
    nothing is restored, because that newer state is not ours to undo.
    """
    if not isinstance(msg, dict) or not isinstance(snapshot, dict):
        return False
    if msg.get("message") != applied_message:
        return False
    for field, value in snapshot.items():
        if value == _ABSENT:
            msg.pop(field, None)
        else:
            msg[field] = copy.deepcopy(value)
    return True

_MENTION_KEYS = ("mentionedJid", "mentionedJidList")


def clean_message_id(raw) -> str:
    """Bare message id from a serialized key (``true_<jid>_<id>[_…]``) or a
    MsgKey-shaped dict."""
    if isinstance(raw, dict):
        raw = raw.get("_serialized") or raw.get("id") or ""
    if not isinstance(raw, str) or not raw:
        return ""
    parts = raw.split("_")
    return parts[2] if len(parts) > 2 else parts[-1]


def is_edit_event(msg: dict) -> bool:
    """True for a normalised edit protocol message — never a row of its own."""
    if not isinstance(msg, dict) or msg.get("messageType") != "protocolMessage":
        return False
    protocol = (msg.get("message") or {}).get("protocolMessage")
    return isinstance(protocol, dict) and protocol.get("type") == MESSAGE_EDIT


def edited_text_message(existing: dict, new_text: str, extended: bool = False):
    """``(message, messageType)`` for an own edit of *existing*.

    A reply that came from sync or the phone keeps its quote only in
    ``message.extendedTextMessage.contextInfo``; rewriting the body to a bare
    ``conversation`` dropped it from the row the moment the user saved the
    edit. That nested context is carried over, minus the mention lists — the
    caller restates mentions for the new text itself. *extended* forces the
    ``extendedTextMessage`` shape (the caller has mentions to attach).
    """
    body = (existing or {}).get("message") or {}
    ext = body.get("extendedTextMessage") if isinstance(body, dict) else None
    nested_ctx = None
    if isinstance(ext, dict) and isinstance(ext.get("contextInfo"), dict):
        nested_ctx = {
            k: v for k, v in copy.deepcopy(ext["contextInfo"]).items()
            if k not in _MENTION_KEYS
        }
    if extended or nested_ctx:
        new_ext = {"text": new_text}
        if nested_ctx:
            new_ext["contextInfo"] = nested_ctx
        return {"extendedTextMessage": new_ext}, "extendedTextMessage"
    return {"conversation": new_text}, "conversation"
