#!/usr/bin/env python3
"""Inspect basic facts from local PNG, JPEG, and WebP image assets."""

import argparse
import dataclasses
import hashlib
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import zlib


@dataclasses.dataclass(frozen=True)
class AssetFacts:
    alpha: bool | None
    byte_size: int
    format: str
    height: int
    sha256: str
    width: int


class StringSink:
    def __init__(self):
        self.value = ""

    def write(self, text):
        self.value += text


def make_png(width, height, color_type, trns=False, trns_payload=None, before_trns=(), after_trns=()):
    def chunk(kind, payload):
        body = kind + payload
        return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0)
    chunks = [chunk(b"IHDR", ihdr)]
    chunks.extend(chunk(kind, payload) for kind, payload in before_trns)
    if trns:
        transparency = trns_payload if trns_payload is not None else (b"\0\0\0\0\0\0" if color_type == 2 else b"\0\0")
        chunks.append(chunk(b"tRNS", transparency))
    chunks.extend(chunk(kind, payload) for kind, payload in after_trns)
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(color_type, 1)
    raw_scanlines = b"".join(b"\0" + b"\0" * (width * channels) for _ in range(height))
    adler_s1 = 1
    adler_s2 = 0
    for value in raw_scanlines:
        adler_s1 = (adler_s1 + value) % 65521
        adler_s2 = (adler_s2 + adler_s1) % 65521
    compressed = (
        b"\x78\x01\x01"
        + struct.pack("<H", len(raw_scanlines))
        + struct.pack("<H", 0xFFFF - len(raw_scanlines))
        + raw_scanlines
        + struct.pack(">I", (adler_s2 << 16) | adler_s1)
    )
    chunks.append(chunk(b"IDAT", compressed))
    chunks.append(chunk(b"IEND", b""))
    return b"\x89PNG\r\n\x1a\n" + b"".join(chunks)


def make_png_with_idat(width, height, color_type, compressed):
    def chunk(kind, payload):
        body = kind + payload
        return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + b"".join(
        (chunk(b"IHDR", ihdr), chunk(b"IDAT", compressed), chunk(b"IEND", b""))
    )


def make_jpeg(width, height):
    if (width, height) != (1, 1):
        raise ValueError("self-test JPEG fixture is fixed at 1x1")
    return bytes.fromhex("ffd8ffe000104a46494600010100000100010000ffdb0043000302020302020303030304030304050805050404050a070706080c0a0c0c0b0a0b0b0d0e12100d0e110e0b0b1016101113141515150c0f171816141812141514ffdb00430103040405040509050509140d0b0d1414141414141414141414141414141414141414141414141414141414141414141414141414141414141414141414141414ffc00011080001000103012200021101031101ffc4001500010100000000000000000000000000000008ffc40014100100000000000000000000000000000000ffc4001501010100000000000000000000000000000709ffc40014110100000000000000000000000000000000ffda000c03010002110311003f009d00062a9bffd9")


def make_webp_vp8x(width, height, alpha, extra_payload=b""):
    flags = 0x10 if alpha else 0
    payload = bytes([flags, 0, 0, 0]) + (width - 1).to_bytes(3, "little") + (height - 1).to_bytes(3, "little") + extra_payload
    padding = b"\0" if len(payload) % 2 else b""
    body = b"WEBPVP8X" + struct.pack("<I", len(payload)) + payload + padding
    return b"RIFF" + struct.pack("<I", len(body)) + body


def make_webp_vp8(width, height):
    if (width, height) != (1, 1):
        raise ValueError("self-test VP8 fixture is fixed at 1x1")
    return bytes.fromhex("524946463c000000574542505650382030000000d001009d012a0100010002003425a00274ba01f80003b000fef0c40bff20b96175c8d7ff203fe407fc80fff8f2000000")


def make_webp_vp8l(width, height):
    if (width, height) != (1, 1):
        raise ValueError("self-test VP8L fixture is fixed at 1x1")
    return bytes.fromhex("524946461e000000574542505650384c110000002f0000000007d0fffef7bfff8188e87f0000")


def make_webp_extended_vp8(width, height, alpha):
    if (width, height) != (1, 1):
        raise ValueError("self-test extended WebP fixture is fixed at 1x1")
    vp8l_chunk = make_webp_vp8l(1, 1)[12:]
    vp8x_payload = bytes([0x10 if alpha else 0, 0, 0, 0]) + b"\0\0\0\0\0\0"
    vp8x_chunk = b"VP8X" + struct.pack("<I", len(vp8x_payload)) + vp8x_payload
    body = b"WEBP" + vp8x_chunk + vp8l_chunk
    return b"RIFF" + struct.pack("<I", len(body)) + body


class AssetInspectorTests(unittest.TestCase):
    def test_png_fixture_has_valid_chunk_crcs(self):
        data = make_png(width=3, height=2, color_type=6)
        offset = 8
        while offset < len(data):
            length = struct.unpack(">I", data[offset:offset + 4])[0]
            chunk = data[offset + 4:offset + 8 + length]
            actual = struct.unpack(">I", data[offset + 8 + length:offset + 12 + length])[0]
            self.assertEqual(actual, zlib.crc32(chunk) & 0xFFFFFFFF)
            offset += 12 + length

    def test_png_reports_dimensions_and_alpha(self):
        data = make_png(width=3, height=2, color_type=6)
        self.assertIn(b"IDAT", data)
        self.assertEqual(parse_png(data), (3, 2, True))

    def test_png_trns_reports_alpha(self):
        self.assertEqual(parse_png(make_png(3, 2, color_type=2, trns=True)), (3, 2, True))

    def test_palette_png_trns_requires_valid_preceding_palette(self):
        palette = b"\0\0\0\xff\xff\xff"
        self.assertEqual(
            parse_png(make_png(3, 2, color_type=3, trns=True, trns_payload=b"\0\xff", before_trns=[(b"PLTE", palette)])),
            (3, 2, True),
        )
        with self.assertRaises(ValueError):
            parse_png(make_png(3, 2, color_type=3, trns=True, trns_payload=b"\0"))
        with self.assertRaises(ValueError):
            parse_png(make_png(3, 2, color_type=3, trns=True, trns_payload=b"\0", after_trns=[(b"PLTE", palette)]))
        with self.assertRaises(ValueError):
            parse_png(make_png(3, 2, color_type=3, trns=True, trns_payload=b"\0\xff\x80", before_trns=[(b"PLTE", palette)]))
        with self.assertRaises(ValueError):
            parse_png(make_png(3, 2, color_type=3, trns=True, trns_payload=b"\0", before_trns=[(b"PLTE", b"\0\0\0\xff")]))

    def test_jpeg_reports_dimensions_without_alpha(self):
        data = make_jpeg(width=1, height=1)
        self.assertEqual(parse_jpeg(data), (1, 1, False))

    def test_jpeg_requires_scan_and_eoi_after_sof(self):
        data = make_jpeg(width=1, height=1)
        self.assertEqual(parse_jpeg(data), (1, 1, False))
        with self.assertRaisesRegex(ValueError, "JPEG scan"):
            parse_jpeg(data[:-2])

    def test_webp_vp8x_reports_dimensions_and_alpha_flag(self):
        data = make_webp_extended_vp8(width=1, height=1, alpha=True)
        self.assertEqual(parse_webp(data), (1, 1, True))

    def test_webp_vp8x_without_alpha_is_false(self):
        self.assertEqual(parse_webp(make_webp_extended_vp8(1, 1, alpha=False)), (1, 1, False))

    def test_webp_vp8x_requires_image_data_and_precedes_it(self):
        with self.assertRaisesRegex(ValueError, "image data"):
            parse_webp(make_webp_vp8x(1, 1, alpha=False))
        valid = make_webp_extended_vp8(1, 1, alpha=False)
        vp8x = valid[12:30]
        vp8 = valid[30:]
        reordered_body = b"WEBP" + vp8 + vp8x
        reordered = b"RIFF" + struct.pack("<I", len(reordered_body)) + reordered_body
        with self.assertRaisesRegex(ValueError, "VP8X"):
            parse_webp(reordered)

    def test_webp_vp8_reports_dimensions_without_alpha(self):
        self.assertEqual(parse_webp(make_webp_vp8(1, 1)), (1, 1, False))

    def test_webp_vp8l_reports_dimensions_with_unknown_alpha(self):
        self.assertEqual(parse_webp(make_webp_vp8l(1, 1)), (1, 1, None))

    def test_unsupported_input_is_an_explicit_error(self):
        with self.assertRaisesRegex(ValueError, "unsupported image format"):
            inspect_bytes(b"not-an-image")

    def test_truncated_or_malformed_png_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_png(b"\x89PNG\r\n\x1a\n")
        with self.assertRaises(ValueError):
            parse_png(make_png(0, 2, color_type=6))
        with self.assertRaises(ValueError):
            parse_png(make_png(3, 2, color_type=2, trns=True, trns_payload=b"\0"))

    def test_png_without_iend_is_rejected(self):
        valid = make_png(3, 2, color_type=6)
        self.assertEqual(parse_png(valid), (3, 2, True))
        with self.assertRaisesRegex(ValueError, "missing PNG IEND"):
            parse_png(valid[:-12])

    def test_png_without_idat_is_rejected(self):
        valid = make_png(3, 2, color_type=6)
        idat_offset = valid.index(b"IDAT") - 4
        idat_length = struct.unpack(">I", valid[idat_offset:idat_offset + 4])[0]
        missing_idat = valid[:idat_offset] + valid[idat_offset + 12 + idat_length:]
        with self.assertRaisesRegex(ValueError, "missing PNG IDAT"):
            parse_png(missing_idat)

    def test_png_rejects_oversized_or_dimension_mismatched_decoded_data(self):
        oversized = make_png_with_idat(1, 1, 6, zlib.compress(b"\0" * 10_000_000))
        with self.assertRaisesRegex(ValueError, "PNG image data size mismatch"):
            parse_png(oversized)
        declared_too_large = make_png_with_idat(10_000, 10_000, 6, zlib.compress(b""))
        with self.assertRaisesRegex(ValueError, "PNG image data exceeds"):
            parse_png(declared_too_large)
        mismatched = make_png_with_idat(1, 1, 6, zlib.compress(b"\0" * 6))
        with self.assertRaisesRegex(ValueError, "PNG image data size mismatch"):
            parse_png(mismatched)

    def test_truncated_or_malformed_jpeg_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_jpeg(b"\xff\xd8\xff\xc0\x00")
        with self.assertRaises(ValueError):
            parse_jpeg(b"\xff\xd8\xff\xc0\x00\x08\x08\x00\x00\x00\x05\x01\x01\x11\x00")

    def test_truncated_or_malformed_webp_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_webp(b"RIFF\x04\0\0\0WEBP")
        with self.assertRaises(ValueError):
            parse_webp(b"RIFF\xff\xff\xff\xffWEBPVP8X\x00\0\0\0")
        with self.assertRaises(ValueError):
            parse_webp(make_webp_vp8x(1, 1, alpha=False)[:-1])
        with self.assertRaises(ValueError):
            parse_webp(make_webp_vp8x(1, 1, alpha=False, extra_payload=b"\0"))

    def test_inspect_file_reports_hash_and_byte_size(self):
        data = make_png(3, 2, color_type=6)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "asset.png"
            path.write_bytes(data)
            facts = inspect_file(path)
        self.assertEqual(facts.byte_size, len(data))
        self.assertEqual(facts.sha256, hashlib.sha256(data).hexdigest())
        self.assertEqual(facts.format, "png")

    def test_missing_file_cli_exits_one_with_error_json(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing.png"
            stdout = StringSink()
            stderr = StringSink()
            result = main([str(missing)], output_stream=stdout, error_stream=stderr)
        self.assertEqual(result, 1)
        self.assertEqual(stdout.value, "")
        self.assertEqual(
            stderr.value,
            json.dumps({"error": "No such file or directory", "path": str(missing)}, sort_keys=True) + "\n",
        )

    def test_malformed_and_unsupported_cli_errors_use_stderr_only(self):
        with tempfile.TemporaryDirectory() as directory:
            malformed = Path(directory) / "broken.png"
            unsupported = Path(directory) / "note.txt"
            malformed.write_bytes(b"\x89PNG\r\n\x1a\n")
            unsupported.write_bytes(b"not-an-image")
            for path in (malformed, unsupported):
                with self.subTest(path=path):
                    stdout = StringSink()
                    stderr = StringSink()
                    self.assertEqual(main([str(path)], output_stream=stdout, error_stream=stderr), 1)
                    self.assertEqual(stdout.value, "")
                    self.assertIn('"error"', stderr.value)

    def test_output_file_equals_sorted_success_json(self):
        data = make_png(3, 2, color_type=6)
        expected = json.dumps(
            {
                "alpha": True,
                "byte_size": len(data),
                "format": "png",
                "height": 2,
                "sha256": hashlib.sha256(data).hexdigest(),
                "width": 3,
            },
            sort_keys=True,
        ) + "\n"
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "asset.png"
            output_path = Path(directory) / "facts.json"
            input_path.write_bytes(data)
            self.assertEqual(main([str(input_path), "--output", str(output_path)]), 0)
            self.assertEqual(output_path.read_text(), expected)

    def test_output_write_error_cli_exits_one_with_error_json(self):
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "asset.png"
            input_path.write_bytes(make_png(3, 2, color_type=6))
            stdout = StringSink()
            stderr = StringSink()
            result = main([str(input_path), "--output", directory], output_stream=stdout, error_stream=stderr)
        self.assertEqual(result, 1)
        self.assertEqual(stdout.value, "")
        self.assertEqual(
            stderr.value,
            json.dumps({"error": "Is a directory", "path": str(input_path)}, sort_keys=True) + "\n",
        )


def run_self_tests():
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(AssetInspectorTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


def _require_dimensions(width, height):
    if width == 0 or height == 0:
        raise ValueError("image dimensions must be non-zero")
    return width, height


MAX_PNG_DECODED_BYTES = 64 * 1024 * 1024
PNG_BIT_DEPTHS = {
    0: {1, 2, 4, 8, 16},
    2: {8, 16},
    3: {1, 2, 4, 8},
    4: {8, 16},
    6: {8, 16},
}
PNG_CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}
ADAM7_PASSES = (
    (0, 0, 8, 8),
    (4, 0, 8, 8),
    (0, 4, 4, 8),
    (2, 0, 4, 4),
    (0, 2, 2, 4),
    (1, 0, 2, 2),
    (0, 1, 1, 2),
)


def _png_row_bytes(width, bit_depth, color_type):
    return (width * PNG_CHANNELS[color_type] * bit_depth + 7) // 8


def _png_decoded_byte_count(width, height, bit_depth, color_type, interlace):
    if interlace == 0:
        return height * (1 + _png_row_bytes(width, bit_depth, color_type))
    total = 0
    for start_x, start_y, step_x, step_y in ADAM7_PASSES:
        pass_width = max(0, (width - start_x + step_x - 1) // step_x)
        pass_height = max(0, (height - start_y + step_y - 1) // step_y)
        if pass_width and pass_height:
            total += pass_height * (1 + _png_row_bytes(pass_width, bit_depth, color_type))
    return total


def _decode_png_idat(image_data, expected_size):
    decompressor = zlib.decompressobj()
    decoded_size = 0
    for chunk in image_data:
        if decompressor.eof:
            raise ValueError("invalid PNG image data")
        try:
            decoded = decompressor.decompress(chunk, expected_size - decoded_size + 1)
        except zlib.error as error:
            raise ValueError("invalid PNG image data") from error
        decoded_size += len(decoded)
        if decoded_size > expected_size or decompressor.unconsumed_tail:
            raise ValueError("PNG image data size mismatch")
        if decompressor.unused_data:
            raise ValueError("invalid PNG image data")
    if not decompressor.eof:
        raise ValueError("invalid PNG image data")
    if decoded_size != expected_size:
        raise ValueError("PNG image data size mismatch")


def parse_png(data):
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("invalid PNG signature")
    if len(data) < 33:
        raise ValueError("truncated PNG IHDR")

    length = struct.unpack(">I", data[8:12])[0]
    if data[12:16] != b"IHDR" or length != 13:
        raise ValueError("invalid PNG IHDR")
    chunk_end = 16 + length
    if chunk_end + 4 > len(data):
        raise ValueError("truncated PNG IHDR")

    width, height, bit_depth, color_type, compression, filtering, interlace = struct.unpack(
        ">IIBBBBB", data[16:29]
    )
    _require_dimensions(width, height)
    if color_type not in PNG_BIT_DEPTHS or compression != 0 or filtering != 0 or interlace not in (0, 1):
        raise ValueError("invalid PNG IHDR")
    if bit_depth not in PNG_BIT_DEPTHS[color_type]:
        raise ValueError("invalid PNG bit depth")
    expected_decoded_size = _png_decoded_byte_count(width, height, bit_depth, color_type, interlace)
    if expected_decoded_size > MAX_PNG_DECODED_BYTES:
        raise ValueError("PNG image data exceeds 64 MiB limit")

    alpha = color_type in (4, 6)
    seen_image_data = False
    seen_trns = False
    seen_iend = False
    palette_entries = None
    image_data: list[bytes] = []
    offset = chunk_end + 4
    while offset < len(data):
        if offset + 8 > len(data):
            raise ValueError("truncated PNG chunk")
        chunk_length = struct.unpack(">I", data[offset:offset + 4])[0]
        chunk_type = data[offset + 4:offset + 8]
        payload_start = offset + 8
        payload_end = payload_start + chunk_length
        if payload_end + 4 > len(data):
            raise ValueError("truncated PNG chunk")
        chunk_payload = data[payload_start:payload_end]
        actual_crc = struct.unpack(">I", data[payload_end:payload_end + 4])[0]
        expected_crc = zlib.crc32(chunk_type + chunk_payload) & 0xFFFFFFFF
        if actual_crc != expected_crc:
            raise ValueError("invalid PNG chunk CRC")
        if chunk_type == b"IDAT":
            seen_image_data = True
            image_data.append(chunk_payload)
        elif chunk_type == b"PLTE" and color_type == 3:
            if seen_image_data or seen_trns or palette_entries is not None or chunk_length == 0 or chunk_length > 768 or chunk_length % 3:
                raise ValueError("invalid PNG PLTE chunk")
            palette_entries = chunk_length // 3
        elif chunk_type == b"tRNS":
            valid_trns = (
                (color_type == 0 and chunk_length == 2)
                or (color_type == 2 and chunk_length == 6)
                or (color_type == 3 and palette_entries is not None and 1 <= chunk_length <= palette_entries)
            )
            if seen_image_data or seen_trns or not valid_trns:
                raise ValueError("invalid PNG tRNS chunk")
            seen_trns = True
            alpha = True
        elif chunk_type == b"IEND":
            if chunk_length != 0 or payload_end + 4 != len(data):
                raise ValueError("invalid PNG IEND chunk")
            if not seen_image_data:
                raise ValueError("missing PNG IDAT")
            seen_iend = True
            break
        offset = payload_end + 4
    if not seen_iend:
        raise ValueError("missing PNG IEND")
    _decode_png_idat(image_data, expected_decoded_size)
    return width, height, alpha


def parse_jpeg(data):
    if not data.startswith(b"\xff\xd8"):
        raise ValueError("invalid JPEG SOI")
    offset = 2
    sof_markers = set(range(0xC0, 0xC4)) | set(range(0xC5, 0xC8)) | set(range(0xC9, 0xCC)) | set(range(0xCD, 0xD0))
    standalone_markers = {0x01, 0xD8, 0xD9} | set(range(0xD0, 0xD8))
    dimensions = None
    while offset < len(data):
        if data[offset] != 0xFF:
            raise ValueError("invalid JPEG marker")
        while offset < len(data) and data[offset] == 0xFF:
            offset += 1
        if offset >= len(data):
            raise ValueError("truncated JPEG marker")
        marker = data[offset]
        offset += 1
        if marker == 0x00:
            raise ValueError("invalid JPEG marker")
        if marker in standalone_markers:
            if marker == 0xD9:
                raise ValueError("missing JPEG scan or EOI")
            continue
        if offset + 2 > len(data):
            raise ValueError("truncated JPEG segment")
        segment_length = struct.unpack(">H", data[offset:offset + 2])[0]
        if segment_length < 2 or offset + segment_length > len(data):
            raise ValueError("invalid JPEG segment length")
        if marker in sof_markers:
            if segment_length < 8:
                raise ValueError("truncated JPEG SOF")
            height, width = struct.unpack(">HH", data[offset + 3:offset + 7])
            components = data[offset + 7]
            if components == 0 or segment_length < 8 + 3 * components:
                raise ValueError("invalid JPEG SOF")
            _require_dimensions(width, height)
            dimensions = (width, height, False)
        if marker == 0xDA:
            if dimensions is None:
                raise ValueError("JPEG SOS before SOF")
            scan_start = offset + segment_length
            if scan_start >= len(data) - 2 or data[-2:] != b"\xff\xd9":
                raise ValueError("missing JPEG scan or EOI")
            scan = data[scan_start:-2]
            if not scan:
                raise ValueError("missing JPEG scan or EOI")
            return dimensions
        offset += segment_length
    if dimensions is not None:
        raise ValueError("missing JPEG scan or EOI")
    raise ValueError("JPEG SOF marker not found")


def parse_webp(data):
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        raise ValueError("invalid WebP RIFF header")
    declared_size = struct.unpack("<I", data[4:8])[0]
    riff_end = declared_size + 8
    if declared_size < 4 or riff_end != len(data):
        raise ValueError("truncated WebP RIFF")

    offset = 12
    vp8x = None
    image = None
    previous_rank = 0
    while offset < riff_end:
        if offset + 8 > riff_end:
            raise ValueError("truncated WebP chunk")
        chunk_type = data[offset:offset + 4]
        chunk_length = struct.unpack("<I", data[offset + 4:offset + 8])[0]
        payload_start = offset + 8
        payload_end = payload_start + chunk_length
        padded_end = payload_end + (chunk_length % 2)
        if padded_end > riff_end:
            raise ValueError("truncated WebP chunk")
        if chunk_length % 2 and data[payload_end] != 0:
            raise ValueError("invalid WebP chunk padding")
        payload = data[payload_start:payload_end]
        if chunk_type == b"VP8X":
            if vp8x is not None or image is not None or offset != 12:
                raise ValueError("invalid WebP VP8X ordering")
            if len(payload) != 10 or payload[1:4] != b"\0\0\0" or payload[0] & 0xC1:
                raise ValueError("invalid WebP VP8X header")
            vp8x = payload
        elif chunk_type in (b"VP8 ", b"VP8L"):
            if image is not None:
                raise ValueError("multiple WebP image chunks")
            if vp8x is not None and previous_rank > 3:
                raise ValueError("invalid WebP image ordering")
            image = (chunk_type, payload)
            previous_rank = 3
        elif vp8x is not None:
            ranks = {b"ICCP": 1, b"ALPH": 2, b"EXIF": 4, b"XMP ": 5}
            rank = ranks.get(chunk_type)
            if rank is not None:
                if rank < previous_rank:
                    raise ValueError("invalid WebP extended chunk ordering")
                previous_rank = rank
        offset = padded_end
    if offset != riff_end:
        raise ValueError("invalid WebP chunk layout")
    if image is None and vp8x is not None:
        raise ValueError("missing WebP image data")
    if image is None:
        raise ValueError("unsupported WebP primary chunk")

    chunk_type, payload = image
    if chunk_type == b"VP8 ":
        if len(payload) <= 10 or payload[3:6] != b"\x9d\x01\x2a":
            raise ValueError("invalid WebP VP8 header")
        width = struct.unpack("<H", payload[6:8])[0] & 0x3FFF
        height = struct.unpack("<H", payload[8:10])[0] & 0x3FFF
        _require_dimensions(width, height)
        alpha = False
    elif len(payload) <= 5 or payload[0] != 0x2F:
        raise ValueError("invalid WebP VP8L header")
    else:
        packed = int.from_bytes(payload[1:5], "little")
        width = (packed & 0x3FFF) + 1
        height = ((packed >> 14) & 0x3FFF) + 1
        _require_dimensions(width, height)
        alpha = None
    if vp8x is None:
        return width, height, alpha
    canvas_width = int.from_bytes(vp8x[4:7], "little") + 1
    canvas_height = int.from_bytes(vp8x[7:10], "little") + 1
    _require_dimensions(canvas_width, canvas_height)
    if (canvas_width, canvas_height) != (width, height):
        raise ValueError("WebP VP8X canvas does not match image data")
    return canvas_width, canvas_height, bool(vp8x[0] & 0x10)


def inspect_bytes(data):
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        image_format = "png"
        width, height, alpha = parse_png(data)
    elif data.startswith(b"\xff\xd8"):
        image_format = "jpeg"
        width, height, alpha = parse_jpeg(data)
    elif data.startswith(b"RIFF") and len(data) >= 12 and data[8:12] == b"WEBP":
        image_format = "webp"
        width, height, alpha = parse_webp(data)
    else:
        raise ValueError("unsupported image format")
    return AssetFacts(
        alpha=alpha,
        byte_size=len(data),
        format=image_format,
        height=height,
        sha256=hashlib.sha256(data).hexdigest(),
        width=width,
    )


def inspect_file(path):
    return inspect_bytes(Path(path).read_bytes())


def _write_json(value, output_stream):
    output_stream.write(json.dumps(value, sort_keys=True) + "\n")


def main(argv=None, output_stream=None, error_stream=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("path", nargs="?")
    parser.add_argument("--output")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        return run_self_tests()
    if not args.path:
        parser.error("path is required unless --self-test is used")
    output_stream = output_stream or sys.stdout
    error_stream = error_stream or sys.stderr
    try:
        facts = inspect_file(args.path)
    except (OSError, ValueError) as error:
        message = error.strerror if isinstance(error, OSError) and error.strerror else str(error)
        _write_json({"error": message, "path": args.path}, error_stream)
        return 1
    rendered = json.dumps(dataclasses.asdict(facts), sort_keys=True) + "\n"
    if args.output:
        try:
            Path(args.output).write_text(rendered)
        except OSError as error:
            message = error.strerror if error.strerror else str(error)
            _write_json({"error": message, "path": args.path}, error_stream)
            return 1
    else:
        output_stream.write(rendered)
    return 0


if __name__ == "__main__":
    sys.exit(main())
