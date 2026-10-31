# Telegram: el servicio, su interfaz y el contrato con PaynaniWeb y PaynaniApp

Este documento es el contrato de TG-0 (#612) para el PRD #609. Dice cómo habla el
servicio `paynani-telegram` con la Bot API, qué escribe en `events.jsonl`, qué
contesta en su `control.sock` (la CLI, el agente, PaynaniWeb y la pasarela SMS) y
qué se habla con PaynaniApp. Iris (TG-7) y Andy (TG-8) programan contra este texto y
contra el servidor falso de la sección 9, sin esperar al servicio real.

Las referencias `FR-n` son del PRD #609.

## 1. Piezas y carpetas

```
telegram.env                         0600  token y switches (FR-8), junto a runtime.env
state/telegram/                      0700
  lock                               candado de instancia (flock), FR-3
  control.sock                       0600  interfaz local, sección 4
  status.json                        0600  último estado (para doctor y el cliente con el servicio caído)
  media/                             0700  archivos recibidos (FR-18), 0600 cada uno
  outbox/                            0700  archivos que se pueden mandar (FR-20), con TELEGRAM_ATTACH_DIRS
  rate.json                          0600  mensajes mandados hoy (UTC) en toda la instalación (FR-26)
  bots/<bot>/                        0700  estado de un bot (FR-3a); <bot> = sha256(bot_id)[:16]
    account.json                     0600  alias aleatorio del bot para `account` (sección 3)
    offset.json                      0600  siguiente offset de getUpdates (FR-4)
    journal.jsonl                    0600  update_id, ref, hash, written (FR-5)
    links.json                       0600  @usuario -> id fijado (FR-13) y a qué otros ids se avisó
    inbox/<ref>.json                 0600  texto y datos de cada mensaje recibido
    outbox.jsonl                     0600  lo que se mandó, por hilo (una línea por cambio de estado)
    chats.json                       0600  hilo -> chat privado y nombre que muestra Telegram (FR-15, FR-25)
  active                             0600  el <bot> en uso; un cambio de token lo reemplaza (FR-10)
```

- **Nada de esto se sirve por la web.** PaynaniWeb pide los datos por `control.sock`.
- **Los ids de Telegram** (`update_id`, `chat.id`, `from.id`, `message_id`, `file_id`)
  sólo viven dentro de `bots/<bot>/`. No salen en `events.jsonl`, en los logs, en
  `doctor`, en la API ni en las respuestas de `control.sock`, salvo una: la acción
  «Agregar al roster» de PaynaniWeb (FR-15, `telegram.roster_candidate`).
- **`<bot>` no es el `bot_id`**, es un prefijo de su hash. Así el nombre de la carpeta
  no dice qué bot es. Como el `bot_id` es un número y se pueden probar candidatos, el
  `<bot>` tampoco sale de la carpeta `state/telegram/`: no va en eventos, logs,
  `doctor`, la API ni respuestas de `control.sock`.
- **`account.json`** guarda `{"alias": "<16 hex aleatorios>"}`, que el servicio crea
  la primera vez que usa ese bot con `secrets.token_hex(8)`. No se deriva de ningún id.

### El diario y la reconciliación (FR-4, FR-5)

Para cada update de un chat privado, en este orden: se anota en `journal.jsonl`
`update_id`, referencia y hash; se guarda `inbox/<ref>.json` con el mensaje, el hash y
el sobre del evento (`journaled: false`); se escribe el evento en `events.jsonl`; se
marca `journaled: true` y se anota «escrito» en el diario. El offset se guarda después.

`events.jsonl` se compacta y `lifecycle.jsonl` se recorta, así que al arrancar, para cada
entrada del diario sin «escrito», se busca en este orden:

1. un evento con esa referencia en `events.jsonl`: si el hash coincide, se marca
   escrita; si no, `journal_mismatch` y no se marca nada;
2. la referencia en `lifecycle.jsonl`: el evento se escribió y ya se compactó; se marca;
3. su `inbox/<ref>.json` con el mismo hash: el evento se rehace desde ahí y se marca;
4. nada: queda pendiente. El offset no avanzó, Telegram lo vuelve a entregar, y si el
   hash coincide se escribe con la misma referencia; si no, `journal_mismatch`.

Los grupos (FR-19), los mensajes de alguien que bloquea al bot y las ediciones de un
mensaje que no está en el inbox no se anotan: sólo avanzan el offset.

## 2. La Bot API

El servicio habla con `https://api.telegram.org` (o con `PAYNANI_TELEGRAM_API`, sólo
para pruebas, sección 9) usando la biblioteca estándar. Sólo usa estos métodos:

| Método | Para qué |
|---|---|
| `getMe` | Validar el token y conocer `bot_id` y `@usuario` (FR-9, FR-10) |
| `getWebhookInfo` | Al arrancar: si hay webhook, `conflict` (FR-3) |
| `deleteWebhook` | Sólo en `setup` o cambio de token, con confirmación (FR-9) |
| `getUpdates` | Recibir. `timeout=30`, `allowed_updates=["message","edited_message","my_chat_member"]` |
| `getFile` y la descarga | Multimedia (FR-18) |
| `sendMessage`, `sendPhoto`, `sendDocument` | Mandar (FR-20) |
| `sendChatAction` | «escribiendo…» (FR-21) |
| `sendMessageDraft` | Streaming y avance (FR-22, FR-24), con `draft_id` distinto de 0 por respuesta |
| `editMessageText` | Streaming cuando `sendMessageDraft` no se acepta (FR-22) |
| `leaveChat` | Grupos, supergrupos y canales (FR-19) |

- **El token va en la ruta de la URL**, como pide la Bot API. Por eso ninguna URL se
  escribe en un log ni en un error: los errores se registran con el método y el código
  HTTP, nunca con la URL.
- `getUpdates` espera hasta 30 s. Si no regresa en 60 s, se corta y se vuelve a abrir
  la conexión (FR-2).
- Errores: `401` → `token_invalid` (FR-7); `409` → `conflict` (FR-3); `429` → se espera
  `parameters.retry_after` (FR-26); red o `5xx` → espera exponencial de 1 a 60 s.

## 3. Lo que entra a `events.jsonl`

### `telegram.received`

```json
{"schema_version": 1, "event_type": "telegram.received",
 "event_id": "tg:9f2c4e1a7b3d4c5e8f9a0b1c2d3e4f50",
 "source": "paynani", "channel": "telegram", "account": "tg:<alias>",
 "observed_at": "2026-11-02T19:10:02Z", "sent_at": "2026-11-02T19:10:01Z",
 "kind": "text", "sender": {"name": "Ana López", "address": ""},
 "roster_match": true, "authenticated_sender": false,
 "provider_id": "telegram:9f2c4e1a7b3d4c5e8f9a0b1c2d3e4f50",
 "inspection_command": "scripts/paynani event show tg:9f2c4e1a7b3d4c5e8f9a0b1c2d3e4f50",
 "notification_text": "[telegram 19:10:02, roster] Ana López: ¿Tienen mesa a las 8? [scripts/paynani event show tg:9f2c…]",
 "_tg_hash": "<sha256 del update canónico>"}
```

- **`event_id` es `tg:` + 32 hex aleatorios** (FR-5). No se deriva de ningún id de
  Telegram. `account` es `tg:` + el alias aleatorio de `account.json` (sección 1),
  nunca el `<bot>` ni algo derivado del `bot_id`. Un cambio de token (otro bot) trae
  otro alias.
- **`sender.address` va vacío.** El contacto se nombra por su fila del roster. Fuera del
  roster, `sender.name` es el nombre que muestra Telegram con «(no verificado)» y
  `address` sigue vacío (FR-17).
- **`_tg_hash`** es el hash de FR-5. Empieza con `_`: `event show`, los avisos, la
  API, PaynaniWeb y la pasarela nunca lo muestran.
- **El texto no va en el evento.** Vive en `bots/<bot>/inbox/<ref>.json` y sale sólo
  con `scripts/paynani event show <id> --body`, con las mismas reglas que WhatsApp:
  del roster, o fuera del roster con el Catch-All de Telegram activo (FR-17).
- **`kind`**: `text`, `image`, `video`, `audio`, `voice`, `document`, `sticker`,
  `location`, `contact` u `other`. El aviso dice el tipo, como WhatsApp (`[foto]`,
  `[documento: factura.pdf]`), y nunca el nombre del archivo fuera del roster.
- `rules` y `catch_all` se agregan igual que en `whatsapp.received`. El Catch-All de
  Telegram es sólo `rules/catch-all-telegram.md`: el viejo `rules/catch-all.md` era de
  SMS y WhatsApp y no abre Telegram, ni se copia a Telegram al migrar (#576 FR-5).
- **`media_rejected`**: `size` o `type` cuando el archivo no pasó FR-18; el aviso lo
  dice (`[documento: factura.pdf, rechazado: tipo]`) y no queda nada en disco. Sólo se
  baja el archivo de alguien del roster, o de fuera con el Catch-All activo; de los
  demás no se pide ni `getFile`.

### Quién es quién (FR-11 a FR-13)

Sólo cuenta `from.id`. En este orden: el id está en la columna `Telegram` de una fila;
o un `@usuario` de la columna ya quedó fijado a ese id en `links.json`; o el
`@usuario` con el que escribe está en la columna y nadie lo ha fijado, y entonces se
fija a este id y el dueño recibe «@usuario quedó vinculado a <contacto>». Si ese
`@usuario` ya está fijado a otro id, no se reconoce y el dueño recibe un aviso, una
vez por id. El vínculo guarda también su fila (el correo, o el nombre si no tiene).
Se borra con el siguiente mensaje si su `@usuario` ya no está en la columna, si quedó
repetido o si ahora está en otra fila: nunca pasa en silencio de un contacto a otro. `doctor` muestra el check
`roster:telegram` con las filas cuyo valor no vale o está repetido, sin el valor.

Las líneas de aviso:

```
[telegram 19:10:02, roster] Ana López: <extracto> [scripts/paynani event show tg:…]
[telegram 19:10:02, reglas: rules/ana-lopez-9b1c.md, roster] Ana López: <extracto> […]
[telegram 19:10:02, catch-all: rules/catch-all-telegram.md] Pedro (no verificado): <extracto> […]
[telegram 19:10:02, catch-all inválido] Pedro (no verificado): mensaje de alguien fuera del roster […]
[telegram 19:10:02] Pedro (no verificado): mensaje de alguien fuera del roster […]
```

### `telegram.edited`

Una edición (FR-16a). Mismo sobre, con su propio `event_id` y un campo más:

```json
{"event_type": "telegram.edited", "event_id": "tg:<ref nueva>", "edits": "tg:<ref del original>", …,
 "notification_text": "[telegram 19:12:40, roster] Ana López editó su mensaje: ¿Tienen mesa a las 9? [scripts/paynani event show tg:…]"}
```

Si el original no está en el diario, no hay evento: sólo sube el contador
`edits_ignored` de `telegram.status`.

### `telegram.health`

Sin remitente, como `whatsapp.health`: `token_invalid`, `conflict`, `offline` (más de
10 minutos sin poder hablar con Telegram), `journal_mismatch` (FR-5, hash distinto) y
`recovered`. La línea dice qué pasó y qué hacer, nunca el token ni un id.

## 4. Interfaz local: `control.sock`

Igual que `WHATSAPP_BRIDGE.md` §11: un socket Unix `0600` en una carpeta `0700`, un
JSON por línea, `id` `q_` + 32 hex, `by` (`terminal`, `agent`, `web`, `phone:<device_id>`
o `api`) que es sólo una etiqueta, y una respuesta `result` o `error` con `ref`.

**Telegram configurado** es un solo predicado, `telegram_config.configured()`: verdadero
sólo si `telegram.env` es un archivo regular, se puede leer, trae `TELEGRAM_ENABLED=1` y
un `TELEGRAM_TOKEN`. Con Telegram configurado y el servicio caído, el cliente contesta
`telegram.status` con `state: "service_down"`.

### Los hilos

Un hilo es una persona. Se nombra con `thread`, un id opaco (`t_` + 32 hex) que el
servicio asigna y guarda en `chats.json`. Nunca es un id de Telegram.

### Los tipos

| `type` | Qué hace | Quién lo usa |
|---|---|---|
| `telegram.status` | Estado del servicio | todos |
| `telegram.threads` | Lista de hilos | web, pasarela, terminal |
| `telegram.thread` | Mensajes de un hilo | web, pasarela, terminal |
| `telegram.send` | Contesta en un hilo | todos |
| `telegram.stream_open`, `telegram.stream_append`, `telegram.stream_close` | Respuesta por partes (FR-22) | terminal (`send --stream`) |
| `telegram.draft` | Borrador de avance (FR-24) | terminal |
| `telegram.image` | La foto de un mensaje recibido | web |
| `telegram.watch` | Avisos sin pedirlos | web, pasarela |
| `telegram.roster_candidate` | El id de alguien fuera del roster, para «Agregar al roster» (FR-15) | sólo web |
| `telegram.token_check` | Prueba un token nuevo con `getMe` (FR-10 paso 1) | web, terminal |
| `telegram.token_apply` | Aplica el token (FR-10 pasos 2 a 5) | web, terminal |

#### `telegram.status`

```json
{"type": "result", "ref": "q_…", "ok": true, "data": {
  "state": "running", "bot_username": "MiNegocioBot", "since": "2026-11-02T18:00:00Z",
  "last_poll_at": "2026-11-02T19:10:30Z",
  "counters": {"received_today": 12, "sent_today": 9, "send_limit_day": 300,
               "edits_ignored": 0, "media_rejected": 1, "groups_left": 0}}}
```

`state`: `starting`, `running`, `offline`, `conflict`, `token_invalid`,
`journal_mismatch`, `stopped` o `service_down`. `conflict` trae
`reason: "webhook"` o `reason: "409"`. Nunca trae el token, el `bot_id` ni ids de
personas.

#### `telegram.threads`

```json
{"type": "telegram.threads", "id": "q_…", "by": "web", "limit": 50, "before": null}
{"type": "result", "ref": "q_…", "ok": true, "data": {
  "threads": [
    {"thread": "t_…", "name": "Ana López", "in_roster": true,
     "last_at": "2026-11-02T19:13:05Z", "last_dir": "out",
     "last_excerpt": "Sí, a las 8 tenemos lugar.", "last_kind": "text", "can_reply": true},
    {"thread": "t_…", "name": "Pedro (no verificado)", "in_roster": false,
     "last_at": "2026-11-02T18:40:11Z", "last_dir": "in",
     "last_excerpt": null, "last_kind": null, "can_reply": false, "hidden": true}],
  "next_before": null}}
```

Igual que `whatsapp.threads` (`SMS_GATEWAY.md` §12), con `thread` en lugar de
`number`. `hidden: true` y `last_excerpt: null` para alguien fuera del roster sin el
Catch-All de Telegram activo.

#### `telegram.thread`

```json
{"type": "telegram.thread", "id": "q_…", "by": "web", "thread": "t_…", "limit": 50, "before": null}
{"type": "result", "ref": "q_…", "ok": true, "data": {
  "thread": "t_…", "name": "Ana López", "in_roster": true, "can_reply": true,
  "messages": [
    {"ref": "tg:…", "dir": "in", "at": "2026-11-02T19:10:01Z", "kind": "text",
     "text": "¿Tienen mesa a las 8?", "edited": false},
    {"ref": "tgo:…", "dir": "out", "at": "2026-11-02T19:13:05Z", "kind": "text",
     "text": "Sí, a las 8 tenemos lugar.", "by": "agent", "status": "sent"}],
  "next_before": null}}
```

- Del más reciente al más viejo, igual que `whatsapp.thread`. `limit` de 1 a 100 (50
  por omisión). Para la página siguiente, con mensajes más viejos, se manda `before`
  con el `next_before` que llegó; `null` es que no hay más. `status` de un mensaje que sale:
  `sending`, `sent` o `failed` (Telegram no da «entregado» ni «leído» a un bot).
- `by` de un mensaje que sale es quién lo escribió, como en `whatsapp.thread`
  (`SMS_GATEWAY.md` §12): `agent` (el agente o la terminal), `owner` (PaynaniWeb o
  PaynaniApp) o `api`. No es la etiqueta `by` de la petición: el servicio convierte
  `web` y `phone:<device_id>` en `owner`.
- `edited: true` en un mensaje que la persona editó; `text` es el último.
- La terminal y el agente pueden pedir el hilo con `contact` en lugar de `thread`.
- Fuera del roster sin Catch-All activo: `messages` va vacío y `hidden: true`.

#### `telegram.send`

```json
{"type": "telegram.send", "id": "q_…", "by": "agent", "thread": "t_…", "text": "…"}
{"type": "telegram.send", "id": "q_…", "by": "terminal", "contact": "Ana López", "text": "…", "file": "/ruta/en/outbox"}
{"type": "result", "ref": "q_…", "ok": true, "data": {"ref": "tgo:…", "status": "sent", "at": "…"}}
```

- `thread` o `contact` (el nombre o el email de la fila del roster). Uno de los dos. Un
  nombre que está en más de una fila da `conflict` y no manda nada: hay que usar el
  correo, que es único.
- `file` sólo de la terminal y del agente, validado siempre contra `outbox/` y las
  carpetas permitidas (FR-20). La web y la pasarela nunca lo mandan.
- El servicio aplica siempre FR-25 y FR-26: contacto del roster con un chat privado
  que la persona abrió, y los límites. Si no, `error` con `not_allowed`,
  `not_started` (la persona nunca le escribió al bot) o `rate_limited` con
  `retry_after_s`.
- Texto de hasta 4096 caracteres por mensaje; más largo se parte en varios, cortando
  en un salto de línea o un espacio. Más de 32768 en un `send` es `invalid`
  (`too_long`). Con `file`, el texto va como pie (hasta 1024); si es más largo, sale
  después del archivo. Un JPEG, PNG o WebP de hasta 10 MB sale con `sendPhoto`; lo
  demás, hasta 50 MB, con `sendDocument`.
- Un mensaje por segundo por chat: el servicio espera ese segundo, no lo rechaza. El
  límite del día (`TELEGRAM_SEND_PER_DAY`, 300) cuenta cada mensaje que queda en el
  chat, en toda la instalación, y se reinicia a medianoche UTC. Se reserva antes de
  mandar y se devuelve lo que no salió, sólo al día de la reserva (un envío de antes de
  medianoche que falla después no resta del día nuevo): un envío que falla no gasta cupo, y uno que
  falla a la mitad queda `partial` con `delivered` y `parts` en `outbox.jsonl`. Pasándolo,
  `rate_limited` con los segundos que faltan. Un 429 espera su `retry_after` y se
  reintenta una vez; si vuelve, `rate_limited`.
- Al mandar, se apaga el «escribiendo…» de ese hilo (FR-21). El «escribiendo…» empieza
  con cada mensaje de un contacto del roster (no con ediciones ni con el Catch-All), se
  repite cada 4 s y se apaga al mandar, al cerrar el agente el evento
  (`handled`, `replied` o `closed`) o a los 2 minutos.

#### Respuesta por partes: `telegram.stream_*`

```json
{"type": "telegram.stream_open", "id": "q_…", "by": "terminal", "contact": "Ana López"}
{"type": "result", "ref": "q_…", "ok": true, "data": {"stream": "s_…"}}
{"type": "telegram.stream_append", "id": "q_…", "stream": "s_…", "text": "Sí, a las "}
{"type": "telegram.stream_close", "id": "q_…", "stream": "s_…"}
{"type": "result", "ref": "q_…", "ok": true, "data": {"ref": "tgo:…", "status": "sent", "transport": "draft"}}
```

- El servicio junta el texto y lo muestra con `sendMessageDraft` cada 0.8 s cuando
  hay al menos 24 caracteres nuevos o pasó 1 s, sin pasar de un cambio por segundo
  por chat. Si Telegram rechaza el borrador, cambia a `editMessageText` sobre un
  mensaje enviado (`transport: "edit"`) para el resto de esa respuesta.
- `stream_close` manda el texto completo como mensaje normal (`sendMessage`), o deja
  el editado como final. Pasando 4096 caracteres sigue en un mensaje nuevo.
- Un `stream` sin `append` en 120 s se cierra solo con lo que tenga. Las mismas
  reglas de `telegram.send` se revisan en `stream_open`.
- `paynani telegram send <contacto> --stream` lee stdin y usa estos tres tipos.
- `stream_append` y `stream_close` no necesitan `by`: el stream lo tomó al abrirse.
- El ritmo: se muestra lo nuevo cuando hay 24 caracteres o más y pasaron 0.8 s, o
  cuando pasó 1 s, pero nunca más de un cambio por segundo en el chat. Lo que quede
  pendiente se muestra en el siguiente cuarto de segundo libre. El borrador no cuenta
  contra el límite del día; cada mensaje que queda al final, sí.

#### `telegram.draft`

```json
{"type": "telegram.draft", "id": "q_…", "by": "terminal", "contact": "Ana López", "text": "Revisando tu pedido…"}
```

Muestra un borrador que reemplaza el siguiente `send` en ese hilo (FR-24). No cuenta
contra los 300 diarios. Si el chat no acepta `sendMessageDraft`, el borrador es un
mensaje que el siguiente `send` edita (`transport: "edit"`).

#### `telegram.image`

Como `whatsapp.image` (#573): `{"ref": "tg:…"}` → `{"mime", "bytes", "data"}`, decidido en
cada pedido con las reglas de FR-17, y cualquier rechazo es el mismo `not_found`.

#### `telegram.watch`

Como `whatsapp.watch`: después del `result`, la conexión recibe
`{"type": "telegram.changed", "what": "threads"}` o `"status"`, sin datos.

#### `telegram.roster_candidate`

Sólo para la acción «Agregar al roster» de PaynaniWeb (FR-15), después de pedir la
contraseña de la web:

```json
{"type": "telegram.roster_candidate", "id": "q_…", "by": "web", "thread": "t_…"}
{"type": "result", "ref": "q_…", "ok": true, "data": {"telegram": "123456789", "display_name": "Pedro"}}
```

Es la única respuesta con un id de Telegram. La web lo pone en el formulario de la
fila nueva y no lo guarda en otro lugar ni lo escribe en su log. La pasarela no
anuncia ni reenvía este tipo. Errores: `not_allowed` si `by` no es `web`, `not_found`
para un hilo que no existe y `conflict` si esa persona ya está en el roster.

#### `telegram.token_check` y `telegram.token_apply`

```json
{"type": "telegram.token_check", "id": "q_…", "by": "web", "token": "…"}
{"type": "result", "ref": "q_…", "ok": true, "data": {
  "bot_username": "MiNegocioBot", "same_token": false, "webhook": false, "check": "c_…"}}
{"type": "telegram.token_apply", "id": "q_…", "by": "web", "check": "c_…",
 "confirm_dedicated": true, "confirm_delete_webhook": false}
{"type": "result", "ref": "q_…", "ok": true, "data": {"result": "applied", "bot_username": "MiNegocioBot"}}
```

- El token viaja sólo en `token_check`. El servicio lo guarda en memoria, ligado a
  `check` por 5 minutos, y `token_apply` usa ese `check`. La web nunca lo devuelve.
- `confirm_dedicated` es obligatorio: el dueño confirma que el token es sólo de esta
  instalación (FR-10 paso 4). `confirm_delete_webhook` es obligatorio si `webhook` era
  `true`.
- `result`: `applied`, `unchanged` (mismo token) o `rollback` (con `reason`: `409`,
  `not_ready`, `getMe`, o `write` si no se pudo guardar el respaldo, `telegram.env` o la
  carpeta del bot). Un `check` vencido o desconocido: `not_found`.
- La pasarela no anuncia ni reenvía estos tipos (FR-29a: el token no se configura
  desde la app).

### Errores

`unavailable`, `not_allowed`, `not_started`, `rate_limited`, `not_found`, `invalid`,
`conflict`, `bad_json`, `unknown_type` y `missing_field`, con los mismos significados
que en `WHATSAPP_BRIDGE.md` §11. Ningún `detail` trae un token, una URL ni un id de
Telegram.

## 5. `paynani telegram`

```
paynani telegram setup                   # lee el token de stdin (FR-9)
paynani telegram status
paynani telegram threads
paynani telegram thread <contacto>
paynani telegram send <contacto> "<texto>" [--file <ruta>]
paynani telegram send <contacto> --stream < texto
paynani telegram draft <contacto> "<texto>"
paynani telegram token                   # cambio de token, lee de stdin (FR-10)
paynani telegram disable                 # llega con TG-6
```

- **El token sólo entra por stdin** (`setup` y `token`), nunca como argumento. En una
  terminal se pide sin eco.
- Las confirmaciones de FR-9 y FR-10 se preguntan en `/dev/tty`, porque stdin ya trae el
  token. Sin terminal, se dan con `--dedicated` (el token es sólo de esta instalación) y
  `--delete-webhook`. Sin ellas no se escribe ni se cambia nada.
- `setup` escribe `telegram.env` (`0600`) sin necesitar el servicio. Con Telegram ya
  configurado se niega y pide `paynani telegram token`, salvo con `--replace`, que es
  para cambiar de token con el servicio parado.
- `token` le pide el cambio al servicio (`token_check` y `token_apply`). Antes de escribir
  el token nuevo guarda el anterior en `telegram.env.bak` (`0600`). Si hay rollback,
  `telegram.env` vuelve a tener el token anterior.
- Al aplicar un token nuevo, el dueño (la primera fila `Human` del roster) recibe un correo
  con el `@usuario` nuevo, sin el token.

Códigos de salida como `paynani whatsapp send`: 2 con el `code` en stderr para
`not_allowed`, `not_started` y `rate_limited`; 1 si el servicio no corre.

## 6. PaynaniApp (TG-8): los mensajes por la pasarela

Mismo modelo que `SMS_GATEWAY.md` §12: pregunta y respuesta por el WebSocket del
teléfono emparejado, `id` `q_` + 32 hex, espera de 15 s y reenvío seguro con el mismo
`id`. La pasarela consulta `control.sock` por dentro.

**Anuncio en el `welcome`:** sólo con Telegram configurado, la pasarela agrega a
`accepts` estos tipos: `telegram.status`, `telegram.threads`, `telegram.thread`,
`telegram.send`. No hay `grants` para Telegram: la app no configura el token, no ve
ids y no tiene «Agregar al roster». Si se activa o desactiva Telegram con la app
conectada, la pasarela cierra con `1012`, como con WhatsApp.

- `telegram.status`, `telegram.threads` y `telegram.thread`: los mismos campos de la
  sección 4, con el mismo orden y la misma paginación.
- **`kind`** trae uno de los valores de la sección 3: `text`, `image`, `video`,
  `audio`, `voice`, `document`, `sticker`, `location`, `contact` u `other`. Para un
  valor que no conozca, la app muestra «[archivo]», como con WhatsApp.
- **Largo:** el servicio parte un texto de más de 4096 caracteres en varios mensajes
  (sección 4, `telegram.send`). La app limita su cuadro de responder a 4096 para que lo que escribe el dueño
  salga en un solo mensaje.
- `telegram.send`: sólo `thread` y `text`; nunca `contact` ni `file`. `by` lo pone la
  pasarela (`phone:<device_id>`).
- **Aviso:** `{"type": "telegram.changed", "what": "threads"}` o `"status"`, sin datos,
  como `whatsapp.changed`.
- Sin `telegram.threads` en `accepts`, la app no muestra «Mensajes de Telegram»; sin
  `telegram.send`, muestra los hilos sin cuadro de responder.

## 7. PaynaniWeb (TG-7)

- «Mensajes de Telegram» usa `telegram.threads`, `telegram.thread`, `telegram.send`,
  `telegram.image` y `telegram.watch`.
- «Bot de Telegram» usa `telegram.status`, y para cambiar el token
  `telegram.token_check` y `telegram.token_apply`, después de pedir la contraseña de la
  web. El campo del token es `type="password"`, con `autocomplete="off"`, y la página
  que lo recibe responde `Cache-Control: no-store`.
- «Agregar al roster» (FR-15): botón en el hilo de alguien fuera del roster; pide la
  contraseña de la web y usa `telegram.roster_candidate`. La fila se agrega como
  cualquier otra desde la web.
- El Catch-All de Telegram tiene su propia página, como cada canal desde #588:
  `/telegram/catch-all`, enlazada desde «Mensajes de Telegram» junto a «Bot de
  Telegram». Guarda `rules/catch-all-telegram.md` con `catchall.save` y
  `channel: telegram`; `catchall.get`/`catchall.save` aceptan ese canal desde TG-3.
  `SaveCatchAll` con `channel: telegram` en la API, y su permiso
  `catchall.telegram.write`, llegan con TG-5.
- Para trabajar sin el servicio, la web usa `telegram_source.py`: `ControlSocket` (el
  cliente de la sección 4) y un `Demo` en memoria que contesta los mismos JSON, con
  `PAYNANI_WEB_TELEGRAM=demo`. La prueba contra el servicio real usa `fake_api.py`
  (sección 9) cuando TG-1 esté fusionado.
- El Dashboard agrega `paynani-telegram` a Servicios, con el `state` de
  `telegram.status`.

## 8. Qué no se registra

Ni en logs, ni en `events.jsonl`, ni en `doctor`, ni en respuestas: el token, cualquier
URL de la Bot API, `bot_id`, `update_id`, `chat.id`, `from.id`, `message_id`, `file_id`,
`@usuario` de personas ni teléfonos. El log del servicio dice el método, el código
HTTP y la referencia opaca (`tg:…`, `t_…`).

## 9. El servidor falso de la Bot API

`scripts/paynani_lib/telegram/fake_api.py` es un servidor HTTP en `127.0.0.1` que
habla como la Bot API, para las pruebas de TG-1 a TG-8. No usa red.

```python
from paynani_lib.telegram.fake_api import FakeBotAPI
api = FakeBotAPI(token="123:TEST", bot_id=123, username="PruebaBot")
api.start()                               # api.base_url -> http://127.0.0.1:<puerto>
api.private_message(user_id=1001, first_name="Ana", text="hola")
api.edit_message(user_id=1001, message_id=1, text="hola de nuevo")
api.group_added(chat_id=-500)             # el bot agregado a un grupo
api.set_webhook("https://ejemplo.invalid/hook")
api.fail_next("sendMessage", 429, retry_after=2)
api.fail_next("getUpdates", 409)
api.revoke()                              # desde aquí todo responde 401
api.sent                                  # lo que el servicio mandó, en orden
api.stop()
```

Con `PAYNANI_TELEGRAM_API=<base_url>` el servicio y la CLI hablan con él en lugar de
`api.telegram.org`. Iris y Andy pueden levantarlo con
`python3 scripts/paynani_lib/telegram/fake_api.py --port 8790` para probar la web y la
pasarela contra el servicio cuando TG-1 exista; hasta entonces, el contrato de la
sección 4 es lo que vale.
