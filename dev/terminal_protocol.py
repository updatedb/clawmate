from __future__ import annotations

import json
import struct
from dataclasses import dataclass

PROTOCOL_VERSION = 2
HEADER = struct.Struct("!Q")
MAX_BINARY_PAYLOAD = 1024 * 1024
CONTROL_TYPES = {
    "hello",
    "focus",
    "resize",
    "output_ack",
    "input_ack",
    "file_context",
    "terminate",
    "new_session",
    "lock_input",
    "heartbeat",
    "heartbeat_ack",
}


@dataclass(slots=True)
class ProtocolError(Exception):
    code: str
    message: str
    fatal: bool = False

    def as_message(self, message_id: str = "") -> dict:
        return {
            "v": PROTOCOL_VERSION,
            "type": "error",
            "id": message_id,
            "error": {
                "code": self.code,
                "message": self.message,
                "fatal": self.fatal,
            },
        }


def encode_binary_frame(sequence: int, payload: bytes) -> bytes:
    if sequence < 0 or len(payload) > MAX_BINARY_PAYLOAD:
        raise ProtocolError("invalid_binary_frame", "Invalid sequence or oversized payload")
    return HEADER.pack(sequence) + payload


def decode_binary_frame(frame: bytes) -> tuple[int, bytes]:
    if len(frame) < HEADER.size or len(frame) - HEADER.size > MAX_BINARY_PAYLOAD:
        raise ProtocolError("invalid_binary_frame", "Invalid binary frame length")
    sequence = HEADER.unpack_from(frame)[0]
    return sequence, frame[HEADER.size:]


def parse_control(raw: str) -> dict:
    try:
        message = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProtocolError("invalid_json", "Control frame is not valid JSON") from exc
    if not isinstance(message, dict):
        raise ProtocolError("invalid_control", "Control frame must be an object")
    if message.get("v") != PROTOCOL_VERSION:
        raise ProtocolError("unsupported_protocol", "Protocol version 2 is required", True)
    if message.get("type") not in CONTROL_TYPES:
        raise ProtocolError("unknown_control", "Unknown control frame type")
    return message


def validate_dimensions(cols: object, rows: object) -> tuple[int, int]:
    if (
        not isinstance(cols, int)
        or not isinstance(rows, int)
        or not 2 <= cols <= 500
        or not 1 <= rows <= 200
    ):
        raise ProtocolError("invalid_dimensions", "Terminal dimensions are outside the supported range")
    return cols, rows
