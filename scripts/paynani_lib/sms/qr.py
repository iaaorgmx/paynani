"""
Generador de códigos QR, sólo con la biblioteca estándar (SRV-4).

paynani no lleva dependencias, así que el QR de emparejamiento se genera aquí:
modo de bytes, corrección de errores M, versiones 1 a 14 (hasta 362 bytes), que
sobra para el JSON de SMS_GATEWAY.md §1. Sigue ISO/IEC 18004: Reed-Solomon sobre
GF(256), intercalado de bloques, máscara elegida por penalización y los bits de
formato y de versión.

    matrix = encode("texto")        # lista de listas de bool, sin zona de silencio
    svg = to_svg(matrix)            # <svg> listo para incrustar en una página
"""
from __future__ import annotations

# --- GF(256) y Reed-Solomon -------------------------------------------------
_EXP = [0] * 512
_LOG = [0] * 256
_x = 1
for _i in range(255):
    _EXP[_i] = _x
    _LOG[_x] = _i
    _x <<= 1
    if _x & 0x100:
        _x ^= 0x11D
for _i in range(255, 512):
    _EXP[_i] = _EXP[_i - 255]


def _mul(a: int, b: int) -> int:
    return 0 if a == 0 or b == 0 else _EXP[_LOG[a] + _LOG[b]]


def _generator(degree: int) -> list[int]:
    poly = [1]
    for i in range(degree):
        nxt = [0] * (len(poly) + 1)
        for j, coef in enumerate(poly):
            nxt[j] ^= coef
            nxt[j + 1] ^= _mul(coef, _EXP[i])
        poly = nxt
    return poly


def reed_solomon(data: list[int], degree: int) -> list[int]:
    """Los `degree` bytes de corrección de `data`."""
    gen = _generator(degree)
    rem = list(data) + [0] * degree
    for i in range(len(data)):
        factor = rem[i]
        if factor:
            for j, coef in enumerate(gen):
                rem[i + j] ^= _mul(coef, factor)
    return rem[len(data):]


# --- tablas (nivel M) --------------------------------------------------------
# versión: (bytes de corrección por bloque, [(bloques, bytes de datos por bloque), ...])
_BLOCKS_M = {
    1: (10, [(1, 16)]), 2: (16, [(1, 28)]), 3: (26, [(1, 44)]), 4: (18, [(2, 32)]),
    5: (24, [(2, 43)]), 6: (16, [(4, 27)]), 7: (18, [(4, 31)]), 8: (22, [(2, 38), (2, 39)]),
    9: (22, [(3, 36), (2, 37)]), 10: (26, [(4, 43), (1, 44)]), 11: (30, [(1, 50), (4, 51)]),
    12: (22, [(6, 36), (2, 37)]), 13: (22, [(8, 37), (1, 38)]), 14: (24, [(4, 40), (5, 41)]),
}
_ALIGN = {
    1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30], 6: [6, 34], 7: [6, 22, 38],
    8: [6, 24, 42], 9: [6, 26, 46], 10: [6, 28, 50], 11: [6, 30, 54], 12: [6, 32, 58],
    13: [6, 34, 62], 14: [6, 26, 46, 66],
}
_REMAINDER_BITS = {1: 0, 2: 7, 3: 7, 4: 7, 5: 7, 6: 7, 7: 0, 8: 0, 9: 0, 10: 0, 11: 0, 12: 0, 13: 0, 14: 3}
_EC_BITS_M = 0
MAX_VERSION = 14


def _data_codewords(version: int) -> int:
    return sum(n * size for n, size in _BLOCKS_M[version][1])


def capacity(version: int) -> int:
    """Bytes de texto que caben en esa versión (modo de bytes, nivel M)."""
    count_bits = 8 if version < 10 else 16
    return (_data_codewords(version) * 8 - 4 - count_bits) // 8


def _version_for(length: int) -> int:
    for version in range(1, MAX_VERSION + 1):
        if length <= capacity(version):
            return version
    raise ValueError(f"el texto de {length} bytes no cabe en un QR de versión {MAX_VERSION} (máximo {capacity(MAX_VERSION)})")


# --- datos -----------------------------------------------------------------------
def _data_bits(payload: bytes, version: int) -> list[int]:
    bits: list[int] = []

    def put(value: int, count: int) -> None:
        bits.extend((value >> i) & 1 for i in range(count - 1, -1, -1))

    put(0b0100, 4)
    put(len(payload), 8 if version < 10 else 16)
    for byte in payload:
        put(byte, 8)
    total = _data_codewords(version) * 8
    put(0, min(4, total - len(bits)))
    put(0, -len(bits) % 8)
    pad = 0xEC
    while len(bits) < total:
        put(pad, 8)
        pad = 0x11 if pad == 0xEC else 0xEC
    return bits


def _codewords(payload: bytes, version: int) -> list[int]:
    bits = _data_bits(payload, version)
    data = [int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]
    ec_len, groups = _BLOCKS_M[version]
    blocks, pos = [], 0
    for count, size in groups:
        for _ in range(count):
            blocks.append(data[pos:pos + size])
            pos += size
    ecc = [reed_solomon(block, ec_len) for block in blocks]
    out = []
    for i in range(max(len(b) for b in blocks)):
        out.extend(b[i] for b in blocks if i < len(b))
    for i in range(ec_len):
        out.extend(e[i] for e in ecc)
    return out


# --- matriz ---------------------------------------------------------------------
def _format_bits(mask: int) -> int:
    data = (_EC_BITS_M << 3) | mask
    rem = data
    for _ in range(10):
        rem = (rem << 1) ^ ((rem >> 9) * 0x537)
    return ((data << 10) | rem) ^ 0x5412


def _version_bits(version: int) -> int:
    rem = version
    for _ in range(12):
        rem = (rem << 1) ^ ((rem >> 11) * 0x1F25)
    return (version << 12) | rem


def _zigzag(size: int):
    """Las posiciones (x, y) en el orden en que se colocan los datos: de a dos columnas, de derecha a izquierda."""
    right = size - 1
    while right >= 1:
        if right == 6:
            right = 5  # la columna 6 es la de sincronía: no se usa
        for vert in range(size):
            for j in range(2):
                x = right - j
                y = size - 1 - vert if ((right + 1) & 2) == 0 else vert
                yield x, y
        right -= 2


class _Grid:
    def __init__(self, version: int):
        self.version = version
        self.size = 17 + 4 * version
        self.mod = [[False] * self.size for _ in range(self.size)]
        self.func = [[False] * self.size for _ in range(self.size)]
        self._patterns()
        self._format(0)  # reserva las áreas de formato (se reescriben con la máscara)

    def set(self, x: int, y: int, dark: bool, func: bool = True) -> None:
        self.mod[y][x] = dark
        if func:
            self.func[y][x] = True

    def _patterns(self) -> None:
        size = self.size
        for i in range(size):
            self.set(6, i, i % 2 == 0)
            self.set(i, 6, i % 2 == 0)
        for cx, cy in ((3, 3), (size - 4, 3), (3, size - 4)):
            for dy in range(-4, 5):
                for dx in range(-4, 5):
                    x, y = cx + dx, cy + dy
                    if 0 <= x < size and 0 <= y < size:
                        dist = max(abs(dx), abs(dy))
                        self.set(x, y, dist not in (2, 4))
        centers = _ALIGN[self.version]
        for i, cy in enumerate(centers):
            for j, cx in enumerate(centers):
                if (i == 0 and j == 0) or (i == 0 and j == len(centers) - 1) or (i == len(centers) - 1 and j == 0):
                    continue
                for dy in range(-2, 3):
                    for dx in range(-2, 3):
                        self.set(cx + dx, cy + dy, max(abs(dx), abs(dy)) != 1)
        if self.version >= 7:
            bits = _version_bits(self.version)
            for i in range(18):
                bit = (bits >> i) & 1 == 1
                a, b = size - 11 + i % 3, i // 3
                self.set(a, b, bit)
                self.set(b, a, bit)

    def _format(self, mask: int) -> None:
        bits, size = _format_bits(mask), self.size
        bit = lambda i: (bits >> i) & 1 == 1  # noqa: E731
        for i in range(6):
            self.set(8, i, bit(i))
        self.set(8, 7, bit(6))
        self.set(8, 8, bit(7))
        self.set(7, 8, bit(8))
        for i in range(9, 15):
            self.set(14 - i, 8, bit(i))
        for i in range(8):
            self.set(size - 1 - i, 8, bit(i))
        for i in range(8, 15):
            self.set(8, size - 15 + i, bit(i))
        self.set(8, size - 8, True)

    def place(self, codewords: list[int]) -> None:
        i = 0
        bits = []
        for word in codewords:
            bits.extend((word >> i) & 1 for i in range(7, -1, -1))
        bits.extend([0] * _REMAINDER_BITS[self.version])
        for x, y in _zigzag(self.size):
            if not self.func[y][x] and i < len(bits):
                self.mod[y][x] = bits[i] == 1
                i += 1

    def apply_mask(self, mask: int) -> None:
        for y in range(self.size):
            for x in range(self.size):
                if not self.func[y][x] and _MASKS[mask](x, y):
                    self.mod[y][x] = not self.mod[y][x]


_MASKS = [
    lambda x, y: (x + y) % 2 == 0,
    lambda x, y: y % 2 == 0,
    lambda x, y: x % 3 == 0,
    lambda x, y: (x + y) % 3 == 0,
    lambda x, y: (x // 3 + y // 2) % 2 == 0,
    lambda x, y: x * y % 2 + x * y % 3 == 0,
    lambda x, y: (x * y % 2 + x * y % 3) % 2 == 0,
    lambda x, y: ((x + y) % 2 + x * y % 3) % 2 == 0,
]


def _penalty(mod: list[list[bool]]) -> int:
    size, score = len(mod), 0
    lines = [row for row in mod] + [[mod[y][x] for y in range(size)] for x in range(size)]
    for line in lines:
        run = 1
        for i in range(1, size):
            if line[i] == line[i - 1]:
                run += 1
            else:
                score += run - 2 if run >= 5 else 0
                run = 1
        score += run - 2 if run >= 5 else 0
        s = "".join("1" if v else "0" for v in line)
        score += 40 * (s.count("10111010000") + s.count("00001011101"))
    for y in range(size - 1):
        for x in range(size - 1):
            if mod[y][x] == mod[y][x + 1] == mod[y + 1][x] == mod[y + 1][x + 1]:
                score += 3
    dark = sum(sum(row) for row in mod)
    score += 10 * (abs(dark * 20 - size * size * 10) // (size * size))
    return score


def encode(text: str) -> list[list[bool]]:
    """La matriz del QR para `text` (UTF-8). Lanza ValueError si no cabe."""
    payload = text.encode("utf-8")
    version = _version_for(len(payload))
    best = None
    for mask in range(8):
        grid = _Grid(version)
        grid.place(_codewords(payload, version))
        grid.apply_mask(mask)
        grid._format(mask)
        score = _penalty(grid.mod)
        if best is None or score < best[0]:
            best = (score, grid.mod)
    return [row[:] for row in best[1]]


def to_svg(matrix: list[list[bool]], quiet: int = 4, label: str = "") -> str:
    """El QR como <svg>, con zona de silencio. Un solo <path> de rectángulos."""
    size = len(matrix)
    parts = []
    for y, row in enumerate(matrix):
        x = 0
        while x < size:
            if row[x]:
                start = x
                while x < size and row[x]:
                    x += 1
                parts.append(f"M{start + quiet} {y + quiet}h{x - start}v1h-{x - start}z")
            else:
                x += 1
    total = size + 2 * quiet
    title = f"<title>{label}</title>" if label else ""
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {total} {total}" '
            f'width="256" height="256" role="img" shape-rendering="crispEdges">{title}'
            f'<rect width="{total}" height="{total}" fill="#fff"/>'
            f'<path d="{"".join(parts)}" fill="#000"/></svg>')
