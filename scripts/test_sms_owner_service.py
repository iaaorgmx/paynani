#!/usr/bin/env python3
"""
Tests for sms/owner.py: the owner's text-message rules shared by PaynaniWeb and the
owner API (PaynaniWebMT PRD #2, FR-A6; paynani#722). An assertion script, like the
rest of this suite. Nada sale de la máquina: las órdenes quedan en un estado temporal.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))

from paynani_lib.sms import outgoing  # noqa: E402
from paynani_lib.sms import owner  # noqa: E402
from paynani_lib.sms import store as sms_store  # noqa: E402

passed = failed = 0


def check(label, expected, actual=True):
    global passed, failed
    if expected == actual:
        passed += 1
        print(f"ok   {label}")
    else:
        failed += 1
        print(f"FAIL {label}\n     expected {expected!r}\n     got      {actual!r}")


def raises(fn, exc):
    try:
        fn()
    except exc as e:
        return e
    return None


os.environ.pop("PAYNANI_WEB_AGENT_PAUSE_MIN", None)
os.environ["PAYNANI_WEB_SMS_PER_HOUR"] = "3"
state = Path(tempfile.mkdtemp()) / "state"
state.mkdir()
st = sms_store.Store(state)
ANA = "+525511112222"

# --- phone_state (FR-6) ------------------------------------------------------------
check("sin teléfono: no_phone", owner.PHONE_NONE, owner.phone_state(st))
st.save_device({"device_id": "d_1", "sims": [{"slot": 0, "country": "MX"}]})
check("teléfono que no anuncia órdenes del dueño: old_app", owner.PHONE_OLD, owner.phone_state(st))
st.touch(accepts_owner_out=True)
check("teléfono que las acepta: ok", owner.PHONE_OK, owner.phone_state(st))
st.touch(sms=False)
check("teléfono sólo Webchat: no_sms_phone", owner.PHONE_NO_SMS, owner.phone_state(st))
st.touch(sms=True)

# --- region y normalize (FR-2) -------------------------------------------------------
check("la región sale de la SIM", "MX", owner.region(st))
check("un número local se normaliza con esa región", ANA, owner.normalize(st, "55 1111 2222"))
check("un número que no sirve: Refused",
      True, raises(lambda: owner.normalize(st, "hola"), outgoing.Refused) is not None)

# --- offline_ttl (FR-7) -------------------------------------------------------------
check("sin estado ok no vence nada", 0, owner.offline_ttl(state, owner.PHONE_OLD))
check("teléfono ok pero sin conexión: vence en DEFAULT_TTL_MIN",
      outgoing.DEFAULT_TTL_MIN, owner.offline_ttl(state, owner.PHONE_OK))

# --- send ---------------------------------------------------------------------------
order = owner.send(st, ANA, "hola\r\nAna", pause=True, source="203.0.113.7")
check("la orden es del dueño", "owner", order.get("origin"))
check("CRLF pasa a LF", "hola\nAna", order.get("text"))
check("con pause lleva los minutos de pausa", True, bool(order.get("agent_pause_min")))
plain = owner.send(st, ANA, "otra", pause=False, source="203.0.113.7")
check("sin pause no pausa", True, not plain.get("agent_pause_min"))
st.touch(accepts_owner_out=False)
err = raises(lambda: owner.send(st, ANA, "x", pause=False, source="203.0.113.7"), owner.NotReady)
check("teléfono viejo: NotReady con su estado", owner.PHONE_OLD, getattr(err, "state", None))
st.touch(accepts_owner_out=True)
owner.send(st, ANA, "tercera", pause=False, source="203.0.113.7")
err = raises(lambda: owner.send(st, ANA, "cuarta", pause=False, source="203.0.113.7"), outgoing.Refused)
check("el tope por hora de la web se aplica", "rate_limited", getattr(err, "code", None))

# --- statuses (FR-5) ------------------------------------------------------------------
res = owner.statuses(st, state, ANA)
check("statuses trae las claves de la web", ["count", "items", "offline"], sorted(res))
check("sólo mensajes de la web (w_)", True, all(i["id"].startswith("w_") for i in res["items"]))
check("cada uno con id, status y error", True,
      all(sorted(i) == ["error", "id", "status"] for i in res["items"]))
check("teléfono desconectado: offline", True, res["offline"])
check("sin número: vacío", 0, owner.statuses(st, state, "")["count"])

# --- set_opt_out ----------------------------------------------------------------------
check("dar de baja cambia", True, owner.set_opt_out(st, ANA, True, by="web:203.0.113.7"))
check("dar de baja otra vez no cambia", False, owner.set_opt_out(st, ANA, True, by="web:203.0.113.7"))
check("dar de alta cambia", True, owner.set_opt_out(st, ANA, False, by="web:203.0.113.7"))

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
