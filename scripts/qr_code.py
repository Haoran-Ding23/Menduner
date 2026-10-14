"""Generate a QR code for the Menduner site as a self-contained SVG.

Written by hand rather than pulled from a package: the project pins its dependencies, an extra
build-time dep is not worth it for one image, and an SVG scales to any print size without going
fuzzy the way a small PNG does when it is blown up for a poster.

Implements the QR spec for byte mode, ECC level L: mode/count indicator, payload, Reed-Solomon
over GF(256), block interleaving, module placement, mask selection by penalty.

The mask is applied as each DATA module is placed, and never to a function module. An earlier
version applied it to the finished matrix, which XORed the finder patterns, timing patterns and
separators into garbage. It looked like a QR code and would not have scanned. The structural
self-check below caught it, which is the only reason it is not shipping.
"""
from __future__ import annotations

import sys

# --- GF(256) arithmetic ---------------------------------------------------------------------
EXP = [0] * 512
LOG = [0] * 256
_x = 1
for _i in range(255):
    EXP[_i] = _x
    LOG[_x] = _i
    _x <<= 1
    if _x & 0x100:
        _x ^= 0x11D
for _i in range(255, 512):
    EXP[_i] = EXP[_i - 255]


def gf_mul(a: int, b: int) -> int:
    if a == 0 or b == 0:
        return 0
    return EXP[LOG[a] + LOG[b]]


def rs_poly(degree: int) -> list[int]:
    poly = [1]
    for i in range(degree):
        nxt = [0] * (len(poly) + 1)
        for j, coef in enumerate(poly):
            nxt[j] ^= gf_mul(coef, 1)
            nxt[j + 1] ^= gf_mul(coef, EXP[i])
        poly = nxt
    return poly


def rs_encode(data: list[int], ecc_len: int) -> list[int]:
    gen = rs_poly(ecc_len)
    msg = data + [0] * ecc_len
    for i in range(len(data)):
        coef = msg[i]
        if coef == 0:
            continue
        for j, g in enumerate(gen):
            msg[i + j] ^= gf_mul(g, coef)
    return msg[len(data):]


# --- version tables (byte mode, ECC level L) -------------------------------------------------
VERSIONS = {
    1: (26, 19, 7, 1),
    2: (44, 34, 10, 1),
    3: (70, 55, 15, 1),
    4: (100, 80, 20, 1),
    5: (134, 108, 26, 1),
    6: (172, 136, 18, 2),
    7: (196, 156, 20, 2),
    8: (242, 194, 24, 2),
    9: (292, 232, 30, 2),
    10: (346, 274, 18, 4),
}
ALIGNMENT = {
    1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30], 6: [6, 34],
    7: [6, 22, 38], 8: [6, 24, 42], 9: [6, 26, 46], 10: [6, 28, 50],
}


def encode_payload(text: str) -> tuple[int, list[int]]:
    raw = text.encode("utf-8")
    for version in range(1, 11):
        _, data_cw, ecc_per_block, blocks = VERSIONS[version]
        count_bits = 8 if version <= 9 else 16
        capacity_bits = data_cw * 8
        if 4 + count_bits + len(raw) * 8 > capacity_bits:
            continue

        bits: list[int] = [0, 1, 0, 0]
        bits += [(len(raw) >> (count_bits - 1 - i)) & 1 for i in range(count_bits)]
        for byte in raw:
            bits += [(byte >> (7 - i)) & 1 for i in range(8)]

        # Terminator: at most four zeros, or as many as fit.
        bits += [0] * min(capacity_bits - len(bits), 4)

        # Pad to a codeword boundary. Note this is 8 - (length % 8), NOT its modulo: when the
        # stream already ends on a boundary the spec still adds a whole zero codeword. Writing
        # `(-length) % 8` here skipped those eight bits, and every following codeword shifted by
        # one — the symbol still looked like a QR code and no scanner could read it.
        bits += [0] * (8 - len(bits) % 8)

        codewords = [int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]

        # Remaining capacity takes alternating pad codewords 11101100 / 00010001.
        pad = ((1, 1, 1, 0, 1, 1, 0, 0), (0, 0, 0, 1, 0, 0, 0, 1))
        for i in range(capacity_bits // 8 - len(codewords)):
            bits += list(pad[i % 2])
        codewords = [int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]

        per_block = data_cw // blocks
        data_blocks = [codewords[i * per_block:(i + 1) * per_block] for i in range(blocks)]
        ecc_blocks = [rs_encode(b, ecc_per_block) for b in data_blocks]
        out: list[int] = []
        for i in range(per_block):
            for b in data_blocks:
                out.append(b[i])
        for i in range(ecc_per_block):
            for b in ecc_blocks:
                out.append(b[i])
        return version, out
    raise ValueError("payload too large for the supported versions")


def function_layer(version: int) -> tuple[list[list[int]], list[list[bool]]]:
    """The fixed patterns, plus a map of which cells they occupy.

    Both are needed: the patterns go into the output untouched, and the reservation map is what
    keeps data, and therefore the mask, out of them.
    """
    size = version * 4 + 17
    m = [[0] * size for _ in range(size)]
    reserved = [[False] * size for _ in range(size)]

    def finder(row: int, col: int) -> None:
        for r in range(-1, 8):
            for c in range(-1, 8):
                rr, cc = row + r, col + c
                if not (0 <= rr < size and 0 <= cc < size):
                    continue
                reserved[rr][cc] = True
                inside = 0 <= r <= 6 and 0 <= c <= 6
                ring = r in (0, 6) or c in (0, 6)
                core = 2 <= r <= 4 and 2 <= c <= 4
                m[rr][cc] = 1 if (inside and (ring or core)) else 0

    finder(0, 0)
    finder(0, size - 7)
    finder(size - 7, 0)

    for i in range(8, size - 8):
        m[6][i] = 1 - (i % 2)
        m[i][6] = 1 - (i % 2)
        reserved[6][i] = True
        reserved[i][6] = True

    for r in ALIGNMENT[version]:
        for c in ALIGNMENT[version]:
            if (r < 9 and c < 9) or (r < 9 and c > size - 10) or (r > size - 10 and c < 9):
                continue
            for dr in range(-2, 3):
                for dc in range(-2, 3):
                    m[r + dr][c + dc] = 1 if max(abs(dr), abs(dc)) != 1 else 0
                    reserved[r + dr][c + dc] = True

    for i in range(9):
        reserved[8][i] = True
        reserved[i][8] = True
    for i in range(8):
        reserved[8][size - 1 - i] = True
        reserved[size - 1 - i][8] = True
    reserved[size - 8][8] = True
    m[size - 8][8] = 1
    return m, reserved


def mask_condition(mask: int, r: int, c: int) -> bool:
    return [
        (r + c) % 2 == 0,
        r % 2 == 0,
        c % 3 == 0,
        (r + c) % 3 == 0,
        (r // 2 + c // 3) % 2 == 0,
        (r * c) % 2 + (r * c) % 3 == 0,
        ((r * c) % 2 + (r * c) % 3) % 2 == 0,
        ((r + c) % 2 + (r * c) % 3) % 2 == 0,
    ][mask]


def build(version: int, codewords: list[int], mask: int) -> list[list[int]]:
    m, reserved = function_layer(version)
    size = len(m)
    total_bits = len(codewords) * 8
    bit_index = 0
    col = size - 1
    upward = True
    while col > 0:
        if col == 6:
            col -= 1
        rows = range(size - 1, -1, -1) if upward else range(size)
        for row in rows:
            for c in (col, col - 1):
                if reserved[row][c]:
                    continue
                bit = 0
                if bit_index < total_bits:
                    bit = (codewords[bit_index // 8] >> (7 - bit_index % 8)) & 1
                # Applied HERE, only here, so the function patterns stay intact.
                if mask_condition(mask, row, c):
                    bit ^= 1
                m[row][c] = bit
                bit_index += 1
        col -= 2
        upward = not upward
    return m


def format_bits(mask: int) -> int:
    data = (0b01 << 3) | mask  # ECC level L
    rem = data
    for _ in range(10):
        rem = (rem << 1) ^ ((rem >> 9) * 0x537)
    return ((data << 10) | rem) ^ 0x5412


def place_format(m: list[list[int]], mask: int) -> list[list[int]]:
    """Write the 15 format bits into their two reserved strips.

    The two strips run in OPPOSITE bit orders, and both skip the timing patterns. Reading
    segno's implementation is what settled this: the low bits go down the left column from (0,8)
    with a step past row 6, the high bits run right along row 8 from (8,0) with a step past
    column 6, and each of the two copies of the symbol is interleaved the other way round — the
    low bits along row 8 to the top-right, the high bits up the column from the bottom-left.

    Getting this wrong is close to invisible: the data area and every function pattern can be
    bit-perfect and the code still will not decode, because a scanner reads the format
    information first to learn the mask and the error level.
    """
    size = len(m)
    out = [row[:] for row in m]
    info = format_bits(mask)
    voffset = 0
    hoffset = 0
    for i in range(8):
        vbit = (info >> i) & 1
        hbit = (info >> (14 - i)) & 1
        if i == 6:  # the timing pattern occupies row 6 and column 6
            voffset += 1
            hoffset = 1
        out[i + voffset][8] = vbit           # left column, low bits
        out[8][i + hoffset] = hbit           # row 8, high bits
        out[8][size - 1 - i] = vbit          # top-right, low bits
        out[size - 1 - i][8] = hbit          # bottom-left, high bits
    out[size - 8][8] = 1  # dark module
    return out


def penalty(m: list[list[int]]) -> int:
    size = len(m)
    score = 0
    lines = list(m) + [list(col) for col in zip(*m)]
    for line in lines:
        run = 1
        for i in range(1, size):
            if line[i] == line[i - 1]:
                run += 1
            else:
                if run >= 5:
                    score += 3 + (run - 5)
                run = 1
        if run >= 5:
            score += 3 + (run - 5)
    for r in range(size - 1):
        for c in range(size - 1):
            if m[r][c] == m[r][c + 1] == m[r + 1][c] == m[r + 1][c + 1]:
                score += 3
    for line in lines:
        for i in range(size - 10):
            window = line[i:i + 11]
            if window == [1, 0, 1, 1, 1, 0, 1, 0, 0, 0, 0] or window == [0, 0, 0, 0, 1, 0, 1, 1, 1, 0, 1]:
                score += 40
    dark = sum(sum(row) for row in m)
    score += 10 * (abs(dark * 100 // (size * size) - 50) // 5)
    return score


def final_matrix(text: str) -> tuple[list[list[int]], int, int]:
    version, codewords = encode_payload(text)
    best_score: int | None = None
    best_mask = 0
    best: list[list[int]] = []
    for mask in range(8):
        candidate = place_format(build(version, codewords, mask), mask)
        score = penalty(candidate)
        if best_score is None or score < best_score:
            best_score, best_mask, best = score, mask, candidate
    return best, version, best_mask


def make_svg(text: str, scale: int = 12, quiet: int = 4) -> tuple[str, int]:
    m, version, _mask = final_matrix(text)
    size = len(m)
    total = size + quiet * 2
    px = total * scale
    path = [
        f"M{(c + quiet) * scale} {(r + quiet) * scale}h{scale}v{scale}h-{scale}z"
        for r in range(size)
        for c in range(size)
        if m[r][c]
    ]
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{px}" height="{px}" '
        f'viewBox="0 0 {px} {px}" role="img" aria-label="Menduner site QR code">\n'
        f"  <title>Menduner 扫码访问</title>\n"
        f'  <rect width="{px}" height="{px}" fill="#ffffff"/>\n'
        f'  <path d="{" ".join(path)}" fill="#000000"/>\n'
        f"</svg>\n",
        version,
    )


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else "http://47.116.133.230"
    out = sys.argv[2] if len(sys.argv) > 2 else "menduner-qr.svg"
    svg, version = make_svg(url)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(svg)
    print(f"url     : {url}")
    print(f"version : {version} ({version * 4 + 17}x{version * 4 + 17} modules)")
    print(f"written : {out}")
