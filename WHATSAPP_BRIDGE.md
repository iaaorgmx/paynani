# Puente de WhatsApp: protocolo entre `paynani-whatsapp` y Baileys

Este documento es el contrato entre el servicio `paynani-whatsapp` (Python) y el
puente de Baileys (`scripts/whatsapp_bridge/`, Node). Lo pide el PRD #550 (FR-2) y lo
sigue también el puente falso de las pruebas. Lo que ve PaynaniApp está en
`SMS_GATEWAY.md` §12; lo que ve el agente, en `AGENTS.md`.

Los números de este documento son de ejemplo (`+1XXXXXXXXXX`). En el repo no va
ningún número real.

## 1. Cómo se hablan

- El servicio arranca el puente como **proceso hijo** y le habla por **stdin**; el
  puente contesta por **stdout**. Cada línea es **un objeto JSON** en UTF-8 con un
  campo `type`, terminado en `\n`. Nada más va por stdout.
- **stderr** es el log del puente. El servicio lo copia a su log tal cual. El puente
  nunca escribe ahí el QR, el código de vinculación, las llaves, el texto de un
  mensaje ni el nombre de un archivo (FR-6a, FR-10). Por eso el log de Baileys
  (`pino`) va en nivel `error` y sin objetos de mensaje, y el servicio corta cada
  línea de stderr a 1 KB.
- El puente **no abre puertos ni sockets** locales (FR-2). La única conexión de red es
  la de Baileys con WhatsApp. Así, ningún otro proceso de la máquina puede mandar ni
  leer mensajes a través de él.
- Una línea de más de **1 MiB** o que no es JSON se descarta y se contesta con
  `error` `bad_json` (sección 7). Ninguna de las dos partes se cae por una línea mala.
- Los tipos y campos desconocidos se ignoran (sección 9).

### Pedidos y respuestas

- Cada orden del servicio lleva un `id` que genera el servicio: `c_` + 16 bytes al azar
  en hex (`^c_[0-9a-f]{32}$`).
- El puente contesta **una sola vez** a cada orden, con `result` o con `error`, y en los
  dos casos con `ref` igual a ese `id`:

```json
{"type": "result", "ref": "c_5d0c…", "ok": true, "data": {…}}
{"type": "error", "ref": "c_5d0c…", "code": "not_connected", "detail": "sin sesión"}
```

- Lo que el puente avisa por su cuenta (un mensaje que llegó, un cambio de estado) va
  sin `ref`.
- El servicio espera cada respuesta **30 segundos** (120 para `send` con archivo). Si
  no llega, lo registra y trata la orden como fallida. Un `send` vencido **no** se
  reintenta solo: puede que sí haya salido.

## 2. Arranque

El servicio lanza el puente con `node scripts/whatsapp_bridge/index.js` y le manda
primero `start`:

```json
{"type": "start", "id": "c_…", "protocol": 1,
 "auth_dir": "/home/agente/paynani/state/whatsapp/auth",
 "media_dir": "/home/agente/paynani/state/whatsapp/media",
 "read_receipts": false, "max_media_mb": 25,
 "allowed": ["+1XXXXXXXXXX"]}
```

- `auth_dir` es donde viven las llaves de la sesión (FR-10). El servicio lo crea con
  0700 antes de arrancar el puente, y el puente crea sus archivos con 0600 (`umask
  077`).
- `media_dir` es donde el puente guarda lo que descarga (sección 4), con 0600.
- `read_receipts` sale de `WHATSAPP_READ_RECEIPTS` en `whatsapp.env`; por omisión
  `false` (FR-4).
- `max_media_mb` sale de `WHATSAPP_MAX_MEDIA_MB`; por omisión 25 (sección 4).
- `allowed` es la lista de números a los que el puente puede mandar (sección 5).

Antes de `start`, el puente sólo contesta `error` `not_started` a cualquier otra orden.
El puente contesta:

```json
{"type": "result", "ref": "c_…", "ok": true,
 "data": {"protocol": 1, "bridge_version": "0.18.0", "baileys_version": "6.7.x"}}
```

Si `protocol` no coincide, contesta `error` `unsupported_protocol` y sale con código 3.
`baileys_version` es la versión exacta que fijó `package.json` (FR-3).

Al conectarse, el puente siempre usa:

- `markOnlineOnConnect: false`: nunca aparece «en línea» (FR-4).
- `syncFullHistory: false` y `shouldSyncHistoryMessage: () => false`, y descarta los
  mensajes de sincronización de historial (`messaging-history.set` y los
  `messages.upsert` de tipo `append`) **antes** de guardarlos o de descargar sus
  archivos (FR-4a). Nada de antes de vincular llega al servicio.

## 3. Estado y vinculación

### `status`: el estado de la cuenta

El puente lo manda al arrancar y cada vez que cambia:

```json
{"type": "status", "state": "connected", "me": "+1XXXXXXXXXX",
 "since": "2026-10-28T19:05:00Z", "reason": null}
```

| `state` | Qué quiere decir |
|---|---|
| `unlinked` | No hay llaves en `auth_dir`: hay que vincular |
| `linking` | Hay una vinculación en curso (QR o código) |
| `connecting` | Hay llaves y el puente se está conectando |
| `connected` | Conectado; llegan y salen mensajes |
| `disconnected` | Se perdió la conexión; el puente reintenta a los 2, 5, 10 y 30 s, y luego cada 60 s |
| `logged_out` | WhatsApp cerró la sesión (el dueño la quitó del teléfono, o la cuenta se bloqueó). Las llaves ya no sirven |

- `me` es el número de la cuenta vinculada en E.164, o `null` sin vincular.
- `reason` es un código corto (`connection_lost`, `logged_out`, `bad_session`,
  `replaced`, `restart_required`), nunca un texto de WhatsApp.
- Con `logged_out` el puente borra las llaves de `auth_dir`, igual que con `logout`
  (sección 6), y queda en `unlinked`.

El servicio también puede pedirlo: `{"type": "status", "id": "c_…"}` contesta `result`
con los mismos campos en `data`.

### `link`: empezar a vincular

```json
{"type": "link", "id": "c_…", "mode": "qr"}
{"type": "link", "id": "c_…", "mode": "code", "number": "+1XXXXXXXXXX"}
```

- `mode: "qr"` para la terminal y PaynaniWeb; `mode: "code"` para
  `paynani whatsapp link --code` y PaynaniApp (FR-6, FR-8). `number` es el del
  teléfono que se va a vincular, y sólo va con `code`.
- **Una sola vinculación en curso** (FR-6a): un `link` nuevo cancela la anterior, que
  termina con `link.ended` `reason: "replaced"`.
- Con una cuenta ya conectada responde `error` `already_linked`: primero se desvincula.

El puente contesta `result` sin datos y después manda el QR o el código:

```json
{"type": "link.qr", "qr": "2@…", "expires_at": "2026-10-28T19:01:20Z"}
{"type": "link.code", "code": "ABCD-EFGH", "expires_at": "2026-10-28T19:03:00Z"}
```

- WhatsApp rota el QR cada ~20 s: cada QR nuevo llega como otro `link.qr`, y el
  anterior deja de valer.
- El código vence a los **3 minutos** (FR-6a). El puente lo cuenta y, al vencer,
  cancela la vinculación.
- **El QR y el código son credenciales de un solo uso.** El servicio los tiene sólo en
  memoria: nunca los escribe en disco, en su log, en `doctor` ni en un aviso al agente
  (FR-6a). Se los da sólo a quien pidió la vinculación (la terminal, la web o la app).

Cómo termina:

```json
{"type": "link.ended", "reason": "linked", "me": "+1XXXXXXXXXX"}
```

`reason` es `linked`, `expired`, `canceled`, `replaced` o `failed`. Con `linked`
le sigue un `status` `connected`.

### `link.cancel`

```json
{"type": "link.cancel", "id": "c_…"}
```

Cancela la vinculación en curso (`link.ended` `canceled`). Sin vinculación en curso
responde `result` igual: no es un error.

## 4. Mensajes que llegan

### `message`: un mensaje directo

```json
{"type": "message", "key_id": "3EB0C4…", "chat": "1XXXXXXXXXX@s.whatsapp.net",
 "from": {"e164": "+1XXXXXXXXXX", "jid": "1XXXXXXXXXX@s.whatsapp.net", "lid": null},
 "push_name": "Ana", "sent_at": "2026-10-28T19:10:02Z",
 "kind": "text", "text": "Hola, ¿tienen mesa para 4 hoy?", "media": null}
```

- **Sólo mensajes directos.** El puente descarta antes de mandarlos y sin guardar nada
  los de grupos (`@g.us`), estados (`status@broadcast`), listas de difusión
  (`@broadcast`) y canales (`@newsletter`) (FR-17), y los suyos propios (`fromMe`).
  Tampoco manda reacciones, ediciones ni mensajes de protocolo: no son algo que el
  contacto escribió.
- **`chat`** es el JID canónico del chat, el mismo para todos los mensajes de ese
  contacto. El servicio arma el id del evento con la cuenta, `chat` y `key_id`:
  `wa:<cuenta>:<hex(sha256(cuenta + "\n" + chat + "\n" + key_id))>` (FR-11). Si
  WhatsApp vuelve a entregar el mismo mensaje, sale el mismo id y no hay otro evento
  (FR-11a).
- **`from.e164`** es el número del remitente. Si WhatsApp sólo da un id de privacidad
  (`…@lid`), el puente usa el mapa LID → número de Baileys. Si no lo puede resolver,
  `e164` va en `null` y `lid` trae el id: el servicio lo trata **como fuera del
  roster**, nunca como contacto autorizado (FR-13).
- `push_name` es el nombre que el contacto se puso en WhatsApp. Es texto del
  remitente: no autoriza nada y sólo se muestra si el número está en el roster.
- `sent_at` es la hora del mensaje según WhatsApp, en UTC.

**`kind` y `media`:**

| `kind` | `text` | `media` |
|---|---|---|
| `text` | El texto | `null` |
| `image`, `video` | El pie de foto, o `null` | Ver abajo |
| `audio` | `null` | Con `seconds` y `voice_note` |
| `document` | El pie, o `null` | Con `filename` |
| `sticker`, `location`, `contact`, `other` | `null` | `null`. El aviso dice el tipo y nada más |

```json
"media": {"path": "/home/agente/paynani/state/whatsapp/media/9f2c….jpg",
          "mime": "image/jpeg", "bytes": 48213, "sha256": "9f2c…",
          "filename": null, "seconds": null, "voice_note": false}
```

- El puente descarga el archivo **antes** de mandar el `message`, a `media_dir`, con
  0600 y con nombre `<sha256>.<extensión del mime>`: el nombre que puso el remitente
  nunca se usa como ruta. `filename` lo trae aparte, limpio de `/`, `\` y caracteres
  de control (FR-16).
- Tope por archivo: `WHATSAPP_MAX_MEDIA_MB` en `whatsapp.env`, 25 por omisión. Uno
  más grande no se descarga: llega con `media.path: null` y `"skipped": "too_large"`.
  Si la descarga falla: `"skipped": "download_failed"`.
- El puente **no** sabe del roster. El servicio decide quién está en el roster y aplica
  FR-16a: el texto y el archivo de un número fuera del roster nunca salen por
  ningún lado salvo con el Catch-All activo. El puente igual descarga el archivo para
  que no se pierda si el Catch-All está activo; el servicio borra el archivo de
  `media/` en cuanto decide que no se puede mostrar.

### `call`: una llamada de WhatsApp

```json
{"type": "call", "call_id": "A1B2…", "from": {"e164": "+1XXXXXXXXXX", "jid": "…", "lid": null},
 "status": "missed", "video": false, "at": "2026-10-28T19:12:40Z"}
```

`status` es `missed` o `answered`, como lo reporta WhatsApp. El servicio escribe
`call.missed` o `call.answered` con `channel: whatsapp` (FR-18). El puente nunca
contesta ni rechaza llamadas.

## 5. Mensajes que salen

### `allow`: a quién se puede mandar

```json
{"type": "allow", "id": "c_…", "allowed": ["+1XXXXXXXXXX", "+1XXXXXXXXXX"]}
```

- Es la **segunda barrera**, como `allowed` en el teléfono de SMS (`SMS_GATEWAY.md`
  §8). El servicio manda la lista en `start` y cada vez que cambia: los números del
  roster que ya escribieron por WhatsApp después de vincular (FR-20).
- El puente reemplaza la lista completa y no la guarda en disco.
- La primera barrera sigue siendo el servicio (FR-19 a FR-22). El puente no sabe del
  roster: sólo compara contra esta lista.

### `send`: mandar texto o un archivo

```json
{"type": "send", "id": "c_…", "to": "+1XXXXXXXXXX", "text": "Sí, a las 8 tenemos lugar."}
{"type": "send", "id": "c_…", "to": "+1XXXXXXXXXX", "text": "Aquí va su factura",
 "file": {"path": "/home/agente/paynani/state/whatsapp/outbox/factura.pdf",
          "mime": "application/pdf", "filename": "factura.pdf"}}
```

- `to` es E.164. Si no está en `allowed`, el puente contesta `error` `not_allowed` y no
  manda nada.
- `text` es de 1 a 4,000 caracteres; con `file`, puede ir vacío y es el pie.
- `file.path` ya lo validó el servicio (FR-22: sólo `state/whatsapp/outbox/` o
  `WHATSAPP_ATTACH_DIRS`). El puente igual revisa que sea un archivo regular, sin
  seguir enlaces simbólicos, y de 64 MB o menos.
- El tope de envío (FR-21: 1 cada 3 s y 200 al día) lo lleva el **servicio**, que
  contesta `rate_limited` sin pasarle la orden al puente. El puente no reintenta un
  envío fallido.

Respuesta:

```json
{"type": "result", "ref": "c_…", "ok": true,
 "data": {"key_id": "3EB0D9…", "chat": "1XXXXXXXXXX@s.whatsapp.net",
          "sent_at": "2026-10-28T19:13:05Z"}}
```

### `receipt`: qué pasó después

```json
{"type": "receipt", "key_id": "3EB0D9…", "chat": "1XXXXXXXXXX@s.whatsapp.net",
 "status": "delivered", "at": "2026-10-28T19:13:07Z"}
```

`status` es `server` (llegó a WhatsApp), `delivered` o `read` (sólo si el otro tiene
los acuses de lectura prendidos). El servicio lo guarda en el hilo (FR-23).

### `read`: marcar como leído

```json
{"type": "read", "id": "c_…", "chat": "1XXXXXXXXXX@s.whatsapp.net", "key_ids": ["3EB0C4…"]}
```

Sólo si `start.read_receipts` era `true`. Si no, el puente contesta `result` sin
hacer nada.

## 6. Salud, desvincular y cierre

### `ping`

```json
{"type": "ping", "id": "c_…"}
```

El puente contesta `result` con `data: {"state": "connected"}`. El servicio lo manda
cada 30 s. Tres pings sin respuesta cuentan como puente caído.

### El puente se cae

- Si el proceso sale o deja de contestar, el servicio lo vuelve a lanzar con espera
  creciente: 5 s, 10 s, 30 s y luego cada 60 s (FR-5). Al relanzarlo manda `start` otra
  vez. La espera vuelve a 5 s después de 10 minutos conectado.
- El servicio escribe `whatsapp.health` en el diario (como `gateway_health_event` de
  SMS) cuando pasan **10 minutos** sin `connected` y cuando llega `logged_out`. No lo
  repite mientras siga el mismo problema, y escribe otro cuando se recupera.
- Una vinculación en curso se pierde si el puente se cae: el QR o el código ya no
  sirve y hay que pedir otro.

### `logout`: desvincular

```json
{"type": "logout", "id": "c_…"}
```

El puente cierra la sesión en WhatsApp (el teléfono deja de ver el dispositivo
vinculado), borra todo `auth_dir` y contesta `result`. Queda en `unlinked`. Si
WhatsApp no contesta en 10 s, igual borra las llaves y contesta con
`data: {"remote": false}`, para que el dueño sepa que debe quitar el dispositivo
desde el teléfono (FR-9).

### `shutdown`: cierre

```json
{"type": "shutdown", "id": "c_…"}
```

El puente cierra la conexión **sin** cerrar la sesión (las llaves se quedan), contesta
`result` y sale con código 0 en menos de 5 s. Si stdin se cierra, hace lo mismo. Si
no sale a tiempo, el servicio le manda `SIGTERM` y, 5 s después, `SIGKILL`.

**Códigos de salida:** `0` cierre normal, `2` error de arranque (falta Node o las
dependencias), `3` protocolo distinto, `4` `auth_dir` con permisos abiertos (el puente
no arranca si el directorio no es 0700 o algún archivo no es 0600).

## 7. Errores

```json
{"type": "error", "ref": "c_…", "code": "not_allowed", "detail": "+1XXXXXXXXXX no está en allowed"}
```

| `code` | Cuándo | Quién lo da |
|---|---|---|
| `bad_json` | La línea no es JSON o pasa de 1 MiB (sin `ref`) | Puente o servicio |
| `unknown_type` | `type` desconocido | Puente |
| `missing_field` | Falta un campo obligatorio. Va `field` | Puente |
| `not_started` | Una orden antes de `start` | Puente |
| `unsupported_protocol` | `start.protocol` distinto | Puente |
| `not_connected` | `send`, `read` o `logout` sin cuenta conectada | Puente |
| `already_linked` | `link` con una cuenta ya conectada | Puente |
| `not_allowed` | `to` fuera de `allowed`, o `file` que no es un archivo regular | Puente |
| `too_large` | `text` o `file` pasan su tope | Puente |
| `send_failed` | WhatsApp rechazó el envío. `detail` trae el código de Baileys | Puente |

`not_started` (contacto del roster que no ha escrito, FR-20), `not_allowed` (fuera del
roster o ruta no permitida, FR-19 y FR-22) y `rate_limited` (FR-21) de
`paynani whatsapp send` los da el **servicio** antes de llegar al puente, con código
de salida 2. Ojo: el `not_started` del puente (orden antes de `start`) no es el mismo
que el de `send`. Ningún error cierra el puente, salvo `unsupported_protocol`.

## 8. Qué no se registra

- Ni el puente (stderr) ni el servicio escriben en su log el QR, el código de
  vinculación, nada de `auth_dir`, el texto de un mensaje, un pie de foto, un
  `push_name` ni un nombre de archivo. Sí registran el `type`, el `key_id`, el
  `state` y los códigos de error.
- El texto de los mensajes vive en `state/whatsapp/inbox/` y en el diario de eventos,
  como el de los SMS (`SMS_GATEWAY.md` §8).
- `install.manifest` excluye `state/whatsapp/auth/` de respaldos y de las
  desinstalaciones parciales (FR-10).

## 9. Versiones

Este documento describe el protocolo **1**. Un campo nuevo y opcional no cambia la
versión, y las dos partes ignoran los campos y avisos que no conocen. Un cambio que
rompe a la otra parte sube `protocol` y se documenta aquí antes de escribir el código.
El puente y el servicio salen siempre juntos en la misma versión de paynani, así que
un `protocol` distinto sólo aparece con una instalación a medias.

## 10. El puente falso

Las pruebas usan un puente falso en Python (WA-1) que sigue este mismo contrato: lee
las órdenes por stdin, contesta por stdout y, con órdenes de prueba que el puente real
no tiene (`fake.*`), simula un mensaje que llega, una llamada, una desconexión o un
`logged_out`. Ninguna prueba se conecta a WhatsApp. El puente real sólo se prueba en
las pruebas reales de WA-8 (#560).

## 11. Interfaz local del servicio (WA-2)

Las secciones 1 a 10 son entre el servicio y su puente. Esta es la otra puerta del
servicio: la que usan `paynani whatsapp` (la terminal y el agente), la pasarela SMS
(para PaynaniApp, `SMS_GATEWAY.md` §12) y PaynaniWeb.

### Dónde y quién

- Un socket Unix en `state/whatsapp/control.sock`. La carpeta es 0700 y el socket
  0600, así que sólo el usuario de la instalación puede conectarse. No hay puerto TCP:
  nada de la red, ni otro usuario de la máquina, llega a él.
- El servicio confía en quien se conecta, porque es el mismo usuario. Las barreras
  de quién puede pedir qué son de cada cliente: la pasarela revisa `whatsapp.admin`
  (FR-6a) y la web pide su contraseña y el CSRF (FR-6a, FR-7) **antes** de mandar la
  petición. Las reglas de envío y de privacidad (FR-16a, FR-19 a FR-22) las aplica
  **siempre** el servicio, venga de quien venga la petición.
- Si el servicio no corre, el socket no existe o rechaza la conexión. El cliente lo
  trata como `unavailable`.
- **WhatsApp configurado** es un solo predicado, `whatsapp_config.configured()` en
  `scripts/paynani_lib/whatsapp/config.py`, que usan el servicio, la pasarela, la web,
  `doctor` y el instalador. Es verdadero sólo si `whatsapp.env`, junto a
  `runtime.env`, es un archivo regular (no un enlace), se puede leer y trae
  `WHATSAPP_ENABLED=1`. Faltante, ilegible, con otro valor o con una línea que no se
  entiende: **no configurado**, y nadie anuncia nada de WhatsApp.
  - Lo escribe sólo la instalación al activar WhatsApp (WA-3, `install.sh
    --with-whatsapp`). Lo apaga `paynani whatsapp disable`, que lo deja en
    `WHATSAPP_ENABLED=0`, y la desinstalación, que lo borra.
  - Configurado y con el servicio caído, el cliente contesta él mismo
    `whatsapp.status` con `state: "service_down"`. La web sigue mostrando el menú.

### Cómo se habla

- Un JSON por línea en cada sentido, como con el puente. Una conexión puede llevar
  varias peticiones.
- Cada petición lleva `type`, `id` (`q_` + 32 hex) y `by`, que dice de dónde viene:
  `terminal`, `agent`, `web`, `phone:<device_id>` o `api`.
- **`by` es sólo una etiqueta.** Todos los clientes entran con el mismo usuario por el
  mismo socket, así que cualquiera puede escribir cualquier `by`. El servicio lo usa
  para el log, para `linking.by` y para marcar quién mandó un mensaje en el hilo,
  nunca para decidir un permiso. Las reglas que protegen algo (FR-16a, FR-19 a
  FR-22) las aplica el servicio igual para todos.
- El servicio contesta una vez a cada petición, con `result` o `error` y `ref` igual
  al `id`, con las mismas formas que `SMS_GATEWAY.md` §12.

```json
{"type": "whatsapp.status", "id": "q_…", "by": "web"}
{"type": "result", "ref": "q_…", "ok": true, "data": {"state": "connected", "me": "+1XXXXXXXXXX", …}}
```

### Los tipos

Los de `SMS_GATEWAY.md` §12, con los mismos campos, más lo que la web y la terminal
necesitan:

| `type` | Qué hace | Diferencia con §12 |
|---|---|---|
| `whatsapp.status` | Estado | Igual |
| `whatsapp.link` | Empieza a vincular | Acepta `mode: "qr"` además de `"code"`, y el `result` trae `link_id` (ver abajo) |
| `whatsapp.link_current` | El QR o código vigente de una vinculación | Nuevo. Pide `link_id` |
| `whatsapp.link_cancel` | Cancela | Igual |
| `whatsapp.unlink` | Desvincula | Igual |
| `whatsapp.threads` | Hilos | Igual |
| `whatsapp.thread` | Un hilo | Igual |
| `whatsapp.send` | Contesta en un hilo | Acepta `file` (ruta), que el servicio valida siempre contra FR-22, sin importar `by`. La pasarela y la web no aceptan archivos de sus propios clientes, así que nunca mandan `file` |
| `whatsapp.watch` | Avisos sin pedirlos | Nuevo. Ver abajo |
| `whatsapp.image` | La foto de un mensaje recibido, para PaynaniWeb | Nuevo (#573). Ver abajo. La pasarela no lo anuncia ni lo reenvía |

### Vincular: `link_id` y `whatsapp.link_current`

La web es pregunta y respuesta, y el QR rota cada ~20 s. Por eso el `result` de
`whatsapp.link` trae un `link_id` (`l_` + 32 hex), además del primer QR o del código:

```json
{"type": "result", "ref": "q_…", "ok": true, "data": {
  "link_id": "l_…", "mode": "qr", "qr": "2@…", "expires_at": "…", "expires_in_s": 20}}
```

Con ese `link_id`, quien empezó la vinculación pregunta por el QR vigente:

```json
{"type": "whatsapp.link_current", "id": "q_…", "by": "web", "link_id": "l_…"}
{"type": "result", "ref": "q_…", "ok": true, "data": {
  "state": "waiting", "mode": "qr", "qr": "2@…", "expires_at": "…", "expires_in_s": 14}}
{"type": "result", "ref": "q_…", "ok": true, "data": {"state": "ended", "reason": "linked"}}
```

- **Sólo el `link_id` da el QR o el código.** `whatsapp.status` nunca los trae, y
  `whatsapp.watch` tampoco. El `link_id` sólo va en el `result` a quien pidió
  vincular (FR-6a). Un `link_id` que no es el de la vinculación en curso responde
  `not_found`.
- `reason` es el de `link.ended` (§3): `linked`, `expired`, `canceled`, `replaced` o
  `failed`. Un `link_id` terminado responde `ended` durante 5 minutos y luego
  `not_found`.
- **Con `mode: "qr"`, si nadie pregunta, se cancela.** Si pasan 60 s sin un
  `whatsapp.link_current` con ese `link_id`, el servicio cancela la vinculación
  (`link.ended` `canceled`). Así un QR no queda vivo con la página cerrada. La web
  pregunta cada 2 a 5 s mientras la página está abierta.
- **Con `mode: "code"` no hay cancelación por silencio.** El código vive sus 180 s
  (FR-6a) o hasta que alguien cancele o empiece otra vinculación. PaynaniApp sólo
  refresca `whatsapp.status`, y eso basta. `whatsapp.link_current` con el `link_id`
  de un código responde el estado (`waiting` o `ended`) y `expires_in_s`, **nunca el
  código otra vez**: el código sale una sola vez, en el `result` de
  `whatsapp.link`, como en §12.
- La terminal (`paynani whatsapp link`) usa el mismo mecanismo.

**De punta a punta en PaynaniWeb** (WA-5):

1. `POST /whatsapp/link` con la contraseña y el CSRF (FR-6a). La web manda
   `whatsapp.link` con `mode: "qr"` y guarda el `link_id` **sólo en el servidor**,
   ligado a la sesión del navegador; nunca va al navegador ni a una URL. Responde la
   página del QR.
2. La página pide `GET /whatsapp/link/current` cada 2 a 5 s. Es una lectura con la
   sesión ya iniciada, sin contraseña ni CSRF. La web manda `whatsapp.link_current`
   con el `link_id` de esa sesión y devuelve el QR vigente como SVG, `expires_in_s` y
   el estado, o el final.
3. `POST /whatsapp/link/cancel` y `POST /whatsapp/unlink` llevan contraseña y CSRF.
4. **Toda respuesta que pueda traer un QR o un código** lleva `Cache-Control:
   no-store`, y el SVG se arma en memoria; nunca se escribe en disco.
5. Si la página se cierra, nadie pregunta y a los 60 s el servicio cancela. Si una
   pregunta falla (socket caído), la página reintenta con la misma espera; si el
   servicio contesta `not_found`, la página dice que la vinculación terminó y ofrece
   empezar otra.

**El QR se dibuja con `scripts/paynani_lib/sms/qr.py`,** no con un codificador nuevo.
Es el que paynani ya usa desde SRV-4 para el QR de emparejamiento de SMS, que
PaynaniApp escanea en cada instalación. `scripts/test_qr.py` lee cada matriz de vuelta
como un lector (bits de formato, máscara, Reed-Solomon y modo byte). WA-2 agrega una
regresión con una cadena del tamaño máximo observado para un QR de WhatsApp (~310
bytes, versión 13, nivel M): la matriz se lee de vuelta y el SVG que sale de `to_svg`
se rasteriza y se decodifica (con `zbarimg` si está instalado). paynani no lleva dependencias
de Python, así que no se agrega una biblioteca de QR.

### `whatsapp.image` (#573)

PaynaniWeb lo usa para mostrar en «WhatsApp messages» la foto de un mensaje recibido:

```json
{"type": "whatsapp.image", "id": "q_…", "by": "web", "message_id": "wa:<cuenta>:<hash>"}
{"type": "result", "ref": "q_…", "ok": true, "data": {"mime": "image/jpeg", "bytes": 287177, "data": "<base64>"}}
```

- **Se decide en cada pedido, con FR-16a.** La foto sale sólo si el texto del mensaje
  también se mostraría: un número del roster, o un mensaje que llegó con el Catch-All
  activo mientras el Catch-All **siga** activo y válido. Apagarlo, o sacar al contacto
  del roster, deja de servir la foto también a una URL que ya estaba abierta.
- **La ruta guardada no se confía.** El servicio abre sólo un archivo con nombre de
  `media/` (sha256 y extensión) directamente dentro de `state/whatsapp/media/`, sin
  seguir enlaces simbólicos (`O_NOFOLLOW`). Tiene que ser un archivo regular de hasta
  10 MB, con el tamaño revisado después de abrirlo, y el tipo sale de sus primeros
  bytes: JPEG, PNG o WebP. Nunca de la extensión ni del `mime` guardado.
- **Un solo error.** Un `message_id` que no existe, que no es una foto, que no se puede
  mostrar o cuyo archivo falta o no pasa las revisiones responde el mismo `not_found`.
  Quien pregunta no puede saber cuál de esos casos fue.
- PaynaniWeb la sirve en `GET /whatsapp/media?id=<message_id>`, con la sesión iniciada.
  Vuelve a revisar el tipo por los primeros bytes y responde con `Cache-Control:
  no-store`, `X-Content-Type-Options: nosniff`, `Content-Disposition: inline` y una CSP
  `sandbox`. Cualquier rechazo es el mismo 404; con el servicio caído, 503. La API de
  PaynaniWeb (WA-6) no da archivos.

### `whatsapp.watch`

```json
{"type": "whatsapp.watch", "id": "q_…", "by": "phone:d_3f9a1c"}
```

El servicio contesta primero `result` con el estado actual, y desde ahí esa conexión
recibe los avisos:

```json
{"type": "result", "ref": "q_…", "ok": true, "data": {"watching": true, "status": {"state": "connected", …}}}
```

Desde ahí, esa conexión recibe `{"type": "whatsapp.changed", "what": "threads"}` y
`{"type": "whatsapp.changed", "what": "status"}`, igual que el aviso de §12: sin
datos del mensaje ni del número, y nunca un QR ni un código. La pasarela lo usa para
reenviar el aviso a PaynaniApp, y la web para refrescar la página.

### Errores

Los de `SMS_GATEWAY.md` §12 (`unavailable`, `already_linked`, `not_connected`,
`not_allowed`, `not_started`, `rate_limited`, `not_found`, `invalid`), más
`bad_json`, `unknown_type` y `missing_field` como en §7. `forbidden` no sale de aquí:
lo da el cliente que revisa sus propias barreras.

### `paynani whatsapp`

La terminal y el agente usan esta misma interfaz. `paynani whatsapp send` sale con
código 2 y el `code` en stderr para `not_allowed`, `not_started` y `rate_limited`,
como `paynani sms send`, y con 1 si el servicio no corre.
