"""
`paynani web user add`, `paynani web passwd` y `paynani web user show` (PRD #434 FR-5).

El usuario de PaynaniWeb se crea en el host, nunca desde la web: quien llega por
internet a una instalación recién hecha no debe poder quedarse con ella (FR-4).
La contraseña se pide dos veces sin eco, o se lee de stdin con
`--password-stdin` (una línea), y nunca se imprime.
"""
from __future__ import annotations

import getpass
import sys

from . import users


def _read_password(args, prompt: str = "Password") -> str | None:
    if getattr(args, "password_stdin", False):
        line = sys.stdin.readline()
        return line.rstrip("\r\n")
    if not sys.stdin.isatty():
        print("No terminal to ask for the password; use --password-stdin.", file=sys.stderr)
        return None
    first = getpass.getpass(f"{prompt} (at least {users.MIN_PASSWORD} characters): ")
    second = getpass.getpass(f"{prompt}, again: ")
    if first != second:
        print("The two passwords do not match; nothing was saved.", file=sys.stderr)
        return None
    return first


def run_user_add(args) -> int:
    path = users.user_path()
    if users.exists(path):
        print(f"PaynaniWeb already has a user ({path}). There is only one (the owner); "
              "change its password with `scripts/paynani web passwd`.", file=sys.stderr)
        return 1
    if path.exists():
        print(f"{path} exists but is not a valid PaynaniWeb user file; move it aside "
              f"(mv {path} {path}.broken) and run `scripts/paynani web user add` again.", file=sys.stderr)
        return 1
    password = _read_password(args)
    if password is None:
        return 1
    try:
        data = users.create(args.email, args.name, password, path)
    except users.UserError as exc:
        print(f"Not saved: {exc}.", file=sys.stderr)
        return 2
    print(f"PaynaniWeb user created: {data['name']} <{data['email']}>.")
    print(f"Saved in {path} (mode 600). Only the password's scrypt hash is stored.")
    print("Reload PaynaniWeb in the browser to sign in.")
    return 0


def run_passwd(args) -> int:
    path = users.user_path()
    if not users.exists(path):
        print("PaynaniWeb has no user yet; create it with `scripts/paynani web user add`.", file=sys.stderr)
        return 1
    password = _read_password(args, "New password")
    if password is None:
        return 1
    try:
        users.set_password(password, path)
    except users.UserError as exc:
        print(f"Not saved: {exc}.", file=sys.stderr)
        return 2
    print("PaynaniWeb password changed.")
    return 0


def run_user_show(args) -> int:
    data = users.load()
    if data is None:
        print("PaynaniWeb has no user yet; create it with `scripts/paynani web user add`.")
        return 1
    shown = users.public(data)
    print(f"{shown.get('name', '')} <{shown.get('email', '')}>")
    print(f"created {shown.get('created_at', '?')}, password changed {shown.get('password_changed_at', '?')}")
    return 0
