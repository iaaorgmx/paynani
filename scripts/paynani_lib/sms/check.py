"""
`paynani sms check` (#350, punto 4): la prueba guiada después de emparejar.

Revisa, en orden, lo que tiene que estar bien para que un SMS vaya y venga:
el servicio de la pasarela, que la pasarela conteste en este equipo, que el
túnel llegue a ella, y que el teléfono emparejado esté en línea. Con `--to`,
además manda un SMS de prueba a un número del roster por el mismo camino que
`paynani sms send` y, con `--wait-reply`, espera la respuesta de ese número en
`events.jsonl`.

Cada línea empieza con `ok`, `warn` o `FAIL`. Sale con 0 si no hubo ningún FAIL,
1 si lo hubo y 2 si se rechazó lo que se pidió (igual que `sms send`).
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "harness"))
sys.path.insert(0, str(ROOT / "scripts"))

import paths  # noqa: E402
import phone  # noqa: E402

from . import cli as sms_cli  # noqa: E402
from . import health  # noqa: E402

DEFAULT_PORT = 8770
HTTP_TIMEOUT_S = 5
# «No me pasaron nada»; None queda para «no instalado» y «sin teléfono».
_UNSET = object()


class Report:
    def __init__(self, out=None):
        self.out = out or sys.stdout
        self.failed = False

    def ok(self, text):
        print(f"ok    {text}", file=self.out, flush=True)

    def warn(self, text):
        print(f"warn  {text}", file=self.out, flush=True)

    def fail(self, text):
        self.failed = True
        print(f"FAIL  {text}", file=self.out, flush=True)


def fetch_health(base_url, timeout=HTTP_TIMEOUT_S):
    """(dict, None) con la respuesta de /sms/health, o (None, motivo)."""
    url = base_url.rstrip("/") + "/sms/health"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 -- URL del propio usuario
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return None, f"HTTP {exc.code}"
    except (urllib.error.URLError, OSError) as exc:
        return None, str(getattr(exc, "reason", exc))
    except ValueError:
        return None, "the answer is not JSON"
    if not isinstance(body, dict) or body.get("ok") is not True:
        return None, "the answer is not the gateway's"
    return body, None


def check_service(report, gateway_facts):
    if gateway_facts is None:
        report.fail("gateway service: not installed. Install it with `scripts/install.sh --with-sms` (INSTALL.md §5.1)")
        return
    if gateway_facts["unit"] == "active":
        report.ok(f"gateway service: {gateway_facts['name']} active")
    elif gateway_facts["unit"] == "unknown":
        report.warn(f"gateway service: {gateway_facts['name']} cannot be queried on this host; checking the gateway itself")
    else:
        report.fail(f"gateway service: {gateway_facts['name']} is {gateway_facts['unit']}. See state/sms.err.log")


def check_local(report, port, fetch=fetch_health):
    body, why = fetch(f"http://127.0.0.1:{port}")
    if body is None:
        report.fail(f"gateway on this machine: no answer on port {port} ({why})")
        return False
    report.ok(f"gateway on this machine: answers on port {port}")
    return True


def check_tunnel(report, public_url, fetch=fetch_health):
    if not public_url:
        report.fail("tunnel: PAYNANI_SMS_PUBLIC_URL is not set in sms.env, so the phone has no address to call (INSTALL.md §5.1)")
        return False
    if not public_url.startswith("https://"):
        report.warn(f"tunnel: {public_url} is not https://")
    if ".trycloudflare.com" in public_url:
        report.warn("tunnel: a trycloudflare.com quick tunnel changes address when it restarts, and the phone then "
                    "has to be paired again. Use an ngrok reserved domain or a cloudflared named tunnel (INSTALL.md §5.1)")
    body, why = fetch(public_url)
    if body is None:
        report.fail(f"tunnel: {public_url}/sms/health does not reach the gateway ({why}). Check that the tunnel is "
                    "running and points at the gateway's port")
        return False
    report.ok(f"tunnel: {public_url} reaches the gateway")
    return True


def check_phone(report, facts):
    if facts is None:
        report.fail("phone: none is paired. Run `scripts/paynani sms pair` and scan the code with the app (INSTALL.md §5.2)")
        return False
    who = facts["device_id"] + (f" ({facts['model']})" if facts["model"] else "")
    version = f", PaynaniApp {facts['app_version']}" if facts["app_version"] else ""
    if facts["last_seen_age_s"] is None:
        report.fail(f"phone: {who} is paired but has never connected. Open Paynani on the phone and check its Status screen")
        return False
    if not facts["online"]:
        report.fail(f"phone: {who} is offline, last heartbeat {facts['last_seen_age_s']} s ago{version}. "
                    "Open Paynani on the phone; the maker's power saver may have closed it (INSTALL.md §5.2, step 4)")
        return False
    report.ok(f"phone: {who} online, last heartbeat {facts['last_seen_age_s']} s ago{version}")
    numbers = [str(s.get("number")) for s in facts.get("sims") or [] if isinstance(s, dict) and s.get("number")]
    if numbers:
        report.ok(f"phone number: {', '.join(numbers)}")
    else:
        report.warn("phone number: the SIM does not expose it (common, not a fault). Texts still work; "
                    "the people who write to it need the number from the SIM's owner")
    if facts["orders_queued"]:
        report.warn(f"phone: {facts['orders_queued']} order(s) waiting in the outbox")
    return True


def journal_size(journal):
    try:
        return journal.stat().st_size
    except OSError:
        return 0


def wait_for_reply(journal, offset, number, seconds, poll_s=1.0, clock=time.monotonic, sleep=time.sleep):
    """El primer `sms.received` de `number` escrito después de `offset`, o None."""
    deadline = clock() + seconds
    while True:
        try:
            with open(journal, "rb") as fh:
                fh.seek(offset)
                for raw in fh:
                    try:
                        record = json.loads(raw.decode("utf-8"))
                    except ValueError:
                        continue
                    if (record.get("event_type") == "sms.received"
                            and (record.get("sender") or {}).get("address") == number):
                        return record
        except OSError:
            pass
        if clock() >= deadline:
            return None
        sleep(poll_s)


def run(args, out=None, gateway_facts=_UNSET, phone_facts=_UNSET, fetch=fetch_health, send=None) -> int:
    report = Report(out)
    number = None
    if args.to:
        number = phone.to_e164(args.to)
        if number is None:
            return sms_cli._refuse(f"{args.to!r} is not a phone number. Write it in E.164, for example +525511112222.")
    if gateway_facts is _UNSET:
        import healthcheck  # noqa: PLC0415 -- pesado; sólo cuando se usa
        gateway_facts = healthcheck.sms_gateway_facts()
    port = int(os.environ.get("PAYNANI_SMS_PORT") or DEFAULT_PORT)
    public_url = os.environ.get("PAYNANI_SMS_PUBLIC_URL", "").strip()

    check_service(report, gateway_facts)
    if gateway_facts is None:
        # Sin el servicio, lo que conteste en el puerto es de otra instalación
        # (en WSL todas las distribuciones comparten 127.0.0.1).
        return 1
    check_local(report, port, fetch)
    check_tunnel(report, public_url, fetch)
    if phone_facts is _UNSET:
        phone_facts = health.phone_facts(paths.state_dir())
        if phone_facts is not None:
            device = sms_cli._store().device() or {}
            phone_facts["sims"] = device.get("sims") or []
    online = check_phone(report, phone_facts)

    if number is None:
        if not report.failed:
            print("\nEverything the phone needs is in place. To try a text both ways, run:\n"
                  "  scripts/paynani sms check --to <a number on roster.md> --wait-reply 300", file=report.out)
        return 1 if report.failed else 0
    if report.failed or not online:
        print("\nNot sending the test text until the FAIL lines above are fixed.", file=report.out)
        return 1

    journal = Path(paths.state_dir()) / "events.jsonl"
    offset = journal_size(journal)
    text = f"paynani sms check {time.strftime('%H:%M:%S')}: test text. Reply to it to check the way back."
    print(f"\nSending a test text to {number}:", file=report.out, flush=True)
    send = send or sms_cli.run_send
    code = send(SimpleNamespace(number=number, text=[text], wait=args.wait, ttl=max(1, args.wait // 60 + 1), sim=None))
    if code == 2:
        return 2
    if code != 0:
        report.fail(f"test text to {number}: no delivery (exit {code} from sms send)")
        return 1
    report.ok(f"test text to {number}: the phone sent it")
    if args.wait_reply <= 0:
        print("Ask the person at that number to reply, then look for an `sms.received` from it.", file=report.out)
        return 0
    print(f"Waiting up to {args.wait_reply} s for a reply from {number}...", file=report.out, flush=True)
    reply = wait_for_reply(journal, offset, number, args.wait_reply)
    if reply is None:
        report.fail(f"reply from {number}: nothing arrived in {args.wait_reply} s")
        return 1
    label = "roster" if reply.get("roster_match") else "not on the roster"
    report.ok(f"reply from {number}: arrived ({label}), {reply.get('event_id', '')}")
    return 0
