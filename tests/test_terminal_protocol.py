import json

import pytest

from dev.terminal_protocol import (
    ProtocolError,
    decode_binary_frame,
    encode_binary_frame,
    parse_control,
    validate_dimensions,
)


def test_binary_terminal_content_cannot_be_control_json():
    data = b'{"type":"terminate"}'
    frame = encode_binary_frame(7, data)
    assert decode_binary_frame(frame) == (7, data)


def test_control_requires_v2_and_known_type():
    assert parse_control(json.dumps({"v": 2, "type": "focus", "id": "m1"}))["type"] == "focus"
    with pytest.raises(ProtocolError) as exc:
        parse_control('{"v":1,"type":"focus"}')
    assert exc.value.code == "unsupported_protocol"


@pytest.mark.parametrize("cols,rows", [(1, 24), (80, 0), (501, 24), (80, 201)])
def test_dimensions_are_bounded(cols, rows):
    with pytest.raises(ProtocolError):
        validate_dimensions(cols, rows)
