# NSCOM01 MP2 Compliance Checklist

Project: **Real-Time Audio Streaming over IP**  
Course: **NSCOM01 – MCO2 (Term 2, AY 2025-2026)**

## Instructions

- Mark each item during final verification/demo.
- Status guide:
  - `[x]` = complete and verified
  - `[~]` = partial / needs confirmation
  - `[ ]` = not complete

## A. SIP Signaling (UDP)

- [x] Client 1 sends **INVITE**
- [x] Client 2 sends **200 OK**
- [x] Client 1 sends **ACK**
- [x] SIP messages include required headers:
  - [x] `Via`
  - [x] `From`
  - [x] `To`
  - [x] `Call-ID`
  - [x] `CSeq`
  - [x] `Contact`
  - [x] `Max-Forwards`
  - [x] `Content-Type`
  - [x] `Content-Length`

## B. SDP Negotiation

- [x] INVITE includes SDP offer body
- [x] 200 OK includes SDP answer body
- [x] SDP parser extracts remote RTP IP/port
- [x] SDP parser extracts payload/codec info

## C. RTP Media (UDP)

- [x] Client 1 reads local audio file (`.wav`)
- [x] Audio is packetized into frames
- [x] RTP packets include valid header fields:
  - [x] Version 2
  - [x] Payload Type
  - [x] Sequence Number (increments)
  - [x] Timestamp (increments by frame samples)
  - [x] SSRC
- [x] RTP frames sent at real-time pace (near 20 ms frame interval)

## D. RTP Receiving and Playback

- [x] Client 2 receives RTP packets reliably
- [x] Client 2 validates payload type/stream identity
- [x] Client 2 outputs received audio correctly:
  - [x] WAV output file (`received_audio.wav`)
  - [x] Optional live playback if audio libs are installed

## E. RTCP

- [x] Periodic RTCP Sender Reports are sent
- [x] RTCP packet includes:
  - [x] SSRC
  - [x] NTP timestamp
  - [x] RTP timestamp
  - [x] Packet count
  - [x] Octet count
- [x] RTCP interval configurable

## F. Call Teardown and Resource Cleanup

- [x] Client 1 sends **BYE** at end of session
- [x] Client 2 responds with **200 OK** to BYE
- [x] Session transitions to terminated state cleanly
- [x] Sockets are closed
- [x] Background threads are stopped/joined

## G. Basic Error Handling

- [x] Handles SIP 4xx/5xx gracefully (logs and exits safely)
- [x] Ignores malformed/unexpected SIP packets without crashing
- [x] Ignores malformed/unexpected RTP packets without crashing
- [x] Handles socket/timeouts safely

## H. Project Constraints / Notes

- [x] Direct client-to-client communication (no SIP proxy required)
- [x] No registration/registrar required
- [x] Works in localhost/LAN setup assumptions

## I. Documentation and Testing

- [x] README includes compile/run instructions
- [x] README includes implemented feature description
- [x] README includes sample outputs/logs
- [x] Test suite exists for SIP/SDP/RTP/RTCP/integration
- [x] Latest local test result: **132 passed**

## J. Deliverables Checklist (Submission Day)

- [ ] Source code ZIP prepared
- [ ] README included in ZIP
- [ ] Demo script / walkthrough prepared
- [ ] Two-terminal demo ready (Client 2 first, then Client 1)
- [ ] Audio sample file included and accessible
- [ ] Backup copy prepared (cloud/USB)

## K. Bonus (Optional)

- [ ] Real-time microphone capture (one-way)
- [ ] Two-way microphone communication

## Final Compliance Verdict

- **Required specification compliance:** **PASS (full)**
- **Bonus features:** optional / not required for base compliance
