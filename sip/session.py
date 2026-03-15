"""SIP session state machines for caller (Client 1) and callee (Client 2).

Each class drives the SIP handshake through a well-defined set of states
and exposes the high-level methods that the application layer calls.
"""

from __future__ import annotations

import socket
from enum import Enum, auto
from typing import Optional

from core.exceptions import SessionError, SipParseError
from core.log import get_logger
from net.udp import UdpSocketAdapter
from sip import messages as m
from sip import parser as p
from sip.sdp import SdpDescription

logger = get_logger("sip.session")


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
        )
        data = req.serialize()
        self._sock.send(data, self.remote_ip, self.remote_sip_port)
        self.state = CallerState.INVITE_SENT
        logger.info("[%s] INVITE sent  call-id=%s", self.state.name, self.call_id)

    def receive_200_ok(self) -> bool:
        """Wait for a 200 OK response.

        Returns ``True`` when a 200 OK is received and the ACK is sent.
        Returns ``False`` on timeout or unrecoverable error.
        """
        if self.state != CallerState.INVITE_SENT:
            raise SessionError(f"Not waiting for 200 OK in state {self.state}")
        try:
            raw, _ = self._sock.recv(4096)
        except socket.timeout:
            logger.warning("[INVITE_SENT] Timeout waiting for 200 OK")
            return False

        try:
            msg = p.parse(raw)
        except SipParseError as exc:
            logger.error("Failed to parse SIP message: %s", exc)
            return False

        if not isinstance(msg, m.SipResponse):
            logger.warning("Expected SIP response, got %s", type(msg).__name__)
            return False

        if msg.status_code >= 400:
            logger.error("Received error response %d %s", msg.status_code, msg.reason)
            self.state = CallerState.TERMINATED
            return False

        if msg.status_code != 200:
            logger.warning("Unexpected status code %d — ignoring", msg.status_code)
            return False

        # Extract To-tag for subsequent requests
        to_header = msg.get_header("To")
        if ";tag=" in to_header:
            self.to_tag = to_header.split(";tag=", 1)[1].split(";")[0]

        # Parse remote SDP
        if msg.body:
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
            except Exception as exc:
                logger.error("Failed to parse remote SDP: %s", exc)

        # Send ACK
        ack = m.build_ack(
            caller_ip=self.local_ip,
            caller_sip_port=self.local_sip_port,
            callee_ip=self.remote_ip,
            callee_sip_port=self.remote_sip_port,
            call_id=self.call_id,
            from_tag=self.from_tag,
            to_tag=self.to_tag,
        )
        self._sock.send(ack.serialize(), self.remote_ip, self.remote_sip_port)
        self.state = CallerState.ESTABLISHED
        logger.info("[%s] ACK sent", self.state.name)
        return True

    def send_bye(self) -> None:
        """Send a BYE to terminate the call."""
        if self.state not in (CallerState.ESTABLISHED, CallerState.INVITE_SENT):
            logger.warning("BYE requested in unexpected state %s — sending anyway", self.state)
        bye = m.build_bye(
            caller_ip=self.local_ip,
            caller_sip_port=self.local_sip_port,
            callee_ip=self.remote_ip,
            callee_sip_port=self.remote_sip_port,
            call_id=self.call_id,
            from_tag=self.from_tag,
            to_tag=self.to_tag,
        )
        self._sock.send(bye.serialize(), self.remote_ip, self.remote_sip_port)
        self.state = CallerState.TERMINATING
        logger.info("[TERMINATING] BYE sent")

    def receive_bye_ok(self) -> None:
        """Wait for 200 OK to BYE and transition to TERMINATED."""
        try:
            raw, _ = self._sock.recv(4096)
            msg = p.parse(raw)
            if isinstance(msg, m.SipResponse) and msg.status_code == 200:
                logger.info("[TERMINATING] Received 200 OK to BYE")
        except socket.timeout:
            logger.warning("Timeout waiting for 200 OK to BYE — assuming terminated")
        except SipParseError:
            pass
        self.state = CallerState.TERMINATED
        logger.info("[TERMINATED]")


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

    def wait_for_invite(self) -> bool:
        """Block until a SIP INVITE is received.

        Returns ``True`` when an INVITE is successfully received.
        Returns ``False`` on timeout.
        """
        if self.state != CalleeState.IDLE:
            raise SessionError(f"Cannot wait for INVITE in state {self.state}")
        logger.info("[IDLE] Waiting for INVITE…")
        try:
            raw, (addr, port) = self._sock.recv(4096)
        except socket.timeout:
            logger.warning("[IDLE] Timeout waiting for INVITE")
            return False

        try:
            msg = p.parse(raw)
        except SipParseError as exc:
            logger.error("Failed to parse incoming message: %s", exc)
            return False

        if not isinstance(msg, m.SipRequest) or msg.method != "INVITE":
            logger.warning("Expected INVITE, got %s — ignoring", getattr(msg, "method", type(msg).__name__))
            return False

        self.remote_ip = addr
        self.remote_sip_port = port
        self._last_invite = msg
        self.state = CalleeState.INVITE_RECEIVED
        logger.info("[INVITE_RECEIVED] From %s:%d  call-id=%s", addr, port, msg.get_header("Call-ID"))

        # Parse offered SDP
        if msg.body:
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
            except Exception as exc:
                logger.error("Failed to parse offered SDP: %s", exc)

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

    def wait_for_ack(self) -> bool:
        """Block until an ACK is received."""
        if self.state != CalleeState.OK_SENT:
            raise SessionError(f"Cannot wait for ACK in state {self.state}")
        try:
            raw, _ = self._sock.recv(4096)
        except socket.timeout:
            logger.warning("[OK_SENT] Timeout waiting for ACK")
            return False

        try:
            msg = p.parse(raw)
        except SipParseError as exc:
            logger.error("Failed to parse ACK: %s", exc)
            return False

        if not isinstance(msg, m.SipRequest) or msg.method != "ACK":
            logger.warning("Expected ACK, got %s — ignoring", getattr(msg, "method", type(msg).__name__))
            return False

        self.state = CalleeState.ESTABLISHED
        logger.info("[ESTABLISHED] ACK received — session up")
        return True

    def wait_for_bye(self) -> bool:
        """Block until a BYE is received, then send 200 OK."""
        logger.info("[ESTABLISHED] Waiting for BYE…")
        while True:
            try:
                raw, _ = self._sock.recv(4096)
            except socket.timeout:
                # Keep looping — BYE may arrive late
                continue

            try:
                msg = p.parse(raw)
            except SipParseError:
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
            logger.debug("Ignoring unexpected message: %s", raw[:80])
