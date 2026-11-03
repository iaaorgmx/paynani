# Webchat

El dueño platica con su propio agente desde PaynaniWeb (#648). Este documento es el
contrato entre el núcleo (`scripts/paynani_lib/webchat/store.py`) y la web (`/webchat`),
acordado en el issue.

## 1. Sin servicio ni socket

Webchat no tiene nadie de afuera: el dueño escribe desde PaynaniWeb y el agente contesta
desde la terminal, en el mismo host y con el mismo usuario. Por eso no hay un servicio
`paynani-webchat` ni un `control.sock`. La web importa `webchat/store.py` y la CLI usa
el mismo módulo. Un `flock` en `state/webchat/lock` ordena las escrituras.

Es sólo para el dueño, con su sesión de PaynaniWeb, y con su propio agente (Q307). No es
para clientes, no hay widget para otra página y no hay API externa.

## 2. Carpetas

```
state/webchat/                 0700
  lock                         0600  flock de las escrituras
  messages.jsonl               0600  un mensaje por línea, sólo se agrega
  files/f_<32 hex>             0600  los adjuntos de los dos lados, con nombre opaco
  outbox/                      0700  de aquí toma archivos `paynani webchat send --file`
  typing.json                  0600  {"until": "…Z"} mientras el agente escribe
  draft.json                   0600  {"text", "at"} el borrador de `webchat send --stream`
```

- **Nada de esto se sirve directo por la web.** Las fotos y los archivos salen por
  `/webchat/file?ref=f_…`, que usa `file_path()`.
- **El nombre original** de un archivo sólo vive en `files[].name`. Nunca llega a una
  ruta del disco.

## 3. El mensaje

```json
{"id": "w_<32 hex>", "dir": "in", "by": "owner", "at": "2026-11-01T16:20:05Z",
 "text": "¿Cómo vamos con el pedido?",
 "files": [{"n": 0, "name": "factura.pdf", "kind": "document", "size": 81234, "ref": "f_<32 hex>"}],
 "event_id": "wc:<los mismos 32 hex>"}
```

- `dir`: `in` lo escribe el dueño y `out` el agente. `by`: `owner` o `agent`.
- `kind`: `image` (se ve en la burbuja) o `document` (tarjeta para descargar).
- `event_id` sólo lo llevan los `in`. Son los mismos hex del `id`.
- En el disco cada archivo guarda además su tipo real (`type`). `messages()` no lo
  devuelve; `file_path()` lo usa para el MIME.

### Límites

| Qué | Límite | Error |
|---|---|---|
| Texto | 4000 caracteres | `too_long` |
| Un archivo | 20 MB | `too_big` |
| Un mensaje | 25 MB en total | `too_big` |
| Mensaje sin texto ni archivos | — | `empty` |
| Tipos | imágenes `jpg`/`jpeg`, `png`, `webp`, `gif`; `pdf`, `txt`, `csv`, `docx`, `xlsx`, `zip` | `bad_type` |

El tipo se revisa por los bytes y tiene que coincidir con la extensión del nombre: un PNG
llamado `.pdf`, un `.docx` con macros, un binario llamado `.txt` o un `.docx` renombrado
a `.zip` se rechazan. Los OOXML se revisan con `telegram/media.py`, igual que en Telegram.
Un rechazo no deja ni archivos ni mensaje.

## 4. Funciones del módulo

```python
from paynani_lib.webchat import store

store.append(by, text, files, *, owner=None, rules=None, state_dir=None) -> dict
store.messages(after=None, limit=50, before=None, *, state_dir=None) -> list[dict]
store.file_path(ref, *, state_dir=None) -> tuple[Path, str, str] | None
store.typing(seconds=60, *, state_dir=None) -> None
store.typing_off(*, state_dir=None) -> None
store.is_typing(now=None, *, state_dir=None) -> bool
store.draft(now=None, *, state_dir=None) -> dict | None
store.draft_set(text, *, state_dir=None) -> None
store.draft_clear(*, state_dir=None) -> None
store.message_for_event(event_id, *, state_dir=None) -> dict | None
```

- **`append(by, text, files)`**: `files` es `[(nombre, bytes)]`. Con `by="owner"` pide
  `owner={"name", "email"}` (el usuario de la sesión de PaynaniWeb) y escribe el evento
  de la sección 5. Con `by="agent"` no hay evento y se quita «escribiendo…». Un error del
  mensaje es `store.Rejected` con `code` en `empty`, `too_long`, `too_big` o `bad_type`.
  Un `by` desconocido, o el dueño sin `owner`, es `ValueError`: es un error de quien llama.
- **`messages()`**: en orden. `after=<id>` da sólo los posteriores, para refrescar;
  `before=<id>` da los anteriores, para «Mensajes anteriores». Siempre los últimos
  `limit` del rango. Una línea rota de `messages.jsonl` se salta.
- **`file_path(ref)`**: `(ruta, mime, nombre original)`, o `None` si el `ref` no tiene el
  formato `f_<32 hex>` o no existe. La web lo transmite con `Content-Disposition`: las
  imágenes `inline` y lo demás como `attachment`, las dos con `nosniff` y `no-store`.
- **`is_typing()`**: «escribiendo…» mientras `typing.json` siga vigente, o mientras el
  último mensaje sea del dueño y su evento esté `dispatched` o `presented`, por 10
  minutos como máximo. `typing(seconds)` acepta de 1 a 600 s. Un borrador vigente
  también cuenta.
- **`draft()`**: `{"text", "at"}` de la respuesta que el agente va escribiendo con
  `--stream`, o `None`. Es el texto completo hasta ese momento, no sólo lo nuevo: el
  servidor del WebSocket manda como `message.delta` lo que cambió desde su último envío.
  `append("agent", …)` lo borra bajo el mismo lock en que guarda el mensaje final, y uno
  sin cambios por más de 10 minutos cuenta como `None`.

La web ya validó la sesión y el CSRF antes de llamar: el módulo confía en ese llamado y no
vuelve a pedir contraseña. `state_dir` sale de `paths.state_dir()`; las pruebas lo pasan.

## 5. El evento `webchat.received`

```json
{"schema_version": 1, "event_type": "webchat.received", "event_id": "wc:<32 hex>",
 "source": "paynani", "channel": "webchat", "account": "webchat",
 "observed_at": "2026-11-01T16:20:05Z", "sent_at": "2026-11-01T16:20:05Z", "kind": "mixed",
 "sender": {"name": "Julian Flores", "address": "<correo del dueño>"},
 "roster_match": true, "authenticated_sender": true,
 "provider_id": "webchat:<32 hex>",
 "inspection_command": "scripts/paynani event show wc:<32 hex>",
 "notification_text": "[webchat 10:20:05, roster] Julian Flores (PaynaniWeb): [documento: factura.pdf] ¿Cómo vamos con el pedido? [scripts/paynani event show wc:…]"}
```

- **El aviso termina en `, roster]` a propósito.** Los hooks de Claude Code y Codex, la
  regla de OpenClaw y `AGENTS.md` ya tratan `, roster]` como trabajo, así que ningún
  runtime necesita aprender una etiqueta nueva. «(PaynaniWeb)» dice de dónde viene.
- **`sender.address`** es el correo del dueño, el de su fila del roster, para que
  `reglas:` encuentre sus reglas como en los otros canales.
- **`kind`**: `text`, `image`, `document` o `mixed`. El aviso marca los adjuntos como en
  WhatsApp: `[foto]`, `[documento: factura.pdf]`. El extracto pasa por `safe_excerpt`, así
  que un salto de línea en el texto no fabrica una línea falsa.
- `append()` escribe el evento en `events.jsonl` y su `observed` en `lifecycle.jsonl`.

## 6. Lo que hace el agente (W-2)

- `scripts/paynani webchat send "<texto>" [--file <ruta>]…`: contesta, quita
  «escribiendo…» y marca `replied` cada `webchat.received` abierto que llegó antes
  (si el dueño mandó tres y el agente contesta una vez, la respuesta es de los tres).
  Los que ya están `handled`, `replied` o `closed` no se tocan. Sin texto lee stdin.
- `scripts/paynani webchat send --stream`: lee stdin mientras llega, lo deja en
  `draft.json` cada 0.3 s y al final guarda el mensaje.
- `scripts/paynani webchat typing [--seconds N] [--off]`.
- `scripts/paynani webchat thread [--limit N]`: la conversación, con los mensajes del
  agente.
- `scripts/paynani event show wc:… --body`: el texto completo y la ruta local de cada
  adjunto, para que el agente los lea.

## 7. PaynaniWeb (Iris)

- `GET /webchat`, en la sección «AI Agent» del menú, con los últimos 20 mensajes (#680; antes 50) y
  «Mensajes anteriores», que se pide solo al llegar arriba con el scroll.
- `POST /webchat/enviar`: `multipart/form-data` con CSRF y Origin; el tamaño se revisa
  antes de leer el cuerpo. Llama a `append("owner", …)`.
- `GET /webchat/updates?after=w_…`: `{messages, typing}`. `assets/webchat.js` lo pide
  cada 3 s, sólo con la pestaña visible.
- `GET /webchat/updates?before=w_…`: «Mensajes anteriores» (Q336 = A), `{html, before,
  more}` con los 20 de antes, que webchat.js pone arriba sin mover lo que se está viendo.
- `GET /webchat/file?ref=f_…`: la descarga.
- La página «AI Agent» (#644) cuenta los `webchat.received` en «Atendidos hoy», la
  mediana, la última respuesta y la actividad.

En v1 la conversación no se borra.
