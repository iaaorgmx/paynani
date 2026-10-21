"""
El texto citado de un correo, para plegarlo detrás de «•••» como Gmail (PRD #455,
4.5; T2 de #456).

Una respuesta suele repetir el mensaje anterior. Lo que se pliega es:

- **Una atribución seguida de líneas con `>`**: «On … wrote:», «El … escribió:»,
  «Le … a écrit :», «Em … escreveu:», «Am … schrieb:». Gmail parte la línea larga
  en dos o tres; se leen juntas. Entre la atribución y la primera `>` puede haber
  líneas en blanco (Apple Mail deja una).
- **Las líneas con `>` del final**, aunque no traigan atribución.
- **La cabecera de Outlook**: «From: … / Sent: … / To: … / Subject: …» (o «De: … /
  Enviado: … / Para: … / Asunto: …»), con la raya o «-----Original Message-----»
  de antes si la hay. Outlook no pone `>`, así que se pliega de ahí al final. La
  misma cabecera después de «---------- Forwarded message ---------» o «Begin
  forwarded message:» es un reenvío y se queda a la vista.
- **La cita en la parte HTML** (`<div class="gmail_quote">`, `<blockquote>`):
  `mail.html_to_text()` ya la entrega con `> ` delante de cada línea, así que la
  regla de las `>` la pliega igual.

La firma (`-- ` y lo que sigue) nunca se pliega: va antes de la cita, y lo que no
es cita se queda a la vista.
"""
from __future__ import annotations

import re

ATTRIBUTION = re.compile(
    r"^\s*(on|el|le|em|am)\b.{0,400}?\b(wrote|escribió|escribio|a\s+écrit|escreveu|schrieb)\s*:\s*$",
    re.IGNORECASE | re.DOTALL)
OUTLOOK_FROM = re.compile(r"^\s*\*?(from|de|von)\s*:\*?\s+\S", re.IGNORECASE)
OUTLOOK_FIELDS = re.compile(
    r"^\s*\*?(sent|date|enviado|enviada|fecha|data|envoyé|gesendet|to|para|à|an|subject|asunto|assunto|objet|betreff)"
    r"\s*:\*?", re.IGNORECASE)
OUTLOOK_RULE = re.compile(r"^\s*(_{10,}|-{3,}\s*(original message|mensaje original|message d'origine|"
                          r"mensagem original|ursprüngliche nachricht)\s*-{3,})\s*$", re.IGNORECASE)
# Lo que va antes de la cabecera de un reenvío. Un reenvío no es una cita: es lo que el
# dueño le pasa al agente para que lo lea, y Gmail lo muestra completo (revisión de #458).
# «-----Original Message-----» no está: Outlook lo pone al responder.
FORWARD = re.compile(
    r"^\s*(-{3,}\s*(forwarded message|mensaje reenviado|message transféré|mensagem encaminhada|"
    r"weitergeleitete nachricht)\s*-{3,}|begin forwarded message\s*:|inicio del mensaje reenviado\s*:|"
    r"début du message réexpédié\s*:|início da mensagem encaminhada\s*:|anfang der weitergeleiteten nachricht\s*:)\s*$",
    re.IGNORECASE)
JOIN = 3   # líneas en que Gmail puede partir una atribución larga


def _quoted(line: str) -> bool:
    return line.lstrip().startswith(">")


def _blank(line: str) -> bool:
    return not line.strip()


def _attribution_at(lines: list[str], i: int) -> int:
    """Si en `i` empieza una atribución (de 1 a JOIN líneas) seguida, tras blancos, de
    una línea con `>`, cuántas líneas ocupa la atribución; si no, 0."""
    for n in range(1, JOIN + 1):
        if i + n > len(lines) or any(_quoted(l) or _blank(l) for l in lines[i:i + n]):
            return 0
        if ATTRIBUTION.match(" ".join(l.strip() for l in lines[i:i + n])):
            j = i + n
            while j < len(lines) and _blank(lines[j]):
                j += 1
            return n if j < len(lines) and _quoted(lines[j]) else 0
    return 0


def _outlook_at(lines: list[str], i: int) -> bool:
    """Una cabecera de Outlook empieza en `i`: «From:» y, en las cuatro siguientes, al menos
    dos campos más (fecha, para, asunto). No si es la de un reenvío: la línea con texto de
    antes es «---------- Forwarded message ---------» o «Begin forwarded message:»."""
    if not OUTLOOK_FROM.match(lines[i]):
        return False
    j = i - 1
    while j >= 0 and _blank(lines[j]):
        j -= 1
    if j >= 0 and FORWARD.match(lines[j]):
        return False
    fields = sum(bool(OUTLOOK_FIELDS.match(l)) for l in lines[i + 1:i + 5])
    return fields >= 2


def split(text: str) -> list[tuple[str, str]]:
    """
    El cuerpo en partes, en orden: `("text", …)` lo que se ve y `("quote", …)` lo que se
    pliega. Juntas dan el texto original, salvo los blancos de los bordes de cada parte.
    """
    # Gmail manda el cuerpo con \r\n: sin esto, cada línea visible acababa en \r y se
    # veía un hueco antes de «•••» (T5 de #456).
    lines = (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    parts: list[tuple[str, str]] = []
    visible: list[str] = []

    def flush(kind: str, chunk: list[str]):
        body = "\n".join(chunk).strip("\n")
        if body.strip():
            parts.append((kind, body))

    i = 0
    while i < len(lines):
        n = _attribution_at(lines, i)
        if n:
            j = i + n
            while j < len(lines) and (_quoted(lines[j]) or _blank(lines[j])):
                j += 1
            flush("text", visible)
            visible = []
            flush("quote", lines[i:j])
            i = j
            continue
        start = i - 1 if i and OUTLOOK_RULE.match(lines[i - 1]) else i
        if _outlook_at(lines, i):
            if start < i:
                visible.pop()
            flush("text", visible)
            visible = []
            flush("quote", lines[start:])
            return parts
        if _quoted(lines[i]):
            j = i
            while j < len(lines) and (_quoted(lines[j]) or _blank(lines[j])):
                j += 1
            block = lines[i:j]
            # Unas líneas con `>` en medio, con texto después, son una respuesta
            # intercalada: se quedan a la vista. Las del final se pliegan.
            if j >= len(lines) and sum(_quoted(l) for l in block) >= 1:
                flush("text", visible)
                visible = []
                flush("quote", block)
                return parts
            visible.extend(block)
            i = j
            continue
        visible.append(lines[i])
        i += 1
    flush("text", visible)
    return parts
