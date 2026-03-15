"""SIP message model — builder and serializer.

Only the subset of SIP required by the project spec is implemented:
INVITE, 200 OK, ACK, BYE (plus minimal 4xx/5xx error responses).
"""

from __future__ import annotations

import uuid
from typing import Optional


# ---------------------------------------------------------------------------
# SIP message base
# ---------------------------------------------------------------------------

class SipMessage:
    """Holds headers and an optional body for a SIP message."""

    def __init__(self) -> None:
        self.headers: dict[str, str] = {}
        self.body: str = ""

    def set_header(self, name: str, value: str) -> None:
        self.headers[name] = value

    def get_header(self, name: str, default: str = "") -> str:
        # Case-insensitive lookup
        lower = name.lower()
        for k, v in self.headers.items():
            if k.lower() == lower:
                return v
        return default

    def _header_lines(self) -> str:
        lines = []
        for k, v in self.headers.items():
            lines.append(f"{k}: {v}")
        return "\r\n".join(lines)

    def serialize(self) -> bytes:
        raise NotImplementedError


class SipRequest(SipMessage):
    """A SIP request (INVITE, ACK, BYE, …)."""

    def __init__(self, method: str, request_uri: str) -> None:
        super().__init__()
        self.method = method
        self.request_uri = request_uri

    def serialize(self) -> bytes:
        body_bytes = self.body.encode()
        self.set_header("Content-Length", str(len(body_bytes)))
        start_line = f"{self.method} {self.request_uri} SIP/2.0"
        raw = f"{start_line}\r\n{self._header_lines()}\r\n\r\n"
        return raw.encode() + body_bytes


class SipResponse(SipMessage):
    """A SIP response (1xx–5xx)."""

    def __init__(self, status_code: int, reason: str) -> None:
        super().__init__()
        self.status_code = status_code
        self.reason = reason

    def serialize(self) -> bytes:
        body_bytes = self.body.encode()
        self.set_header("Content-Length", str(len(body_bytes)))
        start_line = f"SIP/2.0 {self.status_code} {self.reason}"
        raw = f"{start_line}\r\n{self._header_lines()}\r\n\r\n"
        return raw.encode() + body_bytes


# ---------------------------------------------------------------------------
# SIP builder helpers
# ---------------------------------------------------------------------------

def _new_call_id() -> str:
    return uuid.uuid4().hex


def _new_tag() -> str:
    return uuid.uuid4().hex[:8]


def _new_branch() -> str:
    return "z9hG4bK" + uuid.uuid4().hex[:12]


def build_invite(
    caller_ip: str,
    caller_sip_port: int,
    callee_ip: str,
    callee_sip_port: int,
    sdp_body: str,
    call_id: Optional[str] = None,
    from_tag: Optional[str] = None,
    branch: Optional[str] = None,
) -> tuple[SipRequest, str, str]:
    """Build a SIP INVITE request.

    Returns ``(request, call_id, from_tag)`` so the caller can store them
    for subsequent requests in the same dialog.
    """
    call_id = call_id or _new_call_id()
    from_tag = from_tag or _new_tag()
    branch = branch or _new_branch()

    req = SipRequest("INVITE", f"sip:client2@{callee_ip}:{callee_sip_port}")
    req.set_header("Via", f"SIP/2.0/UDP {caller_ip}:{caller_sip_port};branch={branch}")
    req.set_header("Max-Forwards", "70")
    req.set_header("From", f"<sip:client1@{caller_ip}:{caller_sip_port}>;tag={from_tag}")
    req.set_header("To", f"<sip:client2@{callee_ip}:{callee_sip_port}>")
    req.set_header("Call-ID", call_id)
    req.set_header("CSeq", "1 INVITE")
    req.set_header("Contact", f"<sip:client1@{caller_ip}:{caller_sip_port}>")
    req.set_header("Content-Type", "application/sdp")
    req.body = sdp_body
    return req, call_id, from_tag


def build_200_ok(
    invite: "SipRequest",
    callee_ip: str,
    callee_sip_port: int,
    sdp_body: str,
    to_tag: Optional[str] = None,
) -> SipResponse:
    """Build a 200 OK response to an INVITE."""
    to_tag = to_tag or _new_tag()
    resp = SipResponse(200, "OK")
    resp.set_header("Via", invite.get_header("Via"))
    resp.set_header("From", invite.get_header("From"))
    to_val = invite.get_header("To")
    if ";tag=" not in to_val:
        to_val = f"{to_val};tag={to_tag}"
    resp.set_header("To", to_val)
    resp.set_header("Call-ID", invite.get_header("Call-ID"))
    resp.set_header("CSeq", invite.get_header("CSeq"))
    resp.set_header("Contact", f"<sip:client2@{callee_ip}:{callee_sip_port}>")
    resp.set_header("Content-Type", "application/sdp")
    resp.body = sdp_body
    return resp


def build_ack(
    caller_ip: str,
    caller_sip_port: int,
    callee_ip: str,
    callee_sip_port: int,
    call_id: str,
    from_tag: str,
    to_tag: str,
) -> SipRequest:
    """Build a SIP ACK request."""
    branch = _new_branch()
    req = SipRequest("ACK", f"sip:client2@{callee_ip}:{callee_sip_port}")
    req.set_header("Via", f"SIP/2.0/UDP {caller_ip}:{caller_sip_port};branch={branch}")
    req.set_header("Max-Forwards", "70")
    req.set_header("From", f"<sip:client1@{caller_ip}:{caller_sip_port}>;tag={from_tag}")
    req.set_header("To", f"<sip:client2@{callee_ip}:{callee_sip_port}>;tag={to_tag}")
    req.set_header("Call-ID", call_id)
    req.set_header("CSeq", "1 ACK")
    req.set_header("Content-Length", "0")
    return req


def build_bye(
    caller_ip: str,
    caller_sip_port: int,
    callee_ip: str,
    callee_sip_port: int,
    call_id: str,
    from_tag: str,
    to_tag: str,
    cseq: int = 2,
) -> SipRequest:
    """Build a SIP BYE request."""
    branch = _new_branch()
    req = SipRequest("BYE", f"sip:client2@{callee_ip}:{callee_sip_port}")
    req.set_header("Via", f"SIP/2.0/UDP {caller_ip}:{caller_sip_port};branch={branch}")
    req.set_header("Max-Forwards", "70")
    req.set_header("From", f"<sip:client1@{caller_ip}:{caller_sip_port}>;tag={from_tag}")
    req.set_header("To", f"<sip:client2@{callee_ip}:{callee_sip_port}>;tag={to_tag}")
    req.set_header("Call-ID", call_id)
    req.set_header("CSeq", f"{cseq} BYE")
    req.set_header("Content-Length", "0")
    return req


def build_200_ok_bye(bye_request: "SipRequest") -> SipResponse:
    """Build a 200 OK response to a BYE."""
    resp = SipResponse(200, "OK")
    resp.set_header("Via", bye_request.get_header("Via"))
    resp.set_header("From", bye_request.get_header("From"))
    resp.set_header("To", bye_request.get_header("To"))
    resp.set_header("Call-ID", bye_request.get_header("Call-ID"))
    resp.set_header("CSeq", bye_request.get_header("CSeq"))
    resp.set_header("Content-Length", "0")
    return resp


def build_error_response(request: "SipRequest", status_code: int, reason: str) -> SipResponse:
    """Build a generic 4xx/5xx error response."""
    resp = SipResponse(status_code, reason)
    resp.set_header("Via", request.get_header("Via"))
    resp.set_header("From", request.get_header("From"))
    resp.set_header("To", request.get_header("To"))
    resp.set_header("Call-ID", request.get_header("Call-ID"))
    resp.set_header("CSeq", request.get_header("CSeq"))
    resp.set_header("Content-Length", "0")
    return resp
