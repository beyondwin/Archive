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
    ihdr = struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0)
    chunks = [struct.pack(">I", len(ihdr)) + b"IHDR" + ihdr + b"\0\0\0\0"]
    chunks.extend(struct.pack(">I", len(payload)) + kind + payload + b"\0\0\0\0" for kind, payload in before_trns)
    if trns:
        transparency = trns_payload if trns_payload is not None else (b"\0\0\0\0\0\0" if color_type == 2 else b"\0\0")
        chunks.append(struct.pack(">I", len(transparency)) + b"tRNS" + transparency + b"\0\0\0\0")
    chunks.extend(struct.pack(">I", len(payload)) + kind + payload + b"\0\0\0\0" for kind, payload in after_trns)
    chunks.append(b"\0\0\0\0IEND\0\0\0\0")
    return b"\x89PNG\r\n\x1a\n" + b"".join(chunks)


def make_jpeg(width, height):
    sof = bytes([8]) + struct.pack(">HH", height, width) + b"\x01\x01\x11\0"
    return b"\xff\xd8\xff\xc0" + struct.pack(">H", len(sof) + 2) + sof + b"\xff\xd9"


def make_webp_vp8x(width, height, alpha, extra_payload=b""):
    flags = 0x10 if alpha else 0
    payload = bytes([flags, 0, 0, 0]) + (width - 1).to_bytes(3, "little") + (height - 1).to_bytes(3, "little") + extra_payload
    padding = b"\0" if len(payload) % 2 else b""
    body = b"WEBPVP8X" + struct.pack("<I", len(payload)) + payload + padding
    return b"RIFF" + struct.pack("<I", len(body)) + body


def make_webp_vp8(width, height):
    payload = b"\x00\x00\x00\x9d\x01\x2a" + struct.pack("<HH", width, height)
    body = b"WEBPVP8 " + struct.pack("<I", len(payload)) + payload
    return b"RIFF" + struct.pack("<I", len(body)) + body


def make_webp_vp8l(width, height):
    packed = (width - 1) | ((height - 1) << 14)
    payload = b"\x2f" + packed.to_bytes(4, "little")
    body = b"WEBPVP8L" + struct.pack("<I", len(payload)) + payload + b"\0"
    return b"RIFF" + struct.pack("<I", len(body)) + body


class AssetInspectorTests(unittest.TestCase):
    def test_png_reports_dimensions_and_alpha(self):
        data = make_png(width=3, height=2, color_type=6)
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
        data = make_jpeg(width=5, height=4)
        self.assertEqual(parse_jpeg(data), (5, 4, False))

    def test_webp_vp8x_reports_dimensions_and_alpha_flag(self):
        data = make_webp_vp8x(width=7, height=6, alpha=True)
        self.assertEqual(parse_webp(data), (7, 6, True))

    def test_webp_vp8x_without_alpha_is_false(self):
        self.assertEqual(parse_webp(make_webp_vp8x(7, 6, alpha=False)), (7, 6, False))

    def test_webp_vp8_reports_dimensions_without_alpha(self):
        self.assertEqual(parse_webp(make_webp_vp8(8, 9)), (8, 9, False))

    def test_webp_vp8l_reports_dimensions_with_unknown_alpha(self):
        self.assertEqual(parse_webp(make_webp_vp8l(10, 11)), (10, 11, None))

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
            sink = StringSink()
            result = main([str(missing)], output_stream=sink)
        self.assertEqual(result, 1)
        self.assertEqual(
            sink.value,
            json.dumps({"error": "No such file or directory", "path": str(missing)}, sort_keys=True) + "\n",
        )

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
            sink = StringSink()
            result = main([str(input_path), "--output", directory], output_stream=sink)
        self.assertEqual(result, 1)
        self.assertEqual(
            sink.value,
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
    if color_type not in (0, 2, 3, 4, 6) or compression != 0 or filtering != 0 or interlace not in (0, 1):
        raise ValueError("invalid PNG IHDR")
    if bit_depth == 0:
        raise ValueError("invalid PNG bit depth")

    alpha = color_type in (4, 6)
    seen_image_data = False
    seen_trns = False
    seen_iend = False
    palette_entries = None
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
        if chunk_type == b"IDAT":
            seen_image_data = True
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
            seen_iend = True
            break
        offset = payload_end + 4
    if not seen_iend:
        raise ValueError("missing PNG IEND")
    return width, height, alpha


def parse_jpeg(data):
    if not data.startswith(b"\xff\xd8"):
        raise ValueError("invalid JPEG SOI")
    offset = 2
    sof_markers = set(range(0xC0, 0xC4)) | set(range(0xC5, 0xC8)) | set(range(0xC9, 0xCC)) | set(range(0xCD, 0xD0))
    standalone_markers = {0x01, 0xD8, 0xD9} | set(range(0xD0, 0xD8))
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
                break
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
            return width, height, False
        offset += segment_length
    raise ValueError("JPEG SOF marker not found")


def parse_webp(data):
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        raise ValueError("invalid WebP RIFF header")
    declared_size = struct.unpack("<I", data[4:8])[0]
    riff_end = declared_size + 8
    if declared_size < 4 or riff_end > len(data):
        raise ValueError("truncated WebP RIFF")

    offset = 12
    primary = None
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
        if chunk_type in (b"VP8X", b"VP8 ", b"VP8L"):
            if primary is not None:
                raise ValueError("multiple WebP primary chunks")
            primary = (chunk_type, data[payload_start:payload_end])
        offset = padded_end
    if offset != riff_end:
        raise ValueError("invalid WebP chunk layout")
    if primary is None:
        raise ValueError("unsupported WebP primary chunk")

    chunk_type, payload = primary
    if chunk_type == b"VP8X":
        if len(payload) != 10:
            raise ValueError("invalid WebP VP8X length")
        width = int.from_bytes(payload[4:7], "little") + 1
        height = int.from_bytes(payload[7:10], "little") + 1
        _require_dimensions(width, height)
        return width, height, bool(payload[0] & 0x10)
    if chunk_type == b"VP8 ":
        if len(payload) < 10 or payload[3:6] != b"\x9d\x01\x2a":
            raise ValueError("invalid WebP VP8 header")
        width = struct.unpack("<H", payload[6:8])[0] & 0x3FFF
        height = struct.unpack("<H", payload[8:10])[0] & 0x3FFF
        _require_dimensions(width, height)
        return width, height, False
    if len(payload) < 5 or payload[0] != 0x2F:
        raise ValueError("invalid WebP VP8L header")
    packed = int.from_bytes(payload[1:5], "little")
    width = (packed & 0x3FFF) + 1
    height = ((packed >> 14) & 0x3FFF) + 1
    _require_dimensions(width, height)
    return width, height, None


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


def main(argv=None, output_stream=None):
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
    try:
        facts = inspect_file(args.path)
    except (OSError, ValueError) as error:
        message = error.strerror if isinstance(error, OSError) and error.strerror else str(error)
        _write_json({"error": message, "path": args.path}, output_stream)
        return 1
    rendered = json.dumps(dataclasses.asdict(facts), sort_keys=True) + "\n"
    if args.output:
        try:
            Path(args.output).write_text(rendered)
        except OSError as error:
            message = error.strerror if error.strerror else str(error)
            _write_json({"error": message, "path": args.path}, output_stream)
            return 1
    else:
        output_stream.write(rendered)
    return 0


if __name__ == "__main__":
    sys.exit(main())
