"""SIP session state machines for caller (Client 1) and callee (Client 2).

Each class drives the SIP handshake through a well-defined set of states
and exposes the high-level methods that the application layer calls.
"""

from __future__ import annotations

import re
import socket
import time
from enum import Enum, auto
from typing import Optional

from core.exceptions import SdpError, SessionError, SipParseError
from core.log import get_logger
from net.udp import UdpSocketAdapter
from sip import messages as m
from sip import parser as p
from sip.sdp import SdpDescription

logger = get_logger("sip.session")

_TO_TAG_RE = re.compile(r"^[A-Za-z0-9\-_.!~*'()]+$")


# ---------------------------------------------------------------------------
# State enumerations
# ---------------------------------------------------------------------------

class CallerState(Enum):
    IDLE = auto()
    INVITE_SENT = auto()
    ESTABLISHED = auto()
    TERMINATING = auto()
    TERMINATED = auto()


class CalleeState(Enum):
    IDLE = auto()
    INVITE_RECEIVED = auto()
    OK_SENT = auto()
    ESTABLISHED = auto()
    TERMINATING = auto()
    TERMINATED = auto()


# ---------------------------------------------------------------------------
# Caller session
# ---------------------------------------------------------------------------

class CallerSession:
    """Manages the caller side of a SIP dialog.

    Parameters
    ----------
    sock:
        Open :class:`~net.udp.UdpSocketAdapter` bound to the caller SIP port.
    local_ip:
        Caller's IP address (used in headers and SDP).
    local_sip_port:
        Caller's SIP port.
    remote_ip:
        Callee's IP address.
    remote_sip_port:
        Callee's SIP port.
    local_sdp:
        SDP describing the caller's RTP endpoint (offer).
    """

    def __init__(
        self,
        sock: UdpSocketAdapter,
        local_ip: str,
        local_sip_port: int,
        remote_ip: str,
        remote_sip_port: int,
        local_sdp: SdpDescription,
    ) -> None:
        self._sock = sock
        self.local_ip = local_ip
        self.local_sip_port = local_sip_port
        self.remote_ip = remote_ip
        self.remote_sip_port = remote_sip_port
        self.local_sdp = local_sdp

        self.state = CallerState.IDLE
        self.call_id: str = ""
        self.from_tag: str = ""
        self.to_tag: str = ""
        self.remote_sdp: Optional[SdpDescription] = None
        self._invite_cseq: int = 1

    def send_invite(self) -> None:
        """Build and send the SIP INVITE.  Transitions to INVITE_SENT."""
        if self.state != CallerState.IDLE:
            raise SessionError(f"Cannot send INVITE in state {self.state}")
        req, self.call_id, self.from_tag = m.build_invite(
            caller_ip=self.local_ip,
            caller_sip_port=self.local_sip_port,
            callee_ip=self.remote_ip,
            callee_sip_port=self.remote_sip_port,
            sdp_body=self.local_sdp.build(),
            cseq=self._invite_cseq,
        )
        data = req.serialize()
        self._sock.send(data, self.remote_ip, self.remote_sip_port)
        self.state = CallerState.INVITE_SENT
        logger.info("[%s] INVITE sent  call-id=%s", self.state.name, self.call_id)

    def receive_200_ok(
        self,
        max_parse_errors: int = 100,
        max_unexpected_messages: int = 100,
        max_wait_s: float = 30.0,
    ) -> bool:
        """Wait for a 200 OK response.

        Returns ``True`` when a 200 OK is received and the ACK is sent.
        Returns ``False`` on timeout or unrecoverable error.
        """
        if self.state != CallerState.INVITE_SENT:
            raise SessionError(f"Not waiting for 200 OK in state {self.state}")
        deadline = time.monotonic() + max_wait_s
        parse_errors = 0
        unexpected_messages = 0

        while True:
            if time.monotonic() > deadline:
                logger.warning("[INVITE_SENT] Timeout waiting for 200 OK after %.1f seconds", max_wait_s)
                return False

            try:
                raw, _ = self._sock.recv(4096)
            except socket.timeout:
                continue

            try:
                msg = p.parse(raw)
                parse_errors = 0
            except SipParseError as exc:
                parse_errors += 1
                if parse_errors > max_parse_errors:
                    logger.error(
                        "Too many invalid SIP packets while waiting for 200 OK: %d",
                        parse_errors,
                    )
                    return False
                logger.debug("Ignoring malformed SIP while waiting for 200 OK: %s", exc)
                continue

            if not isinstance(msg, m.SipResponse):
                unexpected_messages += 1
                if unexpected_messages > max_unexpected_messages:
                    logger.error(
                        "Too many unexpected SIP messages while waiting for 200 OK: %d",
                        unexpected_messages,
                    )
                    return False
                logger.debug("Ignoring non-response SIP message while waiting for 200 OK")
                continue

            if 100 <= msg.status_code < 200:
                logger.debug("Received provisional response %d %s", msg.status_code, msg.reason)
                continue

            if msg.status_code >= 300:
                logger.error("Received final non-success response %d %s", msg.status_code, msg.reason)
                self.state = CallerState.TERMINATED
                return False

            if msg.status_code != 200:
                unexpected_messages += 1
                if unexpected_messages > max_unexpected_messages:
                    logger.error(
                        "Too many unexpected SIP status codes while waiting for 200 OK: %d",
                        unexpected_messages,
                    )
                    return False
                logger.debug("Ignoring unexpected status code %d while waiting for 200 OK", msg.status_code)
                continue

            if msg.get_header("Call-ID") != self.call_id:
                logger.error("Call-ID mismatch in 200 OK")
                self.state = CallerState.TERMINATED
                return False

            cseq = msg.get_header("CSeq").strip()
            cseq_parts = cseq.split()
            if len(cseq_parts) != 2:
                logger.error("Malformed CSeq in 200 OK: %s", cseq)
                self.state = CallerState.TERMINATED
                return False
            try:
                cseq_num = int(cseq_parts[0])
            except ValueError:
                logger.error("Non-integer CSeq in 200 OK: %s", cseq)
                self.state = CallerState.TERMINATED
                return False
            if cseq_num != self._invite_cseq or cseq_parts[1].upper() != "INVITE":
                logger.error("Unexpected CSeq in 200 OK: %s", cseq)
                self.state = CallerState.TERMINATED
                return False

            # Extract To-tag for subsequent requests
            to_header = msg.get_header("To").strip()
            if not to_header:
                logger.error("Received 200 OK without To header")
                self.state = CallerState.TERMINATED
                return False

            to_tag = ""
            for param in to_header.split(";")[1:]:
                key, sep, value = param.strip().partition("=")
                if sep and key.lower() == "tag":
                    to_tag = value.strip()
                    break

            if not to_tag or not _TO_TAG_RE.match(to_tag):
                logger.error("Received 200 OK without valid To-tag")
                self.state = CallerState.TERMINATED
                return False

            self.to_tag = to_tag

            content_type = msg.get_header("Content-Type").strip().lower()
            if content_type != "application/sdp":
                logger.error("Expected application/sdp in 200 OK, got %r", content_type)
                self.state = CallerState.TERMINATED
                return False

            if not msg.body:
                logger.error("Received 200 OK without SDP body")
                self.state = CallerState.TERMINATED
                return False

            try:
                self.remote_sdp = SdpDescription.parse(msg.body)
                logger.info(
                    "Remote SDP: ip=%s rtp_port=%d codec=%s/%d pt=%d",
                    self.remote_sdp.media_ip,
                    self.remote_sdp.rtp_port,
                    self.remote_sdp.codec_name,
                    self.remote_sdp.clock_rate,
                    self.remote_sdp.payload_type,
                )
            except (SdpError, ValueError) as exc:
                logger.error("Failed to parse remote SDP: %s", exc)
                self.state = CallerState.TERMINATED
                return False

            # Send ACK
            ack = m.build_ack(
                caller_ip=self.local_ip,
                caller_sip_port=self.local_sip_port,
                callee_ip=self.remote_ip,
                callee_sip_port=self.remote_sip_port,
                call_id=self.call_id,
                from_tag=self.from_tag,
                to_tag=self.to_tag,
                cseq=self._invite_cseq,
            )
            self._sock.send(ack.serialize(), self.remote_ip, self.remote_sip_port)
            self.state = CallerState.ESTABLISHED
            logger.info("[%s] ACK sent", self.state.name)
            return True

    def send_bye(self) -> None:
        """Send a BYE to terminate the call."""
        if self.state != CallerState.ESTABLISHED:
            raise SessionError(f"Cannot send BYE in state {self.state}")
        if not self.call_id or not self.from_tag:
            raise SessionError("Cannot send BYE without active dialog identifiers")
        bye = m.build_bye(
            caller_ip=self.local_ip,
            caller_sip_port=self.local_sip_port,
            callee_ip=self.remote_ip,
            callee_sip_port=self.remote_sip_port,
            call_id=self.call_id,
            from_tag=self.from_tag,
            to_tag=self.to_tag,
            cseq=self._invite_cseq + 1,
        )
        self._sock.send(bye.serialize(), self.remote_ip, self.remote_sip_port)
        self.state = CallerState.TERMINATING
        logger.info("[TERMINATING] BYE sent")

    def receive_bye_ok(self) -> bool:
        """Wait for 200 OK to BYE and transition to TERMINATED."""
        if self.state != CallerState.TERMINATING:
            raise SessionError(f"Not waiting for BYE response in state {self.state}")
        try:
            raw, _ = self._sock.recv(4096)
            msg = p.parse(raw)
            if isinstance(msg, m.SipResponse) and msg.status_code == 200:
                logger.info("[TERMINATING] Received 200 OK to BYE")
                self.state = CallerState.TERMINATED
                logger.info("[TERMINATED]")
                return True
        except socket.timeout:
            logger.warning("Timeout waiting for 200 OK to BYE — assuming terminated")
        except SipParseError as exc:
            logger.warning("Failed to parse BYE response: %s", exc)
        self.state = CallerState.TERMINATED
        logger.info("[TERMINATED]")
        return False


# ---------------------------------------------------------------------------
# Callee session
# ---------------------------------------------------------------------------

class CalleeSession:
    """Manages the callee side of a SIP dialog.

    Parameters
    ----------
    sock:
        Open :class:`~net.udp.UdpSocketAdapter` bound to the callee SIP port.
    local_ip:
        Callee's IP address (used in headers and SDP).
    local_sip_port:
        Callee's SIP port.
    local_sdp:
        SDP describing the callee's RTP endpoint (answer).
    """

    def __init__(
        self,
        sock: UdpSocketAdapter,
        local_ip: str,
        local_sip_port: int,
        local_sdp: SdpDescription,
    ) -> None:
        self._sock = sock
        self.local_ip = local_ip
        self.local_sip_port = local_sip_port
        self.local_sdp = local_sdp

        self.state = CalleeState.IDLE
        self.remote_ip: str = ""
        self.remote_sip_port: int = 0
        self.remote_sdp: Optional[SdpDescription] = None
        self._last_invite: Optional[m.SipRequest] = None

    def wait_for_invite(
        self,
        max_parse_errors: int = 100,
        max_unexpected_messages: int = 100,
        max_wait_s: float = 30.0,
    ) -> bool:
        """Block until a SIP INVITE is received.

        Returns ``True`` when an INVITE is successfully received.
        Returns ``False`` on timeout.
        """
        if self.state != CalleeState.IDLE:
            raise SessionError(f"Cannot wait for INVITE in state {self.state}")
        logger.info("[IDLE] Waiting for INVITE…")
        deadline = time.monotonic() + max_wait_s
        parse_errors = 0
        unexpected_messages = 0

        while True:
            if time.monotonic() > deadline:
                logger.warning("[IDLE] Timeout waiting for INVITE after %.1f seconds", max_wait_s)
                return False

            try:
                raw, (addr, port) = self._sock.recv(4096)
            except socket.timeout:
                continue

            try:
                msg = p.parse(raw)
                parse_errors = 0
            except SipParseError as exc:
                parse_errors += 1
                if parse_errors > max_parse_errors:
                    logger.error("Too many invalid SIP packets while waiting for INVITE: %d", parse_errors)
                    return False
                logger.debug("Ignoring malformed SIP while waiting for INVITE: %s", exc)
                continue

            if not isinstance(msg, m.SipRequest) or msg.method != "INVITE":
                unexpected_messages += 1
                if unexpected_messages > max_unexpected_messages:
                    logger.error(
                        "Too many unexpected SIP messages while waiting for INVITE: %d",
                        unexpected_messages,
                    )
                    return False
                logger.debug(
                    "Ignoring unexpected SIP message while waiting for INVITE: %s",
                    getattr(msg, "method", type(msg).__name__),
                )
                continue

            self.remote_ip = addr
            self.remote_sip_port = port
            self._last_invite = msg
            content_type = msg.get_header("Content-Type").strip().lower()
            if content_type != "application/sdp":
                logger.error("Expected application/sdp in INVITE, got %r", content_type)
                error = m.build_error_response(msg, 415, "Unsupported Media Type")
                self._sock.send(error.serialize(), self.remote_ip, self.remote_sip_port)
                self.state = CalleeState.TERMINATED
                return False

            if not msg.body:
                logger.error("Received INVITE without SDP body")
                error = m.build_error_response(msg, 400, "Bad Request")
                self._sock.send(error.serialize(), self.remote_ip, self.remote_sip_port)
                self.state = CalleeState.TERMINATED
                return False

            try:
                self.remote_sdp = SdpDescription.parse(msg.body)
                logger.info(
                    "Offered SDP: ip=%s rtp_port=%d codec=%s/%d pt=%d",
                    self.remote_sdp.media_ip,
                    self.remote_sdp.rtp_port,
                    self.remote_sdp.codec_name,
                    self.remote_sdp.clock_rate,
                    self.remote_sdp.payload_type,
                )
            except (SdpError, ValueError) as exc:
                logger.error("Failed to parse offered SDP: %s", exc)
                error = m.build_error_response(msg, 488, "Not Acceptable Here")
                self._sock.send(error.serialize(), self.remote_ip, self.remote_sip_port)
                self.state = CalleeState.TERMINATED
                return False

            self.state = CalleeState.INVITE_RECEIVED
            logger.info("[INVITE_RECEIVED] From %s:%d  call-id=%s", addr, port, msg.get_header("Call-ID"))
            return True

    def send_200_ok(self) -> None:
        """Send 200 OK with local SDP answer."""
        if self.state != CalleeState.INVITE_RECEIVED:
            raise SessionError(f"Cannot send 200 OK in state {self.state}")
        if self._last_invite is None:
            raise SessionError("No INVITE stored")
        resp = m.build_200_ok(
            invite=self._last_invite,
            callee_ip=self.local_ip,
            callee_sip_port=self.local_sip_port,
            sdp_body=self.local_sdp.build(),
        )
        self._sock.send(resp.serialize(), self.remote_ip, self.remote_sip_port)
        self.state = CalleeState.OK_SENT
        logger.info("[OK_SENT] 200 OK sent")

    def wait_for_ack(
        self,
        max_parse_errors: int = 100,
        max_unexpected_messages: int = 100,
        max_wait_s: float = 30.0,
    ) -> bool:
        """Block until an ACK is received."""
        if self.state != CalleeState.OK_SENT:
            raise SessionError(f"Cannot wait for ACK in state {self.state}")
        deadline = time.monotonic() + max_wait_s
        parse_errors = 0
        unexpected_messages = 0

        while True:
            if time.monotonic() > deadline:
                logger.warning("[OK_SENT] Timeout waiting for ACK after %.1f seconds", max_wait_s)
                return False

            try:
                raw, _ = self._sock.recv(4096)
            except socket.timeout:
                continue

            try:
                msg = p.parse(raw)
                parse_errors = 0
            except SipParseError as exc:
                parse_errors += 1
                if parse_errors > max_parse_errors:
                    logger.error("Too many invalid SIP packets while waiting for ACK: %d", parse_errors)
                    return False
                logger.debug("Ignoring malformed SIP while waiting for ACK: %s", exc)
                continue

            if not isinstance(msg, m.SipRequest) or msg.method != "ACK":
                unexpected_messages += 1
                if unexpected_messages > max_unexpected_messages:
                    logger.error(
                        "Too many unexpected SIP messages while waiting for ACK: %d",
                        unexpected_messages,
                    )
                    return False
                logger.debug(
                    "Ignoring unexpected SIP message while waiting for ACK: %s",
                    getattr(msg, "method", type(msg).__name__),
                )
                continue

            self.state = CalleeState.ESTABLISHED
            logger.info("[ESTABLISHED] ACK received — session up")
            return True

    def wait_for_bye(
        self,
        max_parse_errors: int = 100,
        max_unexpected_messages: int = 100,
        max_wait_s: float = 30.0,
        log_timeout: bool = True,
        log_waiting: bool = True,
    ) -> bool:
        """Block until a BYE is received, then send 200 OK."""
        if self.state != CalleeState.ESTABLISHED:
            raise SessionError(f"Cannot wait for BYE in state {self.state}")
        if log_waiting:
            logger.info("[ESTABLISHED] Waiting for BYE…")
        deadline = time.monotonic() + max_wait_s
        parse_errors = 0
        unexpected_messages = 0
        while True:
            if time.monotonic() > deadline:
                if log_timeout:
                    logger.warning("Timed out waiting for BYE after %.1f seconds", max_wait_s)
                return False
            try:
                raw, _ = self._sock.recv(4096)
            except socket.timeout:
                # Keep looping — BYE may arrive late
                continue

            try:
                msg = p.parse(raw)
                parse_errors = 0
            except SipParseError as exc:
                parse_errors += 1
                if parse_errors > max_parse_errors:
                    logger.error("Too many invalid SIP packets while waiting for BYE: %d", parse_errors)
                    return False
                logger.debug("Ignoring malformed SIP while waiting for BYE: %s", exc)
                continue

            if isinstance(msg, m.SipRequest) and msg.method == "BYE":
                self.state = CalleeState.TERMINATING
                logger.info("[TERMINATING] BYE received — sending 200 OK")
                ok = m.build_200_ok_bye(msg)
                self._sock.send(ok.serialize(), self.remote_ip, self.remote_sip_port)
                self.state = CalleeState.TERMINATED
                logger.info("[TERMINATED]")
                return True

            # Unexpected message — log and ignore
            unexpected_messages += 1
            if unexpected_messages > max_unexpected_messages:
                logger.error(
                    "Too many unexpected SIP messages while waiting for BYE: %d",
                    unexpected_messages,
                )
                return False
            logger.debug("Ignoring unexpected message: %s", raw[:80])
