"""Custom exceptions for the VoIP application."""


class VoIPError(Exception):
    """Base exception for all VoIP application errors."""


class SipError(VoIPError):
    """Raised when a SIP protocol error occurs."""


class SipParseError(SipError):
    """Raised when a SIP message cannot be parsed."""


class SdpError(VoIPError):
    """Raised when an SDP body is invalid or incompatible."""


class RtpError(VoIPError):
    """Raised when an RTP packet is invalid."""


class MediaError(VoIPError):
    """Raised when a media file cannot be loaded or processed."""


class NetworkError(VoIPError):
    """Raised when a network operation fails."""


class SessionError(VoIPError):
    """Raised when an illegal state transition or session issue occurs."""
