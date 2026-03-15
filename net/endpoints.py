"""Endpoint configuration data classes."""

from dataclasses import dataclass


@dataclass
class EndpointConfig:
    """Network address and port tuple for a single role (SIP, RTP, or RTCP)."""

    ip: str
    port: int

    def __str__(self) -> str:
        return f"{self.ip}:{self.port}"
