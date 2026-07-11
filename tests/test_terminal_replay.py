from dev.terminal_replay import ReplayRing


def test_replay_is_byte_bounded_and_slices_first_chunk():
    ring = ReplayRing(max_bytes=6)
    ring.append(b"abcd")
    ring.append(b"efgh")
    replay = ring.after(5)
    assert replay.gap is False
    assert b"".join(chunk.data for chunk in replay.chunks) == b"fgh"
    assert ring.retained_bytes <= 6


def test_replay_reports_gap():
    ring = ReplayRing(max_bytes=4)
    ring.append(b"abcd")
    ring.append(b"efgh")
    replay = ring.after(0)
    assert replay.gap is True
    assert replay.earliest_sequence == 4
