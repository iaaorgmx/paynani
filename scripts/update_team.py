#!/usr/bin/env python3
"""
Actualiza «Development team» de PaynaniWeb (#686): `paynani_lib/web/team.json` y los
avatares en `paynani_lib/assets/team/`. Se corre a mano antes de una versión, con `gh`
autenticado (lee el repo privado de PaynaniApp-Agentic). La página nunca le pide nada a
GitHub (Iris[Q33] = A): todo sale de esta copia.

    python3 scripts/update_team.py            # actualiza y dice qué cambió
    python3 scripts/update_team.py --check    # sólo dice si hay cambios (sale 1 si hay)

Quién cuenta para cada proyecto, con los commits que GitHub liga a una cuenta:
- paynani: los contributors de iaaorgmx/paynani.
- PaynaniWeb: los autores de commits en la web (WEB_PATHS) de iaaorgmx/paynani.
- PaynaniApp: los contributors de iaaorgmx/PaynaniApp-Agentic e iaaorgmx/PaynaniApp.

El nombre y el tipo (human o agent) los decide
una persona: una cuenta nueva entra con `type: "?"` y la prueba de la página falla hasta
que alguien lo escriba en team.json. Alguien sin commits (Daniel y Ares, que apoyan con
pruebas reales, Iris[Q35]) se agrega a mano en team.json y el script lo conserva.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEAM = HERE / "paynani_lib" / "web" / "team.json"
AVATARS = HERE / "paynani_lib" / "assets" / "team"
CORE = "iaaorgmx/paynani"
APP = ("iaaorgmx/PaynaniApp-Agentic", "iaaorgmx/PaynaniApp")
WEB_PATHS = ("scripts/paynani_lib/web", "scripts/paynani_lib/assets", "PAYNANI_WEB.md")
SKIP = {"iaaorgmx"}            # la cuenta de la organización no es una persona
SIZE = 96                      # lo que se pide; los identicons de GitHub llegan de 420 px igual (Metis en #687)


def gh_json(path: str) -> list:
    """Todas las páginas de `path`, un elemento por línea (`--jq '.[]'`)."""
    out = subprocess.run(["gh", "api", "--paginate", path, "--jq", ".[]"], check=True, capture_output=True,
                         text=True).stdout
    return [json.loads(line) for line in out.splitlines() if line.strip()]


def contributors(repo: str) -> set[str]:
    return {c["login"] for c in gh_json(f"repos/{repo}/contributors?per_page=100") if c.get("type") == "User"}


def web_authors() -> set[str]:
    found = set()
    for path in WEB_PATHS:
        for c in gh_json(f"repos/{CORE}/commits?path={path}&per_page=100"):
            if (c.get("author") or {}).get("login"):
                found.add(c["author"]["login"])
    return found


def avatar(login: str) -> bytes:
    url = f"https://github.com/{login}.png?size={SIZE}"
    return subprocess.run(["curl", "-sSfL", "--max-time", "30", url], check=True, capture_output=True).stdout


def kind_of(data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    raise ValueError("el avatar no es PNG ni JPEG")


def main(check_only: bool) -> int:
    current = {m["login"]: m for m in json.loads(TEAM.read_text(encoding="utf-8"))["members"]} if TEAM.exists() else {}
    projects: dict[str, set[str]] = {}
    for login in contributors(CORE):
        projects.setdefault(login, set()).add("paynani")
    for login in web_authors():
        projects.setdefault(login, set()).add("paynaniweb")
    for repo in APP:
        for login in contributors(repo):
            projects.setdefault(login, set()).add("paynaniapp")
    members, changes = [], []
    for login in sorted(projects, key=str.lower):
        if login in SKIP:
            continue
        old = current.get(login, {})
        if not old:
            changes.append(f"nuevo: {login} (escribe su name y type en team.json)")
        member = {"login": login, "name": old.get("name") or login, "type": old.get("type") or "?",
                  "projects": [p for p in ("paynani", "paynaniweb", "paynaniapp") if p in projects[login]],
                  "avatar": old.get("avatar", "")}
        if old and old.get("projects") != member["projects"]:
            changes.append(f"proyectos de {login}: {old.get('projects')} -> {member['projects']}")
        members.append(member)
    for login in sorted(set(current) - {m["login"] for m in members}):
        members.append(current[login])   # nunca se quita a alguien solo: lo decide una persona
    if check_only:
        print("\n".join(changes) or "sin cambios")
        return 1 if changes else 0
    AVATARS.mkdir(parents=True, exist_ok=True)
    for m in members:
        data = avatar(m["login"])
        name = f"{m['login'].lower()}.{kind_of(data)}"
        target = AVATARS / name
        if not target.exists() or target.read_bytes() != data:
            for stale in AVATARS.glob(f"{m['login'].lower()}.*"):
                stale.unlink()
            target.write_bytes(data)
            changes.append(f"avatar: {name}")
        m["avatar"] = name
    TEAM.write_text(json.dumps({"members": members}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("\n".join(changes) or "sin cambios")
    return 0


if __name__ == "__main__":
    sys.exit(main("--check" in sys.argv[1:]))
