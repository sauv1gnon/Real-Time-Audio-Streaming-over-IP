"""SDP (Session Description Protocol) builder and parser.

Only the subset required by the project is supported:
  v=, o=, s=, c=, t=, m=, a=rtpmap
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass, field
from typing import Optional

from core.exceptions import SdpError


@dataclass
class SdpDescription:
    """Holds the SDP fields needed to set up an RTP media session."""

    # Connection / origin
    origin_username: str = "-"
    session_id: str = "0"
    session_version: str = "0"
    net_type: str = "IN"
    addr_type: str = "IP4"
    unicast_addr: str = "127.0.0.1"

    # Session
    session_name: str = "VoIP Demo"

    # Media
    media_ip: str = "127.0.0.1"
    rtp_port: int = 10000
    payload_type: int = 96          # Dynamic PT for raw PCM
    codec_name: str = "L16"         # Linear 16-bit PCM
    clock_rate: int = 8000

    # Extra attributes (stored as list of "key:value" or plain "key" strings)
    extra_attrs: list[str] = field(default_factory=list)

    # ---------------------------------------------------------------------------
    # Builder
    # ---------------------------------------------------------------------------

    def build(self) -> str:
        """Serialise to an SDP string (CRLF-terminated lines)."""
        lines = [
            "v=0",
            f"o={self.origin_username} {self.session_id} {self.session_version} "
            f"{self.net_type} {self.addr_type} {self.unicast_addr}",
            f"s={self.session_name}",
            f"c={self.net_type} {self.addr_type} {self.media_ip}",
            "t=0 0",
            f"m=audio {self.rtp_port} RTP/AVP {self.payload_type}",
            f"a=rtpmap:{self.payload_type} {self.codec_name}/{self.clock_rate}",
        ]
        for attr in self.extra_attrs:
            lines.append(f"a={attr}")
        return "\r\n".join(lines) + "\r\n"

    # ---------------------------------------------------------------------------
    # Parser
    # ---------------------------------------------------------------------------

    @classmethod
    def parse(cls, sdp_text: str) -> "SdpDescription":
        """Parse an SDP string and return an :class:`SdpDescription`."""
        desc = cls()
        for line in sdp_text.splitlines():
            line = line.strip()
            if not line or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()

            if key == "o":
                parts = value.split()
                if len(parts) >= 6:
                    desc.origin_username = parts[0]
                    desc.session_id = parts[1]
                    desc.session_version = parts[2]
                    desc.net_type = parts[3]
                    desc.addr_type = parts[4]
                    desc.unicast_addr = parts[5]

            elif key == "s":
                desc.session_name = value

            elif key == "c":
                parts = value.split()
                if len(parts) < 3:
                    raise SdpError(f"Malformed c= line: {line!r}")
                try:
                    ipaddress.IPv4Address(parts[2])
                except ipaddress.AddressValueError as exc:
                    raise SdpError(f"Invalid IPv4 address in c= line: {parts[2]!r}") from exc
                desc.media_ip = parts[2]

            elif key == "m":
                parts = value.split()
                if len(parts) < 4:
                    raise SdpError(f"Malformed m= line: {line!r}")
                if parts[0] != "audio":
                    raise SdpError(f"Unsupported media type: {parts[0]!r}")
                try:
                    desc.rtp_port = int(parts[1])
                except ValueError as exc:
                    raise SdpError(f"Invalid RTP port: {parts[1]!r}") from exc
                if not 1 <= desc.rtp_port <= 65535:
                    raise SdpError(f"RTP port out of range: {desc.rtp_port}")
                try:
                    desc.payload_type = int(parts[3])
                except ValueError as exc:
                    raise SdpError(f"Invalid payload type: {parts[3]!r}") from exc
                if not 0 <= desc.payload_type <= 127:
                    raise SdpError(f"Payload type out of range: {desc.payload_type}")

            elif key == "a":
                if value.startswith("rtpmap:"):
                    rest = value[len("rtpmap:"):]
                    pt_str, _, codec_info = rest.partition(" ")
                    try:
                        desc.payload_type = int(pt_str)
                    except ValueError as exc:
                        raise SdpError(f"Invalid rtpmap payload type: {pt_str!r}") from exc
                    if not codec_info or "/" not in codec_info:
                        raise SdpError(f"Malformed rtpmap attribute: {value!r}")
                    codec_name, _, rate_str = codec_info.partition("/")
                    codec_name = codec_name.strip()
                    if not codec_name:
                        raise SdpError(f"Missing codec name in rtpmap: {value!r}")
                    desc.codec_name = codec_name
                    try:
                        desc.clock_rate = int(rate_str.strip())
                    except ValueError as exc:
                        raise SdpError(f"Invalid codec rate in rtpmap: {value!r}") from exc
                    if desc.clock_rate <= 0:
                        raise SdpError(f"Clock rate must be positive: {desc.clock_rate}")
                else:
                    desc.extra_attrs.append(value)

        return desc
