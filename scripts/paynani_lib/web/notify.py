"""
Los correos al dueño (PRD #434 FR-9): una entrada desde una dirección nueva, y
después cada cambio al roster, a las reglas o a las cuentas hecho desde la web.

Salen por `scripts/send.sh`, como los de la pasarela (`roster_api.send_sh_notifier`),
que vuelve a comprobar al destinatario contra roster.md. En un hilo aparte: un
correo que tarda no detiene la página. Si no sale, queda una línea en el log de
PaynaniWeb, sin el cuerpo.
"""
from __future__ import annotations

import sys
import threading
import time

from ..sms import roster_api


class Notifier:
    def __init__(self, send=None, log=None):
        # send(to, subject, body); las pruebas pasan uno que anota.
        self.send = send or roster_api.send_sh_notifier
        self.log = log or (lambda line: print(f"paynani-web: {line}", file=sys.stderr, flush=True))
        self.threads: list[threading.Thread] = []

    def owner(self, user: dict | None, subject: str, body: str) -> None:
        to = (user or {}).get("email", "")
        if not to:
            self.log(f"aviso sin destinatario ({subject})")
            return

        def run():
            try:
                self.send(to, subject, body)
            except Exception as exc:  # noqa: BLE001 -- cualquier falla de send.sh se dice y ya
                self.log(f"no salió el aviso al dueño «{subject}» ({type(exc).__name__})")

        t = threading.Thread(target=run, daemon=True)
        t.start()
        self.threads.append(t)
        self.threads = [x for x in self.threads if x.is_alive()]

    def wait(self, timeout: float = 5.0) -> None:
        """Para las pruebas: espera a que salgan los avisos en curso."""
        end = time.time() + timeout
        for t in list(self.threads):
            t.join(max(0.0, end - time.time()))

