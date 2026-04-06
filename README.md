# Real-Time Audio Streaming over IP

A Python-based two-endpoint VoIP demo that implements:

- **SIP signalling** (INVITE / 200 OK / ACK / BYE) over UDP
- **SDP negotiation** to exchange RTP endpoint details
- **One-way RTP audio streaming** from Client 1 to Client 2
- **Periodic RTCP Sender Reports** (~every 5 s)
- **Graceful call teardown** via BYE
- **Basic 4xx/5xx error handling**

---

## Table of contents

1. [Requirements](#requirements)
2. [Project structure](#project-structure)
3. [Quick start](#quick-start)
4. [Configuration](#configuration)
5. [Running on a LAN](#running-on-a-lan)
6. [Architecture overview](#architecture-overview)
7. [Protocol flow](#protocol-flow)
8. [Tests](#tests)
9. [Implemented features](#implemented-features)
10. [Sample outputs](#sample-outputs)

---

## Requirements

- Python 3.10 or later (tested on 3.12)
- `pytest` for tests: `pip install pytest`
- **Optional** - microphone capture and live playback: `pip install sounddevice numpy`

No other third-party packages are required; all protocol logic uses the Python standard library.

---

## Project structure

```
project/
├─ app/
│  ├─ config.py          # Shared configuration (ports, IPs, …)
│  ├─ main_client1.py    # Caller entry-point
│  └─ main_client2.py    # Callee entry-point
├─ core/
│  ├─ exceptions.py      # Custom exception hierarchy
│  ├─ log.py             # Structured logger factory
│  └─ timers.py          # Monotonic clock helpers for RTP pacing
├─ sip/
│  ├─ messages.py        # SIP message model + builder functions
│  ├─ parser.py          # SIP text parser
│  ├─ sdp.py             # SDP builder / parser
│  └─ session.py         # CallerSession / CalleeSession state machines
├─ rtp/
│  ├─ packet.py          # RTP fixed-header packer / unpacker
│  ├─ sender.py          # Paced RTP sender (one thread)
│  ├─ receiver.py        # Background RTP receive thread
│  ├─ rtcp.py            # RTCP Sender Report + periodic reporter thread
│  └─ jitter_buffer.py   # Optional reorder buffer
├─ media/
│  ├─ wav_reader.py      # WAV file loader / validator / frame iterator
│  ├─ packetizer.py      # Thin bridge between WAV reader and RTP sender
│  ├─ playback.py        # PCM playback sink (sounddevice or WAV file)
│  └─ codec.py           # Codec adapter placeholder (L16 / G.711 hook)
├─ net/
│  ├─ udp.py             # Blocking UDP socket adapter
│  └─ endpoints.py       # EndpointConfig dataclass
├─ tests/
│  ├─ test_sip.py        # SIP message builder tests
│  ├─ test_sip_parser.py # SIP parser tests
│  ├─ test_sdp.py        # SDP builder / parser tests
│  ├─ test_rtp.py        # RTP packet tests
│  ├─ test_rtcp.py       # RTCP packet tests
│  └─ test_integration.py# End-to-end SIP + RTP + RTCP tests
├─ assets/
│  └─ sample.wav         # 3 s mono 8 kHz 16-bit PCM sine wave
├─ conftest.py           # Pytest path setup
├─ pytest.ini            # Pytest configuration
└─ README.md
```

---

## Quick start

### 1 – Clone and navigate

```bash
git clone <repo-url>
cd Real-Time-Audio-Streaming-over-IP
```

### 2 - Create a local `.env`

```powershell
Copy-Item .env.example .env
```

The app loads `.env` automatically if it exists.

### 3 - Start Client 2 (callee/receiver) first

```bash
python -m app.main_client2
```

Client 2 binds `127.0.0.1:5061` (SIP) and `127.0.0.1:10002` (RTP) and waits
for an INVITE.

### 4 - Start Client 1 (caller/sender) in a second terminal

```bash
python -m app.main_client1
```

Client 1 sends a SIP INVITE, completes the handshake, streams
`assets/sample.wav` as RTP, sends RTCP Sender Reports every 5 s, then
terminates the call with BYE.

Received audio is saved to `received_audio.wav` by Client 2.

---

## Configuration

All settings live in `app/config.py` and can be overridden with environment
variables:

- The project includes `.env.example`, `.env.client1`, and `.env.client2`.
- Use `ENV_FILE=<path>` to load a specific profile file.
- If `ENV_FILE` is not set, `.env` is loaded automatically (when present).
- `PACKET_LOSS` is sender-side RTP drop simulation only (SIP and RTCP are unaffected).

| Variable | Default | Description |
|---|---|---|
| `ENV_FILE` | *(unset)* | Optional path to a specific env file to load first |
| `CLIENT1_IP` | `127.0.0.1` | Caller IP |
| `CLIENT2_IP` | `127.0.0.1` | Callee IP |
| `CLIENT1_SIP_PORT` | `5060` | Caller SIP port |
| `CLIENT2_SIP_PORT` | `5061` | Callee SIP port |
| `CLIENT1_RTP_PORT` | `10000` | Caller RTP port |
| `CLIENT2_RTP_PORT` | `10002` | Callee RTP port |
| `SAMPLE_WAV` | `assets/sample.wav` | Audio file to stream |
| `OUTPUT_WAV` | `received_audio.wav` | Where Client 2 saves received audio |
| `OUTPUT_WAV_CALLER` | `received_audio_client1.wav` | Where Client 1 saves received audio in two-way mode |
| `AUDIO_SOURCE` | `wav` | `wav` or `mic` |
| `MIC_DURATION_S` | `5.0` | Microphone capture duration (seconds) |
| `TWO_WAY_CALL` | `false` | Enables simultaneous uplink from Client 2 to Client 1 |
| `LIVE_PLAYBACK` | `false` | Enables sounddevice live playback (set `true` only if stable on your machine) |
| `RTCP_INTERVAL_S` | `5` | RTCP SR interval in seconds |
| `SIP_TIMEOUT_S` | `10` | SIP socket receive timeout |
| `PACKET_LOSS` | `0.00` | RTP sender packet loss probability (double) from `0.00` to `1.00`; blank/missing uses no loss |

---

## Running on a LAN

```bash
# Terminal on machine A (Client 1)
CLIENT1_IP=192.168.1.10 CLIENT2_IP=192.168.1.20 python -m app.main_client1

# Terminal on machine B (Client 2)
CLIENT2_IP=192.168.1.20 CLIENT1_IP=192.168.1.10 python -m app.main_client2
```

Ensure that no firewall blocks UDP on ports 5060, 5061, 10000–10003.

### Profile-based startup (recommended)

Use the included role-specific env files:

```powershell
# Terminal 1 (callee)
$env:ENV_FILE = ".env.client2"
python -m app.main_client2

# Terminal 2 (caller)
$env:ENV_FILE = ".env.client1"
python -m app.main_client1
```

### Bonus mode: microphone and two-way call

Install optional audio dependencies:

```powershell
pip install sounddevice numpy
```

One-way microphone (Client 1 mic -> Client 2) with env files:

```powershell
# Terminal 1 (callee)
$env:ENV_FILE = ".env.client2"
python -m app.main_client2

# Terminal 2 (caller)
$env:ENV_FILE = ".env.client1"
$env:AUDIO_SOURCE = "mic"
$env:MIC_DURATION_S = "8"
python -m app.main_client1
```

Two-way microphone call:

```powershell
# Terminal 1 (callee)
$env:ENV_FILE = ".env.client2"
$env:AUDIO_SOURCE = "mic"
$env:TWO_WAY_CALL = "true"
$env:MIC_DURATION_S = "8"
python -m app.main_client2

# Terminal 2 (caller)
$env:ENV_FILE = ".env.client1"
$env:AUDIO_SOURCE = "mic"
$env:TWO_WAY_CALL = "true"
$env:MIC_DURATION_S = "8"
python -m app.main_client1
```

Tip: if you prefer persistent settings, edit `.env.client1` and `.env.client2`
directly instead of overriding variables in the terminal.

---

## Architecture overview

```
Client 1 (Caller)                          Client 2 (Callee)
─────────────────                          ─────────────────
CallerSession ──SIP INVITE──────────────►  CalleeSession
              ◄──200 OK (SDP answer)───
              ──ACK──────────────────►
                  (call established)
RtpSender ────RTP audio─────────────────►  RtpReceiver → AudioPlaybackSink
RtcpReporter ─RTCP SR───────────────────►  (logged)
CallerSession ──BYE─────────────────────►  CalleeSession
              ◄──200 OK (BYE)──────────
```

### Runtime model

Each concern runs in its own thread:

| Thread | Role |
|---|---|
| Main | SIP handshake, BYE |
| `rtp-send` (implicit in sender loop) | RTP paced send |
| `rtcp-sr` | RTCP periodic Sender Report |
| `rtp-recv` | RTP background receive |
| `bye-watcher` | Monitors incoming BYE |
| `playback` | Writes frames to WAV / sounddevice |

---

## Protocol flow

### SIP handshake

```
Client 1 ──INVITE (+ SDP offer)──► Client 2
         ◄──100 Trying────────────  (optional)
         ◄──200 OK (+ SDP answer)─
         ──ACK───────────────────►
```

### SDP (exchanged in INVITE body and 200 OK body)

```
v=0
o=- 0 0 IN IP4 127.0.0.1
s=VoIP Demo
c=IN IP4 127.0.0.1
t=0 0
m=audio 10000 RTP/AVP 96
a=rtpmap:96 L16/8000
```

### RTP packet (12-byte fixed header)

| Field | Value |
|---|---|
| Version | 2 |
| Payload type | 96 (dynamic, L16 PCM) |
| Sequence number | increments by 1 per packet |
| Timestamp | increments by 160 per packet (8 kHz, 20 ms) |
| SSRC | random 32-bit value |

### RTCP Sender Report (sent every 5 s)

| Field | Value |
|---|---|
| Packet type | 200 (SR) |
| SSRC | same as RTP sender |
| NTP timestamp | current wall clock |
| Packet count | running total |
| Octet count | running total |

### Call teardown

```
Client 1 ──BYE──► Client 2
         ◄──200 OK (BYE)──
```

---

## Tests

```bash
pip install pytest
python -m pytest tests/ -v
```

Expected output: **132 tests, all passing**.

Test coverage includes:

- SIP message builder (all required headers, bodies, and round-trips)
- SIP parser (valid messages, malformed inputs, error cases)
- SDP builder and parser (all required fields, error cases, round-trips)
- RTP packet encode / decode (all header fields, marker bit, wrap-around)
- RTCP Sender Report encode / decode
- End-to-end SIP handshake (in-process threads, localhost)
- End-to-end RTP send + receive (in-process, localhost)
- RTCP reporter sends periodic SRs
- WAV reader validates PCM format and produces correct frame sizes

---

## Implemented features

- [x] SIP INVITE with SDP body
- [x] SIP 200 OK with SDP answer
- [x] SIP ACK
- [x] SIP BYE + 200 OK response
- [x] All required SIP headers (Via, From, To, Call-ID, CSeq, Contact, Max-Forwards, Content-Type, Content-Length)
- [x] SDP offer / answer exchange
- [x] Valid RTP packets (version, PT, sequence, timestamp, SSRC)
- [x] Real-time-paced RTP sending (20 ms frames, monotonic clock)
- [x] RTP reception and WAV output
- [x] Periodic RTCP Sender Reports (every 5 s by default)
- [x] Graceful BYE teardown
- [x] Clean socket and thread shutdown
- [x] Basic 4xx/5xx error handling (no crash)
- [x] Malformed packet tolerance (logged, not fatal)
- [x] Configurable ports and IPs via environment variables
- [x] Jitter buffer for mild out-of-order delivery
- [x] Codec adapter hook for future G.711 support
- [x] 132 passing unit and integration tests

---

## Sample outputs

### Client 1 (caller) log

```
01:00:00  app.client1           INFO      === Client 1 (Caller) starting ===
01:00:00  sip.session           INFO      [INVITE_SENT] INVITE sent  call-id=3f2a…
01:00:00  sip.session           INFO      Remote SDP: ip=127.0.0.1 rtp_port=10002 …
01:00:00  sip.session           INFO      [ESTABLISHED] ACK sent
01:00:00  rtp.rtcp              INFO      RTCP reporter started (interval=5.0 s)
01:00:00  rtp.sender            DEBUG     RTP sent  seq=12301  ts=981440  bytes=320  total_pkts=1
…
01:00:03  rtp.rtcp              INFO      RTCP SR sent  pkts=50  octets=16000  ntp_hi=3900012345
01:00:03  rtp.sender            INFO      RTP sender done: 150 packets / 48000 bytes sent
01:00:03  sip.session           INFO      [TERMINATING] BYE sent
01:00:03  sip.session           INFO      [TERMINATED]
01:00:03  app.client1           INFO      === Client 1 done ===
```

### Client 2 (callee) log

```
01:00:00  app.client2           INFO      === Client 2 (Callee) starting ===
01:00:00  sip.session           INFO      [IDLE] Waiting for INVITE…
01:00:00  sip.session           INFO      [INVITE_RECEIVED] From 127.0.0.1:5060
01:00:00  sip.session           INFO      [OK_SENT] 200 OK sent
01:00:00  sip.session           INFO      [ESTABLISHED] ACK received — session up
01:00:00  media.playback        INFO      Writing received audio to received_audio.wav
01:00:00  rtp.receiver          INFO      RTP receiver started (PT=96)
…
01:00:03  sip.session           INFO      [TERMINATING] BYE received — sending 200 OK
01:00:03  sip.session           INFO      [TERMINATED]
01:00:03  app.client2           INFO      === Client 2 done ===
```
