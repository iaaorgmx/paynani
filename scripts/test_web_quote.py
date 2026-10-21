#!/usr/bin/env python3
"""
Tests for folding the quoted text of a mail in PaynaniWeb (PRD #455 4.5; T2 of
#456). An assertion script, like the rest of this suite.

Los correos de prueba copian la forma exacta en que Gmail, Outlook y Apple Mail
citan (atribución partida en dos líneas, línea en blanco antes de la cita, la
cabecera de Outlook sin `>`), con nombres y direcciones de ejemplo.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))

from paynani_lib.web import mail, quote  # noqa: E402

passed = failed = 0


def check(label, expected, actual=True):
    global passed, failed
    if expected == actual:
        passed += 1
        print(f"ok   {label}")
    else:
        failed += 1
        print(f"FAIL {label}\n     expected {expected!r}\n     got      {actual!r}")


def kinds(text):
    return [k for k, _ in quote.split(text)]


def part(text, kind):
    return next((body for k, body in quote.split(text) if k == kind), None)


# --- Gmail, texto plano: la atribución partida en dos líneas, la firma antes ----------------
GMAIL_ES = """Ana,

Muchas gracias por el pronóstico.

¿Crees que llueva el viernes?

--
Beto Ruiz
Sent from a mobile device

El mié, 21 oct 2026 a las 12:27, Ana Pérez (<ana.perez@example.com>)
escribió:

> Hola Beto,
>
> Este es el pronóstico de los siguientes 5 días:
>
> - Jueves 22: llovizna, máx 20 °C
>
"""
check("Gmail (es): el texto a la vista y la cita plegada", ["text", "quote"], kinds(GMAIL_ES))
check("... la firma se queda a la vista", True, part(GMAIL_ES, "text").endswith("--\nBeto Ruiz\nSent from a mobile device"))
check("... la cita empieza en la atribución, con sus dos líneas", True,
      part(GMAIL_ES, "quote").startswith("El mié, 21 oct 2026 a las 12:27, Ana Pérez (<ana.perez@example.com>)\nescribió:"))
check("... y lleva todas las líneas con >", True, "> - Jueves 22: llovizna, máx 20 °C" in part(GMAIL_ES, "quote"))

GMAIL_EN = """Thanks!

On Wed, Oct 21, 2026 at 12:27 PM Ana Perez <ana.perez@example.com> wrote:

> Hi,
> here is the forecast.
"""
check("Gmail (en), en una línea", (["text", "quote"], "Thanks!"), (kinds(GMAIL_EN), part(GMAIL_EN, "text")))

GMAIL_EN_WRAPPED = """Sounds good.

On Wed, Oct 21, 2026 at 12:27 PM Ana Perez from the Sales Department <
ana.perez@example.com> wrote:

> Hi,
"""
check("Gmail (en), partida en dos con el < al final", ["text", "quote"], kinds(GMAIL_EN_WRAPPED))

# --- Apple Mail: «On … at …, X wrote:» y una línea en blanco antes de la cita ---------------
APPLE_EN = """See you there.

Sent from my iPhone

> On Oct 21, 2026, at 12:27 PM, Ana Perez <ana.perez@example.com> wrote:
>
> Hi,
> are you coming?
"""
check("Apple Mail (en): la atribución ya va con > y se pliega todo el final", (["text", "quote"], "See you there.\n\nSent from my iPhone"),
      (kinds(APPLE_EN), part(APPLE_EN, "text")))

APPLE_ES = """Ahí nos vemos.

El 21 oct 2026, a las 12:27, Ana Pérez <ana.perez@example.com> escribió:


> Hola,
> ¿vienes?
"""
APPLE_ES = APPLE_ES.replace("﻿\n", "\n")
check("Apple Mail (es): atribución, línea en blanco y la cita", (["text", "quote"], "Ahí nos vemos."),
      (kinds(APPLE_ES), part(APPLE_ES, "text")))

# --- Outlook: la cabecera sin >, de ahí al final --------------------------------------------
OUTLOOK_EN = """Approved, go ahead.

Regards,
Carla

________________________________
From: Ana Perez <ana.perez@example.com>
Sent: Wednesday, October 21, 2026 12:27 PM
To: Carla Gomez <carla@example.com>
Subject: Budget

Hi Carla,
can you approve the budget?
"""
check("Outlook (en): la raya y la cabecera From/Sent/To/Subject se pliegan hasta el final",
      (["text", "quote"], "Approved, go ahead.\n\nRegards,\nCarla"), (kinds(OUTLOOK_EN), part(OUTLOOK_EN, "text")))
check("... la cita empieza en la raya", True, part(OUTLOOK_EN, "quote").startswith("________________________________\nFrom: Ana"))

OUTLOOK_ES = """Aprobado.

-----Mensaje original-----
De: Ana Pérez <ana.perez@example.com>
Enviado el: miércoles, 21 de octubre de 2026 12:27
Para: Carla Gómez <carla@example.com>
Asunto: Presupuesto

Hola Carla,
"""
check("Outlook (es): «-----Mensaje original-----» y De/Enviado/Para/Asunto",
      (["text", "quote"], "Aprobado."), (kinds(OUTLOOK_ES), part(OUTLOOK_ES, "text")))

# --- un reenvío no es una cita (revisión de #458) -----------------------------------------
FORWARDS = (
    ("Gmail (en)", "---------- Forwarded message ---------", "From", "Date", "Subject", "To"),
    ("Gmail (es)", "---------- Mensaje reenviado ---------", "De", "Fecha", "Asunto", "Para"),
    ("Gmail (fr)", "---------- Message transféré ---------", "De", "Date", "Subject", "To"),
    ("Gmail (pt)", "---------- Mensagem encaminhada ---------", "De", "Data", "Assunto", "Para"),
    ("Gmail (de)", "---------- Weitergeleitete Nachricht ---------", "Von", "Date", "Betreff", "An"),
    ("Apple Mail (en)", "Begin forwarded message:", "From", "Subject", "Date", "To"),
    ("Apple Mail (es)", "Inicio del mensaje reenviado:", "De", "Asunto", "Fecha", "Para"),
    ("Apple Mail (fr)", "Début du message réexpédié :", "De", "Objet", "Date", "À"),
    ("Apple Mail (pt)", "Início da mensagem encaminhada:", "De", "Assunto", "Data", "Para"),
)
for label, separator, f1, f2, f3, f4 in FORWARDS:
    forward = (f"Metis, revisa este correo del cliente.\n\n{separator}\n{f1}: Ana Ruiz <ana@example.com>\n"
               f"{f2}: Wed, Oct 21, 2026 at 11:00 AM\n{f3}: Pedido\n{f4}: Beto <beto@example.com>\n\n"
               "Hola, necesito 3 cajas para el viernes.\nGracias, Ana\n")
    check(f"un reenvío de {label} se ve completo, sin plegar", (["text"], True),
          (kinds(forward), "necesito 3 cajas" in part(forward, "text")))
check("«-----Original Message-----» de Outlook sigue siendo cita", ["text", "quote"],
      kinds("Va.\n\n-----Original Message-----\nFrom: Ana <a@example.com>\nSent: Wed\nTo: Beto\nSubject: X\n\nHola\n"))
REPLY_TO_FORWARD = ("Ya lo vi.\n\nOn Wed, Oct 21, 2026 at 11:05 AM Beto <beto@example.com> wrote:\n\n"
                    "> ---------- Forwarded message ---------\n> From: Ana <ana@example.com>\n> Date: Wed\n> Subject: X\n>\n> Hola\n")
check("la respuesta a un reenvío: la cita (con el reenvío adentro) se pliega", (["text", "quote"], "Ya lo vi."),
      (kinds(REPLY_TO_FORWARD), part(REPLY_TO_FORWARD, "text")))

# --- otros idiomas --------------------------------------------------------------------------
for label, attribution in (("fr", "Le mer. 21 oct. 2026 à 12:27, Ana Perez <ana@example.com> a écrit :"),
                           ("pt", "Em qua., 21 de out. de 2026 às 12:27, Ana Perez <ana@example.com> escreveu:"),
                           ("de", "Am Mi., 21. Okt. 2026 um 12:27 Uhr schrieb Ana Perez <ana@example.com>:")):
    text = f"Merci.\n\n{attribution}\n\n> Bonjour\n"
    check(f"atribución en {label}", ["text", "quote"], kinds(text))

# --- lo que no es cita se queda ---------------------------------------------------------------
PLAIN = "Hola,\n\nOn Friday I travel to CDMX.\nEl viernes salgo temprano.\n\n--\nBeto"
check("sin cita: un solo bloque, aunque una línea empiece con «On» o «El»", [("text", PLAIN)], quote.split(PLAIN))
ATTR_NO_QUOTE = "Mira lo que dijo:\n\nOn Monday Ana wrote: nothing.\n\nFin."
check("una «… wrote:» sin líneas con > después no se pliega", ["text"], kinds(ATTR_NO_QUOTE))
INLINE = """> ¿Vienes el viernes?
Sí, llego a las 10.

> ¿Traes la sombrilla?
Sí.
"""
check("respuestas intercaladas: las > con texto después se quedan a la vista", ["text"], kinds(INLINE))
TRAIL = "Va.\n\n> lo de antes\n> y más\n"
check("unas > al final sin atribución se pliegan", (["text", "quote"], "Va."), (kinds(TRAIL), part(TRAIL, "text")))
OUTLOOK_LIKE = "From: the beginning I said so.\nThanks."
check("un «From:» sin los otros campos de Outlook no se pliega", ["text"], kinds(OUTLOOK_LIKE))
check("vacío: nada", [], quote.split(""))
check("solo una cita: solo la parte plegada", ["quote"], kinds("On Mon, Ana <a@example.com> wrote:\n> hola\n"))

# --- la cita de la parte HTML -----------------------------------------------------------------
HTML = """<div dir="ltr">Gracias, Ana.<div><br></div><div>--<br>Beto</div></div><br>
<div class="gmail_quote"><div dir="ltr" class="gmail_attr">El mié, 21 oct 2026 a las 12:27, Ana Pérez
(&lt;<a href="mailto:ana@example.com">ana@example.com</a>&gt;) escribió:<br></div>
<blockquote class="gmail_quote" style="margin:0px 0px 0px 0.8ex">Hola Beto,<br><br>El pronóstico:<br>
<div>- Jueves 22: llovizna</div></blockquote></div>"""
text = mail.html_to_text(HTML)
check("HTML de Gmail: html_to_text pone > en lo citado", True,
      "> Hola Beto," in text and "> - Jueves 22: llovizna" in text and "> Gracias" not in text)
check("... y split lo pliega, con la firma a la vista", (["text", "quote"], "Gracias, Ana.\n\n--\nBeto"),
      (kinds(text), part(text, "text")))
APPLE_HTML = '<div>Ahí nos vemos.</div><div><br><blockquote type="cite">El 21 oct 2026, Ana escribió:<br><br>¿vienes?</blockquote></div>'
check("HTML de Apple Mail (<blockquote type=cite>)", (["text", "quote"], "Ahí nos vemos."),
      (kinds(mail.html_to_text(APPLE_HTML)), part(mail.html_to_text(APPLE_HTML), "text")))
check("un HTML sin cita no cambia", "Hola\n\nmundo", mail.html_to_text("<p>Hola</p><p>mundo</p>"))
check("los marcadores de cita que traiga el correo se van y no abren una cita", "Hola\n\nmundo",
      mail.html_to_text("<p>Hola\x01</p><p>\x02mundo</p>"))
check("un div cualquiera dentro de la cita no la cierra antes de tiempo", True,
      "> - Jueves 22: llovizna" in mail.html_to_text(HTML))

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
