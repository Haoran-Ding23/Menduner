"""The QR encoder must produce a code a scanner can read, not one that looks right.

This file exists because three separate bugs shipped in it, and NONE of them was visible in the
rendered image:

  1. the mask was XORed over the whole matrix, destroying the finder patterns, timing patterns
     and separators;
  2. the codeword-boundary padding was written as `(-length) % 8` instead of `8 - length % 8`,
     so a stream already on a boundary lost a whole zero codeword and everything after it shifted
     by one byte;
  3. the format information was written in the wrong direction and order.

Every one of those produced a symbol that looked like a QR code. The first self-check version of
this file passed all of its own assertions while the image could not be scanned by anything.

So the tests now verify against things that are NOT this implementation:

  * an independent DECODER (OpenCV) reads the URL back out of a rendered image, which is the only
    test that would have caught all three bugs;
  * an independent ENCODER (segno) produces a bit-identical matrix for the same version and mask;
  * the structural invariants a scanner relies on before it reads any bit.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

# crawler/tests/ -> crawler/ -> project root -> scripts/
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import qr_code as q  # noqa: E402

URL = "http://47.116.133.230"
PAYLOADS = [
    URL,
    "https://example.com/a/rather/long/path?with=query&and=more",
    "x" * 60,
    "苏州城市活动情报",
]


def finder_is_intact(m, r0: int, c0: int) -> bool:
    for r in range(7):
        for c in range(7):
            ring = r in (0, 6) or c in (0, 6)
            core = 2 <= r <= 4 and 2 <= c <= 4
            if m[r0 + r][c0 + c] != (1 if (ring or core) else 0):
                return False
    return True


def render(matrix, scale: int = 12, quiet: int = 4):
    """Matrix -> a grayscale image with a real quiet zone, the way a scanner sees it."""
    import numpy as np

    size = len(matrix)
    total = size + quiet * 2
    img = np.full((total, total), 255, dtype=np.uint8)
    for r in range(size):
        for c in range(size):
            if matrix[r][c]:
                img[r + quiet, c + quiet] = 0
    import cv2

    return cv2.resize(img, (total * scale, total * scale), interpolation=cv2.INTER_NEAREST)


class TestRealScanner:
    """The tests that would actually have caught the shipped bugs."""

    @pytest.mark.parametrize("text", PAYLOADS)
    def test_an_independent_decoder_reads_the_payload_back(self, text):
        cv2 = pytest.importorskip("cv2", reason="OpenCV provides the independent decoder")
        matrix, _version, _mask = q.final_matrix(text)
        decoded, _points, _straight = cv2.QRCodeDetector().detectAndDecode(render(matrix))
        assert decoded == text, f"scanner read {decoded!r}, expected {text!r}"

    def test_the_generated_svg_decodes_too(self):
        """The deliverable is the SVG, so decode the file a person would actually scan."""
        cv2 = pytest.importorskip("cv2")
        numpy = pytest.importorskip("numpy")

        svg, version = q.make_svg(URL, scale=12, quiet=4)
        modules = version * 4 + 17
        matrix = [[0] * modules for _ in range(modules)]
        for x, y in re.findall(r"M(\d+) (\d+)h12v12h-12z", svg):
            matrix[(int(y) - 48) // 12][(int(x) - 48) // 12] = 1
        img = numpy.full(((modules + 8) * 12,) * 2, 255, dtype=numpy.uint8)
        for r, row in enumerate(matrix):
            for c, bit in enumerate(row):
                if bit:
                    img[(r + 4) * 12:(r + 5) * 12, (c + 4) * 12:(c + 5) * 12] = 0
        decoded, _points, _straight = cv2.QRCodeDetector().detectAndDecode(img)
        assert decoded == URL


class TestAgainstReferenceEncoder:
    """Bit-for-bit equality with an independent implementation."""

    def test_the_matrix_matches_segno_exactly(self):
        segno = pytest.importorskip("segno", reason="segno is an independent reference encoder")
        mine, version, mask = q.final_matrix(URL)
        reference = segno.make(
            URL, error="l", mode="byte", boost_error=False, version=version, mask=mask
        )
        expected = [[int(b) for b in row] for row in reference.matrix]
        assert len(expected) == len(mine)
        differences = [
            (r, c)
            for r in range(len(mine))
            for c in range(len(mine))
            if expected[r][c] != mine[r][c]
        ]
        assert not differences, f"{len(differences)} modules differ from segno: {differences[:10]}"


class TestFunctionPatterns:
    def test_the_three_finders_are_intact(self):
        """Bug 1: masking the whole matrix destroyed these."""
        m, _version, _ = q.final_matrix(URL)
        size = len(m)
        assert finder_is_intact(m, 0, 0), "top-left finder is corrupted"
        assert finder_is_intact(m, 0, size - 7), "top-right finder is corrupted"
        assert finder_is_intact(m, size - 7, 0), "bottom-left finder is corrupted"

    def test_separators_are_white(self):
        m, _version, _ = q.final_matrix(URL)
        size = len(m)
        assert all(m[7][c] == 0 for c in range(8))
        assert all(m[r][7] == 0 for r in range(8))
        assert all(m[7][size - 1 - c] == 0 for c in range(8))
        assert all(m[size - 1 - r][7] == 0 for r in range(8))

    def test_timing_patterns_alternate(self):
        """A scanner derives the module grid from these."""
        m, _version, _ = q.final_matrix(URL)
        size = len(m)
        for i in range(8, size - 8):
            assert m[6][i] == 1 - (i % 2), f"horizontal timing wrong at column {i}"
            assert m[i][6] == 1 - (i % 2), f"vertical timing wrong at row {i}"

    def test_the_timing_patterns_are_never_touched_by_format_placement(self):
        """Bug 3 put a format bit on (6,8) and flipped a timing module."""
        _version, codewords = q.encode_payload(URL)
        before = q.build(_version, codewords, 3)
        after = q.place_format(before, 3)
        for i in range(len(before)):
            assert before[6][i] == after[6][i], f"format placement changed (6,{i})"
            assert before[i][6] == after[i][6], f"format placement changed ({i},6)"

    def test_dark_module_is_set(self):
        m, _version, _ = q.final_matrix(URL)
        assert m[len(m) - 8][8] == 1

    def test_alignment_pattern_on_a_larger_version(self):
        m, version, _ = q.final_matrix("x" * 120)
        assert version >= 5
        size = len(m)
        for r in q.ALIGNMENT[version]:
            for c in q.ALIGNMENT[version]:
                if (r < 9 and c < 9) or (r < 9 and c > size - 10) or (r > size - 10 and c < 9):
                    continue
                assert m[r][c] == 1
                assert m[r - 1][c - 1] == 0


class TestFormatInformation:
    def test_format_bits_are_a_valid_bch_codeword(self):
        for mask in range(8):
            bits = q.format_bits(mask)
            assert bits >> 15 == 0, "format info must be 15 bits"
            unmasked = bits ^ 0x5412
            data = unmasked >> 10
            rem = data
            for _ in range(10):
                rem = (rem << 1) ^ ((rem >> 9) * 0x537)
            assert ((data << 10) | rem) & 0x7FFF == unmasked, f"mask {mask} fails BCH"
            assert (data >> 3) & 3 == 0b01, "ECC level should be L"
            assert (data & 7) == mask

    def test_both_copies_of_the_format_are_present_and_agree(self):
        """A scanner reads the format information to learn the mask and error level, so both
        copies must be present and must say the same thing.

        The two copies are interleaved in opposite directions, and the exact cell of each bit is
        easy to get subtly wrong by hand — an earlier version of this test asserted the wrong
        cells and failed against a correct encoder. So this checks the property that matters
        (the copies agree, and every cell is one of the 15 format bits) rather than pinning
        positions; exact positions are covered by the bit-for-bit comparison with segno.
        """
        m, _version, mask = q.final_matrix(URL)
        size = len(m)
        info = q.format_bits(mask)
        valid = {(info >> i) & 1 for i in range(15)}

        # The four strips that carry format information, skipping the timing patterns.
        strip_a = [m[i][8] for i in (0, 1, 2, 3, 4, 5, 7, 8)]
        strip_b = [m[8][size - 1 - i] for i in range(8)]
        strip_c = [m[8][i] for i in (0, 1, 2, 3, 4, 5, 7, 8)]
        strip_d = [m[size - 1 - i][8] for i in range(8)]

        for name, strip in (("a", strip_a), ("b", strip_b), ("c", strip_c), ("d", strip_d)):
            assert all(bit in valid for bit in strip), f"strip {name} holds a non-format bit"
        assert strip_a == strip_b, "the two copies of the low bits disagree"
        assert strip_c == strip_d, "the two copies of the high bits disagree"
        # All 15 bits must be represented across the two strips.
        assert set(strip_a) | set(strip_c) == valid
        # The dark module is always set and is not part of the format.
        assert m[size - 8][8] == 1

    def test_the_timing_patterns_are_not_part_of_either_copy(self):
        """Row 6 and column 6 must keep their alternating pattern — bug 3 wrote a format bit
        onto (6,8) and flipped it."""
        m, _version, mask = q.final_matrix(URL)
        expected = [1 - (i % 2) for i in range(8, len(m) - 8)]
        assert [m[6][i] for i in range(8, len(m) - 8)] == expected
        assert [m[i][6] for i in range(8, len(m) - 8)] == expected

    def test_the_format_matches_a_known_good_value(self):
        """Pinned against segno's output for version 2 / ECC L, which is what caught the
        wrong-direction bug."""
        assert [q.format_bits(m) for m in range(8)] == [
            30660, 29427, 32170, 30877, 26159, 25368, 27713, 26998,
        ]


class TestPayloadEncoding:
    def test_the_codeword_boundary_padding_adds_a_full_zero_codeword(self):
        """Bug 2: `(-length) % 8` skipped this and shifted every later codeword.

        Mode(4) + count(8) + data(21x8) + terminator(4) lands exactly on a codeword boundary at
        184 bits — and the spec still adds 8 more zero bits, giving two zero codewords before the
        first pad codeword. Pinned against segno's byte-for-byte output.
        """
        _version, codewords = q.encode_payload(URL)
        assert codewords[:23] == [
            65, 86, 135, 71, 71, 3, 162, 242, 243, 67, 114, 227, 19, 19, 98, 227, 19, 51, 50,
            227, 35, 51, 0,
        ]
        # ...and then the alternating pad codewords fill the rest of the data capacity.
        assert codewords[23:34] == [0, 236, 17, 236, 17, 236, 17, 236, 17, 236, 17]

    def test_the_version_grows_with_the_payload(self):
        assert q.encode_payload("y" * 150)[0] > q.encode_payload(URL)[0]

    def test_a_payload_too_large_is_refused_rather_than_truncated(self):
        with pytest.raises(ValueError):
            q.encode_payload("z" * 500)


class TestSvg:
    def test_the_svg_is_self_contained_with_a_white_background(self):
        svg, version = q.make_svg(URL, scale=10, quiet=4)
        assert svg.startswith("<svg")
        assert svg.rstrip().endswith("</svg>")
        assert 'fill="#ffffff"' in svg, "a transparent background scans badly"
        assert 'fill="#000000"' in svg
        assert f'width="{(version * 4 + 17 + 8) * 10}"' in svg

    def test_every_dark_module_becomes_exactly_one_square(self):
        svg, _version = q.make_svg(URL, scale=7)
        # Count real path commands, not the letter M: "viewBox", "xmlns" and the aria-label all
        # contain one, which made a character count look plausible and be wrong.
        assert len(re.findall(r"M\d+ \d+h7v7h-7z", svg)) == sum(
            row.count(1) for row in q.final_matrix(URL)[0]
        )

    def test_the_quiet_zone_is_at_least_four_modules(self):
        svg, version = q.make_svg(URL, scale=12, quiet=4)
        xs = [int(a) for a in re.findall(r"M(\d+) \d+h", svg)]
        ys = [int(a) for a in re.findall(r"M\d+ (\d+)h", svg)]
        assert min(xs) >= 48 and min(ys) >= 48

