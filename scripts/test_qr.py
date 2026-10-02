#!/usr/bin/env python3
"""
Tests for the stdlib QR generator (scripts/paynani_lib/sms/qr.py, SRV-4).
An assertion script, like the rest of this suite.

No QR reader is available to the suite, so besides known constants the test
reads each matrix back the way a scanner does (format bits, unmask, zigzag,
de-interleave, Reed-Solomon check, byte-mode decode) and expects the text.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))

from paynani_lib.sms import qr  # noqa: E402

passed = failed = 0


def check(label, expected, actual=True):
    global passed, failed
    if expected == actual:
        passed += 1
        print(f"ok   {label}")
    else:
        failed += 1
        print(f"FAIL {label}\n     expected {expected!r}\n     got      {actual!r}")


# --- constantes conocidas --------------------------------------------------
check("Reed-Solomon: 'HELLO WORLD' 1-M (vector de la guía de Thonky)",
      [196, 35, 39, 119, 235, 215, 231, 226, 93, 23],
      qr.reed_solomon([32, 91, 11, 120, 209, 114, 220, 77, 67, 64, 236, 17, 236, 17, 236, 17], 10))
check("bits de formato M, máscara 0 (101010000010010)", 0b101010000010010, qr._format_bits(0))
check("bits de versión 7 (000111110010010100)", 0b000111110010010100, qr._version_bits(7))
check("capacidades M: v1 14, v9 180, v10 213, v14 362",
      (14, 180, 213, 362), (qr.capacity(1), qr.capacity(9), qr.capacity(10), qr.capacity(14)))
for v in range(1, 15):
    ec, groups = qr._BLOCKS_M[v]
    total = qr._data_codewords(v) + ec * sum(n for n, _ in groups)
    grid = qr._Grid(v)
    free = sum(1 for y in range(grid.size) for x in range(grid.size) if not grid.func[y][x])
    if free != total * 8 + qr._REMAINDER_BITS[v]:
        check(f"v{v}: módulos libres = palabras de código * 8 + resto", total * 8 + qr._REMAINDER_BITS[v], free)
        break
else:
    check("v1..v14: los módulos libres cuadran con la tabla de bloques", True)


# --- lectura de vuelta --------------------------------------------------------
def read_back(matrix):
    size = len(matrix)
    version = (size - 17) // 4
    grid = qr._Grid(version)
    bit = lambda x, y: 1 if matrix[y][x] else 0  # noqa: E731
    fmt = sum(bit(8, i) << i for i in range(6)) | bit(8, 7) << 6 | bit(8, 8) << 7 | bit(7, 8) << 8
    fmt |= sum(bit(14 - i, 8) << i for i in range(9, 15))
    mask = next((m for m in range(8) if qr._format_bits(m) == fmt), None)
    if mask is None:
        return None, "formato ilegible"
    mod = [row[:] for row in matrix]
    for y in range(size):
        for x in range(size):
            if not grid.func[y][x] and qr._MASKS[mask](x, y):
                mod[y][x] = not mod[y][x]
    bits = [1 if mod[y][x] else 0 for x, y in qr._zigzag(size) if not grid.func[y][x]]
    ec_len, groups = qr._BLOCKS_M[version]
    sizes = [s for n, s in groups for _ in range(n)]
    words = [int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, (len(bits) // 8) * 8, 8)]
    blocks = [[] for _ in sizes]
    pos = 0
    for i in range(max(sizes)):
        for b, s in enumerate(sizes):
            if i < s:
                blocks[b].append(words[pos])
                pos += 1
    eccs = [[] for _ in sizes]
    for i in range(ec_len):
        for b in range(len(sizes)):
            eccs[b].append(words[pos])
            pos += 1
    data = []
    for b in range(len(sizes)):
        if qr.reed_solomon(blocks[b], ec_len) != eccs[b]:
            return None, f"Reed-Solomon no cuadra en el bloque {b}"
        data.extend(blocks[b])
    stream = "".join(f"{w:08b}" for w in data)
    if stream[:4] != "0100":
        return None, "no es modo de bytes"
    count_bits = 8 if version < 10 else 16
    n = int(stream[4:4 + count_bits], 2)
    body = stream[4 + count_bits:4 + count_bits + n * 8]
    return bytes(int(body[i:i + 8], 2) for i in range(0, len(body), 8)).decode("utf-8"), version


payload = json.dumps({"v": 1, "pair": "https://iris-gateway-demo.ngrok.io/sms/pair",
                      "ws": "wss://iris-gateway-demo.ngrok.io/sms/ws", "code": "K7QW2MXP"},
                     separators=(", ", ": "))
for label, text in [("1 byte", "A"), ("el JSON de emparejamiento", payload), ("con acentos y ñ", "Teléfono: señal ✓"),
                    ("14 bytes (llena v1)", "x" * 14), ("15 bytes (v2)", "x" * 15),
                    ("181 bytes (v10, contador de 16 bits)", "y" * 181), ("362 bytes (llena v14)", "z" * 362)]:
    matrix = qr.encode(text)
    got, info = read_back(matrix)
    check(f"se lee de vuelta: {label}", (text, True), (got, isinstance(info, int)))
check("el JSON de emparejamiento cabe en una versión modesta (<= 10)", True, read_back(qr.encode(payload))[1] <= 10)
check("el tamaño sigue a la versión (v2 = 25 módulos)", 25, len(qr.encode("x" * 15)))

try:
    qr.encode("w" * 363)
    check("363 bytes no caben", "ValueError", "sin error")
except ValueError as exc:
    check("363 bytes no caben: ValueError claro", True, "no cabe" in str(exc))

m = qr.encode("hola")
finder = [[m[y][x] for x in range(7)] for y in range(7)]
check("patrón de búsqueda arriba a la izquierda", [True] * 7, finder[0])
check("esquinas de los otros dos patrones de búsqueda", (True, True), (m[0][len(m) - 1], m[len(m) - 1][0]))
check("determinista: el mismo texto da la misma matriz", m, qr.encode("hola"))

svg = qr.to_svg(qr.encode("hola"), label="QR <de> prueba")
check("SVG: viewBox con zona de silencio de 4 módulos",
      True, f'viewBox="0 0 {len(m) + 8} {len(m) + 8}"' in svg)
check("SVG: sin scripts y con el título escapado por to_svg", True,
      "<script" not in svg and "<title>QR &lt;de&gt; prueba</title>" in svg)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
