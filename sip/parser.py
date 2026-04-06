"""SIP message parser.

Parses raw UDP bytes into ``SipRequest`` or ``SipResponse`` objects.
"""

from __future__ import annotations

from core.exceptions import SipParseError
from sip.messages import SipRequest, SipResponse, SipMessage

_MAX_SIP_BODY_SIZE = 64 * 1024
_ALLOWED_METHODS = {"INVITE", "ACK", "BYE", "CANCEL", "OPTIONS"}


def parse(raw: bytes) -> SipMessage:
    """Parse *raw* bytes into a :class:`SipRequest` or :class:`SipResponse`.

    Raises :class:`~core.exceptions.SipParseError` if the message is
    structurally invalid.
    """
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise SipParseError(f"Cannot decode SIP bytes: {exc}") from exc

    if "\r\n\r\n" in text:
        header_section, body = text.split("\r\n\r\n", 1)
    else:
        header_section = text
        body = ""

    lines = header_section.split("\r\n")
    if not lines:
        raise SipParseError("Empty SIP message")

    start_line = lines[0].strip()
    if not start_line:
        raise SipParseError("Missing SIP start line")

    msg: SipMessage
    if start_line.startswith("SIP/2.0"):
        parts = start_line.split(" ", 2)
        if len(parts) != 3:
            raise SipParseError(f"Malformed response start line: {start_line!r}")
        version = parts[0]
        if version != "SIP/2.0":
            raise SipParseError(f"Unsupported SIP version: {version!r}")
        try:
            status_code = int(parts[1])
        except ValueError as exc:
            raise SipParseError(f"Non-integer status code: {parts[1]!r}") from exc
        if not 100 <= status_code <= 699:
            raise SipParseError(f"SIP status code out of range: {status_code}")
        reason = parts[2]
        msg = SipResponse(status_code, reason)
    else:
        parts = start_line.split(" ", 2)
        if len(parts) != 3:
            raise SipParseError(f"Malformed request start line: {start_line!r}")
        method, request_uri, version = parts
        if version != "SIP/2.0":
            raise SipParseError(f"Unsupported SIP version: {version!r}")
        method = method.upper()
        if method not in _ALLOWED_METHODS:
            raise SipParseError(f"Unsupported SIP method: {method!r}")
        msg = SipRequest(method, request_uri)

    for line in lines[1:]:
        if not line.strip():
            continue
        if ":" not in line:
            raise SipParseError(f"Malformed header line: {line!r}")
        name, _, value = line.partition(":")
        msg.set_header(name.strip(), value.strip())

    cl_str = msg.get_header("Content-Length").strip()
    if not cl_str:
        msg.body = body
        return msg

    try:
        cl = int(cl_str)
    except ValueError as exc:
        raise SipParseError(f"Invalid Content-Length value: {cl_str!r}") from exc

    if cl < 0 or cl > _MAX_SIP_BODY_SIZE:
        raise SipParseError(f"Content-Length out of range: {cl}")
    if cl > len(body):
        raise SipParseError(f"Content-Length exceeds available body bytes: {cl} > {len(body)}")
    if cl < len(body):
        raise SipParseError(f"Content-Length smaller than body bytes: {cl} < {len(body)}")
    msg.body = body[:cl]

    return msg
