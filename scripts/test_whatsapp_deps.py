#!/usr/bin/env python3
"""
Tests for the WhatsApp bridge's dependencies (WA-1 #553, PRD #550 FR-3, FR-3a):
exact versions in package.json, a lockfile that pins and hashes them, and no
node_modules in git.
An assertion script, like the rest of this suite.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "scripts" / "whatsapp_bridge"

passed = failed = 0


def check(label, expected, actual=True):
    global passed, failed
    if expected == actual:
        passed += 1
        print(f"ok   {label}")
    else:
        failed += 1
        print(f"FAIL {label}\n     expected {expected!r}\n     got      {actual!r}")


# Una versión exacta: 1.2.3 o 1.2.3-rc4. Nada de ^, ~, *, x, latest, rangos ni URLs.
EXACT = re.compile(r"^\d+\.\d+\.\d+(-[0-9A-Za-z.]+)?$")

pkg = json.loads((BRIDGE / "package.json").read_text())
deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {}),
        **pkg.get("optionalDependencies", {})}
check("package.json tiene dependencias", True, bool(deps))
loose = {name: v for name, v in deps.items() if not EXACT.match(v)}
check("FR-3a: ninguna dependencia directa con rango (^, ~, *, latest, x)", {}, loose)
check("FR-3b: engines.node pide 20 o más", ">=20", pkg.get("engines", {}).get("node"))
check("package.json es privado (no se publica en npm)", True, pkg.get("private"))

lock = json.loads((BRIDGE / "package-lock.json").read_text())
check("package-lock.json en formato 3 (npm 9 o más)", 3, lock.get("lockfileVersion"))
root = lock.get("packages", {}).get("", {})
check("el lockfile declara las mismas dependencias que package.json",
      pkg.get("dependencies", {}), root.get("dependencies", {}))
for name, version in pkg.get("dependencies", {}).items():
    entry = lock["packages"].get(f"node_modules/{name}", {})
    check(f"lockfile: {name} resuelto en {version}", version, entry.get("version"))
missing = [k for k, v in lock["packages"].items()
           if k and not v.get("link") and not str(v.get("integrity", "")).startswith("sha512-")]
check("FR-3: cada paquete del lockfile con hash sha512", [], missing)
registry = [k for k, v in lock["packages"].items()
            if k and v.get("resolved") and not v["resolved"].startswith("https://registry.npmjs.org/")]
check("FR-3: todo viene del registro de npm (sin git ni tarballs sueltos)", [], registry)

tracked = subprocess.run(["git", "ls-files", "scripts/whatsapp_bridge/node_modules"], cwd=ROOT,
                         capture_output=True, text=True).stdout.strip()
check("node_modules no está en git", "", tracked)
ignored = subprocess.run(["git", "check-ignore", "-q", "scripts/whatsapp_bridge/node_modules/x"],
                         cwd=ROOT).returncode
check(".gitignore cubre scripts/whatsapp_bridge/node_modules/", 0, ignored)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
