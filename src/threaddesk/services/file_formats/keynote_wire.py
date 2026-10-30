"""Bounded data-only IWA identity reader; no document rendering or execution.

IWA uses four-byte chunk headers, raw Snappy blocks and length-delimited
protobuf archive records. Only the small root identity fields are interpreted.
"""
from __future__ import annotations

from time import monotonic

MAX_PLAIN = 16 * 1024 * 1024
MAX_IWA = 4 * 1024 * 1024


class KeynoteError(ValueError):
    def __init__(self, code="keynote_invalid"):
        self.code = code
        super().__init__(code)


def _need(condition, code="keynote_invalid"):
    if not condition:
        raise KeynoteError(code)


def varint(data, position):
    result = 0
    for shift in range(0, 70, 7):
        _need(position < len(data))
        value = data[position]
        position += 1
        _need(shift < 63 or value <= 1)
        result |= (value & 127) << shift
        if value < 128:
            return result, position
    raise KeynoteError()


def fields(data, *, maximum=2048):
    result, position, count = {}, 0, 0
    while position < len(data):
        count += 1
        _need(count <= maximum, "keynote_limit")
        tag, position = varint(data, position)
        number, wire = tag >> 3, tag & 7
        _need(number > 0 and number <= (1 << 29) - 1)
        if wire == 0:
            value, position = varint(data, position)
        elif wire == 2:
            length, position = varint(data, position)
            _need(length <= len(data) - position)
            value = data[position:position + length]
            position += length
        elif wire in {1, 5}:
            size = 8 if wire == 1 else 4
            _need(size <= len(data) - position)
            value = data[position:position + size]
            position += size
        else:
            raise KeynoteError()
        result.setdefault(number, []).append((wire, value))
    return result


def one(values, number, wire):
    candidates = [value for kind, value in values.get(number, []) if kind == wire]
    _need(len(candidates) == 1)
    return candidates[0]


def _snappy(data, maximum, deadline):
    promised, position = varint(data, 0)
    _need(0 < promised <= maximum, "keynote_limit")
    output, count = bytearray(), 0
    while position < len(data):
        count += 1
        if count % 256 == 0:
            _need(monotonic() <= deadline, "keynote_limit")
        tag = data[position]
        position += 1
        kind = tag & 3
        if kind == 0:
            length = tag >> 2
            if length >= 60:
                size = length - 59
                _need(size <= len(data) - position)
                length = int.from_bytes(data[position:position + size], "little")
                position += size
            length += 1
            _need(length <= len(data) - position and len(output) + length <= promised)
            output.extend(data[position:position + length])
            position += length
        else:
            size = {1: 1, 2: 2, 3: 4}[kind]
            _need(size <= len(data) - position)
            offset = int.from_bytes(data[position:position + size], "little")
            position += size
            length = 4 + ((tag >> 2) & 7) if kind == 1 else (tag >> 2) + 1
            if kind == 1:
                offset += (tag & 224) << 3
            _need(0 < offset <= len(output) and len(output) + length <= promised)
            for _ in range(length):
                output.append(output[-offset])
    _need(len(output) == promised)
    return bytes(output)


def objects(body, *, deadline=None):
    _need(0 < len(body) <= MAX_IWA, "keynote_limit")
    deadline = deadline if deadline is not None else monotonic() + 1
    plain, position, chunks = bytearray(), 0, 0
    while position < len(body):
        chunks += 1
        _need(chunks <= 128 and monotonic() <= deadline, "keynote_limit")
        _need(position + 4 <= len(body) and body[position] == 0)
        length = int.from_bytes(body[position + 1:position + 4], "little")
        position += 4
        _need(0 < length <= len(body) - position)
        plain.extend(_snappy(body[position:position + length], MAX_PLAIN - len(plain), deadline))
        position += length
    position, count = 0, 0
    while position < len(plain):
        count += 1
        _need(count <= 4096 and monotonic() <= deadline, "keynote_limit")
        size, position = varint(plain, position)
        _need(0 < size <= 65536 and size <= len(plain) - position)
        header = fields(plain[position:position + size])
        position += size
        identifier = one(header, 1, 0)
        messages = [data for wire, data in header.get(2, []) if wire == 2]
        _need(messages)
        for message in messages:
            info = fields(message)
            kind, length = one(info, 1, 0), one(info, 3, 0)
            _need(length <= len(plain) - position)
            payload = bytes(plain[position:position + length])
            position += length
            yield identifier, kind, payload
