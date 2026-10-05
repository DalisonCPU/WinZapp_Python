"""Contacts that WhatsApp syncs to the phone's address book.

A local contact (NewContactDialog's first tab) lives only inside WinZapp. A
phone-synced one is saved in WhatsApp through the server's ``save-contact``
route (WPP.contact.save with syncAddressBook), which is the action WhatsApp
Web's own "add contact" runs, and ends up in the phone's address book.

Plain functions over an injectable ``post``, no wx and no network of their
own, so the request shapes and the error mapping are tested directly.
"""

import re

from core.api_client import api_post

#: Set on the contact record of a phone-synced contact, next to isSaved.
SYNCED_KEY = "syncedToPhone"

#: Shortest number WhatsApp can have; below it nothing is sent.
MIN_DIGITS = 7

#: i18n keys for each way saving can fail.
ERR_INVALID = "create_contact_error"
ERR_NOT_ON_WHATSAPP = "new_contact_phone_not_on_whatsapp"
ERR_FAILED = "new_contact_phone_failed"

# Answers that mean the contact is already not in the address book: removing
# it has nothing left to do.
_ALREADY_GONE = {"contact_not_found", "number_is_not_your_contact"}


def digits_of(phone: str) -> str:
    return re.sub(r"\D", "", phone or "")


def is_phone_synced(contact) -> bool:
    return bool(contact) and bool(contact.get(SYNCED_KEY))


def synced_entry(jid: str, full_name: str) -> dict:
    """The contact record a successful save leaves in WinZapp."""
    return {"remoteJid": jid, "name": full_name, "pushName": full_name,
            "isSaved": True, SYNCED_KEY: True}


def local_entry(jid: str, full_name: str) -> dict:
    return {"remoteJid": jid, "name": full_name, "pushName": full_name, "isSaved": True}


def _url(base: str, token: str, route: str) -> str:
    return f"{base}/api/{token}/{route}"


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _error_of(resp) -> str:
    """The i18n key for a refused request."""
    try:
        body = resp.json()
    except Exception:
        body = {}
    code = body.get("code", "") if isinstance(body, dict) else ""
    if code == "contact_invalid":
        return ERR_INVALID
    if resp.status_code == 400 and not code:
        # The server's contact validation: "the number does not exist".
        return ERR_NOT_ON_WHATSAPP
    return ERR_FAILED


def _code_of(resp) -> str:
    try:
        body = resp.json()
    except Exception:
        return ""
    return body.get("code", "") if isinstance(body, dict) else ""


def save_contact(base: str, token: str, phone: str, first: str, last: str = "",
                 post=api_post) -> tuple:
    """Save the contact in WhatsApp, synced to the phone.

    Returns ``(True, "")`` or ``(False, i18n_key)``. Blocks for the length of
    the request: call it off the main thread.
    """
    digits = digits_of(phone)
    if len(digits) < MIN_DIGITS:
        return False, ERR_INVALID
    payload = {"phone": digits, "name": first, "lastName": last, "syncAddressBook": True}
    try:
        resp = post(_url(base, token, "save-contact"), json=payload,
                    headers=_headers(token), timeout=20)
    except Exception:
        return False, ERR_FAILED
    if resp.ok:
        return True, ""
    return False, _error_of(resp)


def remove_contact(base: str, token: str, phone: str, post=api_post) -> bool:
    """Remove the contact from WhatsApp and the phone. True when it is gone,
    including when it was already not a contact."""
    digits = digits_of(phone)
    if len(digits) < MIN_DIGITS:
        return False
    try:
        resp = post(_url(base, token, "remove-contact"), json={"phone": digits},
                    headers=_headers(token), timeout=20)
    except Exception:
        return False
    return bool(resp.ok) or _code_of(resp) in _ALREADY_GONE
