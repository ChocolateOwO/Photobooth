"""Builds a real ICC v2 matrix/TRC RGB profile (Adobe RGB (1998) primaries, D50-adapted, gamma
563/256) so colour-management tests do not depend on files installed on the machine."""

from __future__ import annotations

import struct


def _s15f16(value: float) -> bytes:
    return struct.pack(">i", round(value * 65536))


def _pad(data: bytes) -> bytes:
    return data + b"\0" * (-len(data) % 4)


def _xyz(x: float, y: float, z: float) -> bytes:
    return b"XYZ \0\0\0\0" + _s15f16(x) + _s15f16(y) + _s15f16(z)


def _curve(gamma: float) -> bytes:
    return _pad(b"curv\0\0\0\0" + struct.pack(">I", 1) + struct.pack(">H", round(gamma * 256)))


def _desc(text: str) -> bytes:
    ascii_text = text.encode("ascii") + b"\0"
    body = b"desc\0\0\0\0" + struct.pack(">I", len(ascii_text)) + ascii_text
    body += struct.pack(">II", 0, 0)  # unicode language code + count
    body += struct.pack(">HB", 0, 0) + b"\0" * 67  # scriptcode code + count + 67 bytes
    return _pad(body)


def _text(text: str) -> bytes:
    return _pad(b"text\0\0\0\0" + text.encode("ascii") + b"\0")


def adobe_rgb_profile() -> bytes:
    tags = [
        (b"desc", _desc("Test Adobe RGB compatible")),
        (b"cprt", _text("test fixture")),
        (b"wtpt", _xyz(0.9642, 1.0, 0.8249)),
        (b"rXYZ", _xyz(0.6097, 0.3111, 0.0195)),
        (b"gXYZ", _xyz(0.2053, 0.6257, 0.0609)),
        (b"bXYZ", _xyz(0.1492, 0.0632, 0.7446)),
        (b"rTRC", _curve(563 / 256)),
        (b"gTRC", _curve(563 / 256)),
        (b"bTRC", _curve(563 / 256)),
    ]
    table_size = 4 + 12 * len(tags)
    offset = 128 + table_size
    table = struct.pack(">I", len(tags))
    data = b""
    for signature, body in tags:
        table += signature + struct.pack(">II", offset + len(data), len(body))
        data += body
    total = 128 + table_size + len(data)
    header = struct.pack(">I", total)
    header += b"\0\0\0\0"  # preferred CMM
    header += struct.pack(">I", 0x02100000)  # version 2.1
    header += b"mntr" + b"RGB " + b"XYZ "
    header += b"\0" * 12  # date/time
    header += b"acsp" + b"\0\0\0\0" + b"\0\0\0\0" + b"\0\0\0\0" + b"\0\0\0\0"
    header += b"\0" * 8  # device attributes
    header += struct.pack(">I", 0)  # rendering intent
    header += _s15f16(0.9642) + _s15f16(1.0) + _s15f16(0.8249)  # D50 illuminant
    header += b"\0\0\0\0"  # creator
    header += b"\0" * (128 - len(header))
    return header + table + data
