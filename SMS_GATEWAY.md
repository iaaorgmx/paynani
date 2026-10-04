# Pasarela SMS: protocolo entre PaynaniApp y paynani

Esta página define cómo se hablan **PaynaniApp** (la app de Android que vive en el
teléfono) y la **pasarela SMS** de paynani (el servicio que corre en la máquina del
agente). Es el contrato que siguen las dos partes. Si una de las dos hace algo que
aquí no está, el error es de esa parte o de esta página, y se corrige aquí primero.

Es la tarea PROTO-1 ([#305](https://github.com/iaaorgmx/paynani/issues/305)) del
PRD [iaaorgmx/PaynaniApp#15](https://github.com/iaaorgmx/PaynaniApp/issues/15).
La pasarela (SRV-1) ya lo implementa en `scripts/sms_gateway.py` y `scripts/paynani_lib/sms/`; la app lo implementa en APP-2, APP-3, APP-4 y APP-11.

## Qué hace la pasarela

El agente ya recibe y manda correo con paynani. Con la pasarela hace lo mismo con
**SMS**, usando el número y el servicio celular reales de un teléfono Android:

- Un **SMS que llega** al teléfono entra al mismo diario (`events.jsonl`) que el
  correo, como evento `sms.received`, y le llega al agente por el mismo *dispatcher*.
- El agente **contesta** con `paynani sms send <número> <texto>` y el teléfono lo
  envía.
- Las **llamadas perdidas y contestadas** entran como `call.missed` y
  `call.answered`, para que el agente ubique al cliente, avise al humano o lo
  registre en un CRM. Las llamadas salientes no se reportan.
- `roster.md` decide igual que con el correo, con una columna de teléfono:

| | número en `roster.md` | cualquier otro |
|---|---|---|
| Se le reporta al agente | sí | sí |
| Marcado `roster` | sí | no |
| El texto es una instrucción | sí | no |
| Se le puede enviar un SMS | sí | no: `paynani sms send` sale con código 2 y el teléfono lo rechaza |

Todo corre en la máquina del agente. No hay Firebase ni ningún servicio de terceros
en medio, salvo el túnel que se elija para que el teléfono llegue a esa máquina.

## Piezas

```
 Teléfono (PaynaniApp)                        Máquina del agente (paynani)
 ────────────────────                         ─────────────────────────────
 SMS / llamada ─► cola local ─┐               ┌─► events.jsonl ─► dispatcher ─► agente
                              │   wss://      │
                              ├──────────────►│  pasarela SMS
                              │  (túnel)      │
 SmsManager ◄── sms.out ◄─────┘               └─◄ paynani sms send <número> <texto>
```

- **Una conexión WebSocket por teléfono**, que siempre **abre el teléfono** hacia la
  pasarela y mantiene abierta desde su servicio en primer plano. La pasarela nunca
  inicia una conexión hacia el teléfono.
- **TLS lo pone el túnel** (ngrok, Cloudflare Tunnel o Tailscale): el teléfono usa
  `wss://` y `https://`. La pasarela escucha en `127.0.0.1` y nunca en una interfaz
  pública. Sin túnel, el teléfono sólo llega en la misma red local y se usa `ws://`
  únicamente para pruebas.
- **Un teléfono por agente en esta versión** (DEC-3). Igual que se hizo con el
  correo, primero funciona bien con uno solo; varios teléfonos se consideran después,
  ya probado. Emparejar un teléfono nuevo pide revocar antes el actual. El
  `device_id` ya viaja en los mensajes y en la cuenta (`sms:<device_id>`) para que
  sumar teléfonos después no cambie el protocolo.
- **El roster es `roster.md`**, el mismo del correo, con su columna `Phone`.

## Números de teléfono

Todo número se guarda y se compara en **E.164** (`+` y sólo dígitos). La biblioteca
estándar de Python no trae `phonenumbers`, así que estas reglas son las que aplican
**las dos partes** (la app y paynani), con la región por omisión
`PAYNANI_SMS_DEFAULT_REGION` de `runtime.env` (`MX` si no está):

1. Se quitan espacios, guiones, puntos y paréntesis.
2. `00` al inicio equivale a `+`.
3. **México:** `+521` seguido de 10 dígitos se convierte en `+52` y los mismos 10
   dígitos. Es el `1` de los móviles que se dejó de usar en 2019 y que todavía
   circula, por ejemplo en WhatsApp. Con región `MX`, 10 dígitos sin `+` son `+52`
   y esos 10, y 12 dígitos que empiezan con `52` son `+` y esos 12.
4. Con región `US` o `CA`, 10 dígitos son `+1` y esos 10, y 11 dígitos que empiezan
   con `1` son `+` y esos 11.
5. Lo que ya empieza con `+` sólo pasa por las reglas 1 y 3. Sin `+` y sin una
   regla de la región, **no se adivina** el país: el resultado es `null`.
6. **Códigos cortos** (de 3 a 6 dígitos, los de bancos y servicios) y **remitentes
   alfanuméricos** (`AMAZON`, `O'Shop`) no son E.164: su `e164` es `null`, se
   reportan tal cual y **nunca** coinciden con el roster.

| Entrada | Región | E.164 |
|---|---|---|
| `55 1111 2222` | MX | `+525511112222` |
| `+52 1 55 1111 2222` | MX | `+525511112222` |
| `0052 55 1111-2222` | MX | `+525511112222` |
| `(555) 000-1111` | US | `+15550001111` |
| `1 555 000 1111` | US | `+15550001111` |
| `+15550001111` | MX | `+15550001111` |
| `26262` | MX | `null` (código corto) |
| `AMAZON` | MX | `null` (alfanumérico) |

Esta tabla es el caso de prueba compartido. En paynani la implementa
`harness/phone.py` (`to_e164`) y la prueba `scripts/test_phone.py`; el roster y la
pasarela usan esa misma función, y las pruebas de la app corren la misma tabla.

**En `roster.md`** la columna `Phone` acepta varios números separados por coma (por
ejemplo `+525511112222, 55 3333 4444`). Cada uno se normaliza con estas reglas al
leer el roster.

## 1. Emparejamiento

Se hace una vez por teléfono, desde la página de onboarding de paynani.

1. La página genera un **código de un solo uso** (8 caracteres de
   `ABCDEFGHJKMNPQRSTUVWXYZ23456789`, vence a los **10 minutos**) y muestra un QR con:

   ```json
   {"v": 1, "pair": "https://<túnel>/sms/pair", "ws": "wss://<túnel>/sms/ws", "code": "K7QW2MXP"}
   ```

2. La app escanea el QR (o se escriben la dirección y el código a mano) y manda:

   ```http
   POST /sms/pair
   Content-Type: application/json

   {"code": "K7QW2MXP",
    "device": {"model": "Pixel 6", "android": "16", "app_version": "1.0"},
    "sims": [{"slot": 0, "number": "+525512345678", "country": "MX"}]}
   ```

   `number` puede venir en `null`: muchas SIM no exponen su número. `country` es el
   país de la SIM en ISO; con él se normalizan los números (ver `sms.in`).

3. La pasarela contesta `201` con:

   ```json
   {"device_id": "d_3f9a1c", "token": "<32 bytes al azar en base64url>", "ws": "wss://<túnel>/sms/ws"}
   ```

   El código queda gastado aunque la respuesta no llegue. La pasarela guarda **sólo el
   SHA-256 del token**, nunca el token. La app lo guarda en
   `EncryptedSharedPreferences`.

| Respuesta | Cuándo |
|---|---|
| `201` | Emparejado |
| `400 bad_request` | Falta `code` o el JSON no es válido |
| `409 device_exists` | Ya hay un teléfono emparejado (DEC-3: uno). Se revoca con `paynani sms revoke` o `paynani sms pair --replace` |
| `410 code_expired` | El código venció o ya se usó |
| `429 too_many_attempts` | Más de 10 códigos equivocados en 10 minutos **en total**. El emparejamiento queda bloqueado hasta generar un código nuevo. Es un tope global y no por dirección: detrás del túnel todas las peticiones llegan desde `127.0.0.1`, y un `X-Forwarded-For` se puede falsificar |

**Revocar** un teléfono (desde `paynani sms pair --web` o con `paynani sms revoke`)
borra el hash del token y cierra su WebSocket con el código `4401`. La revocación se
hace desde otro proceso, así que la pasarela la nota en la siguiente revisión de la
conexión (cada `heartbeat_s / 3`, 10 s por omisión) o con el siguiente mensaje del
teléfono, lo que pase primero. Un mensaje que llega después de revocar no entra al
diario y no recibe `ack`. Emparejar otro teléfono corta igual al anterior.

## 2. Conexión

```http
GET /sms/ws
Upgrade: websocket
Authorization: Bearer <token>
Sec-WebSocket-Protocol: paynani-sms.v1
```

- Token desconocido o revocado: la pasarela responde `401` y no abre el WebSocket.
- Si el mismo `device_id` ya tiene una conexión abierta, la vieja se cierra con
  `4409` y se queda la nueva.
- Cada mensaje es **un objeto JSON en un frame de texto** con un campo `type`.

### Saludo

Lo primero que manda la app:

```json
{"type": "hello", "protocol": 1, "device_id": "d_3f9a1c", "app_version": "1.0",
 "sims": [{"slot": 0, "number": "+525512345678"}],
 "pending": {"in": 3, "status": 0}}
```

La pasarela contesta:

```json
{"type": "welcome", "protocol": 1, "server_time": "2026-10-02T03:10:00Z",
  "heartbeat_s": 30, "allowed": ["+525511112222", "+15550001111"], "max_out_per_hour": 60,
  "accepts": ["sms.in", "call.missed", "call.answered", "sms.status", "sms.unseen"],
  "server_version": "0.11.0"}
```

- `accepts` es la lista de tipos que esta pasarela acepta del teléfono. La app
  **sólo** manda un tipo que aparece ahí. Una pasarela anterior a `accepts` no lo
  trae, y con ella la app se queda en los tipos de siempre y no manda `sms.unseen`.
  Así un tipo nuevo no sube `protocol` (sección 10).

- `server_version` es la versión de paynani de la pasarela; la app la muestra en
  Estado. Una pasarela anterior no lo trae.

- `allowed` es la lista de teléfonos de `roster.md`. La app **sólo** envía SMS a esos
  números (segunda barrera, por si la primera falla). Cuando cambia el roster, la
  pasarela manda `{"type": "allowed", "allowed": [...]}`.
- Si `protocol` no coincide, la pasarela manda `error` con `unsupported_protocol` y
  cierra con `4400`.

### Latido

- La app manda un frame **ping** de WebSocket cada `heartbeat_s` segundos
  (`OkHttpClient.pingInterval`), y la pasarela responde **pong**.
- Si la pasarela no recibe nada de un teléfono en **3 × `heartbeat_s`**, lo marca
  fuera de línea y escribe `sms.gateway.offline` (ver la sección 6).
- Si la app no recibe el pong, cierra y **reconecta** con espera creciente: 1, 2, 4,
  8, 16, 32 y 60 segundos como máximo, con ±20 % al azar. Al reconectar repite el
  `hello`.

## 3. Del teléfono a la pasarela

Todo lo que manda la app pasa primero por una **cola SQLite** en el teléfono. Sale
de la cola sólo con el `ack` de la pasarela. Si no llega el `ack` en 30 segundos o
se cae la conexión, se reenvía con el **mismo `id`**.

### `sms.in`: SMS recibido

```json
{"type": "sms.in", "id": "9f2c…(64 hex)",
 "from": {"e164": "+525511112222", "raw": "+525511112222"},
 "sim": {"slot": 0, "number": "+525512345678"},
 "text": "Hola, ¿tienen mesa para 4 hoy?",
 "sent_at": "2026-10-02T03:09:41-06:00",
 "received_at": "2026-10-02T03:09:44-06:00",
 "parts": 1}
```

- `from.raw` es el remitente **exacto** que reporta Android. `from.e164` es ese número
  normalizado a E.164, o `null` si el remitente es alfanumérico (`AMAZON`,
  `O'Shop`). **Nunca** se limpia el remitente a sólo dígitos: eso hoy junta todos los
  alfanuméricos en una sola llave vacía.
- `sent_at` es la hora del centro de mensajes (`SmsMessage.getTimestampMillis()`,
  que Android guarda en la bandeja como `date_sent`). `received_at` es cuándo lo
  recibió el teléfono.
- Un SMS largo se arma completo en el teléfono y se manda una sola vez, con su
  número de partes en `parts`.

**`id`, la llave que evita duplicados:**

```
llave = from.e164 si no es null, si no from.raw
id = hex(sha256(llave + "\n" + str(sent_at_en_ms) + "\n" + text))
```

Las dos rutas de la app, el receptor en tiempo real y el barrido de respaldo de la
bandeja, calculan **el mismo `id`** para el mismo SMS. Usan el E.164 y no el
remitente original porque el mismo SMS no siempre trae el mismo texto de remitente en
las dos rutas: en el emulador el receptor ve `5550001111` y la bandeja guarda
`+15550001111`. La pasarela es **idempotente** por `id`: un `id` repetido no crea otro
evento.

**Región de la normalización:** la del país de la SIM (`sims[].country`, en ISO,
por ejemplo `"US"`), que la app manda al emparejar y en el `hello`. Sin país, la de
`PAYNANI_SMS_DEFAULT_REGION`. La pasarela recalcula `from.e164` con esa región a
partir de `from.raw`; el `from.e164` que manda la app sólo sirve para el `id`.

### `call.missed` y `call.answered`: llamadas

```json
{"type": "call.missed", "id": "…(64 hex)",
 "from": {"e164": "+525511112222", "raw": "5511112222"},
 "sim": {"slot": 0, "number": "+525512345678"},
 "started_at": "2026-10-02T03:20:05-06:00"}
```

```json
{"type": "call.answered", "id": "…(64 hex)",
 "from": {"e164": "+525511112222", "raw": "5511112222"},
 "sim": {"slot": 0, "number": "+525512345678"},
 "started_at": "2026-10-02T03:25:10-06:00", "duration_s": 184}
```

- `id = hex(sha256(type + "\n" + llave + "\n" + str(started_at_en_ms)))`, con la misma
  `llave` que en `sms.in`.
- Una llamada con número oculto llega con `from.raw = ""` y `from.e164 = null`.
- `call.answered` se manda **al colgar**, cuando ya se conoce la duración.

### `sms.unseen`: un mensaje que la app no pudo leer

Google Messages entrega los RCS por datos y nunca como SMS, así que la app no los
ve (PaynaniApp#46). Si el usuario le dio a la app acceso a las notificaciones, la
app detecta una notificación de mensaje de Google Messages que en 60 segundos no
tuvo un SMS correspondiente, y avisa:

```json
{"type": "sms.unseen", "id": "4b1e…(64 hex)", "app": "com.google.android.apps.messaging",
 "posted_at": "2026-10-04T08:00:00Z", "title": "Ana López",
 "sim": {"slot": 0, "number": "+525512345678"}}
```

- `id`, `app` y `posted_at` son obligatorios. Si falta alguno, `missing_field` y
  `ack` `rejected`.
- `title` es lo que mostró la notificación: un nombre de contacto o un número, **no
  confiable**. La pasarela lo limpia y lo recorta a 80 caracteres.
- El texto de la notificación **no** se manda: puede venir cortado y no sirve para
  decidir si el remitente está en el roster.
- Se deduplica por `id` y se contesta con `ack`, igual que `sms.in`.
- La app sólo lo manda si `welcome.accepts` incluye `sms.unseen`.
- Google Messages también notifica los **MMS**, que tampoco pasan por
  `content://sms` y la app no lee: un MMS también produce `sms.unseen`. Por eso la
  línea dice «posible RCS» y no «RCS».
- Un SMS que llega por la SIM que paynani no atiende (APP-10) no se encola, pero
  la app lo anota como visto, así que no produce un `sms.unseen` falso.

### `ack`: la pasarela lo guardó

```json
{"type": "ack", "id": "9f2c…", "result": "stored", "event_id": "sms:d_3f9a1c:9f2c…"}
```

| `result` | Significado | Qué hace la app |
|---|---|---|
| `stored` | Ya está escrito en `events.jsonl` | Lo saca de la cola |
| `duplicate` | Ese `id` ya estaba | Lo saca de la cola |
| `rejected` | El mensaje no es válido (va `error` con el detalle) | Lo saca de la cola, lo anota en su registro local y lo muestra en la pantalla de estado |

**La pasarela manda `ack` sólo después de escribir el evento en disco.** Si se cae
antes, la app reenvía y la idempotencia evita el duplicado.

## 4. De la pasarela al teléfono

### `sms.out`: enviar un SMS

```json
{"type": "sms.out", "id": "o_6b1e…", "to": "+525511112222",
 "text": "Sí, les apartamos mesa a las 8.", "sim_slot": 0,
 "expires_at": "2026-10-02T03:40:00Z"}
```

- `id` lo genera la pasarela (`o_` + 16 bytes al azar en hex, `^o_[0-9a-f]{32}$`). Es la
  llave de la orden de principio a fin, y cualquier otra forma se rechaza.
- **La app deduplica por `id`.** Al reconectar, la pasarela vuelve a mandar las órdenes
  que todavía no tienen ningún `sms.status`; la app no envía dos veces un `id` que ya
  recibió, y contesta con el estado que ya conoce.
- `sim_slot` es opcional; sin él se usa la SIM de envío predeterminada.
- `text` tiene como máximo **1,000 caracteres**. Más largo, la pasarela no lo manda y
  `paynani sms send` sale con error `text_too_long`. La app lo divide con
  `SmsManager.divideMessage` y reporta en `parts` cuántos SMS fueron.
- `expires_at` se compara con el reloj **de la pasarela**: la app calcula la
  diferencia entre su reloj y `server_time` del `welcome` y la aplica, para no
  depender de que la hora del teléfono esté bien. Si ya venció, no envía y contesta
  `expired`.

### `sms.status`: qué pasó con el envío

La app contesta a cada `sms.out`, en este orden, con lo que vaya sabiendo:

```json
{"type": "sms.status", "id": "…(64 hex)", "order_id": "o_6b1e…", "status": "sent",
 "at": "2026-10-02T03:31:12-06:00", "parts": 1}
```

Una orden produce **varios** `sms.status`, así que cada uno lleva su propio `id`:
`id = hex(sha256(order_id + "\n" + status))`. El `ack` y la idempotencia van por ese
`id`, y `order_id` dice a qué orden pertenece. Así `sent` y `delivered` de la misma
orden no se confunden ni uno descarta al otro como `duplicate`.

| `status` | Significado |
|---|---|
| `accepted` | La app recibió la orden y la puso en su cola de salida |
| `sent` | El `sentIntent` de Android confirmó el envío a la red |
| `delivered` | El `deliveryIntent` confirmó la entrega. No todas las redes lo reportan |
| `failed` | Android reportó error. Va `error` con el código (`RESULT_ERROR_GENERIC_FAILURE`, `RESULT_ERROR_NO_SERVICE`, etc.) |
| `rejected` | La app no lo envió: número fuera de `allowed`, tope por hora excedido o texto vacío. Va `error` con la razón |
| `expired` | Llegó después de `expires_at` |

Los `sms.status` van por la misma cola con `ack` que los mensajes de la sección 3: un
estado no se pierde si se cae la conexión.

### Del lado del agente

`paynani sms send <número> <texto>`:

1. Normaliza el número a E.164. Si no está en `roster.md`, sale con **código 2** sin
   tocar la red, igual que `send.sh`.
2. Se manda por el teléfono emparejado. Cuando se agreguen más teléfonos
   (DEC-3), se elegirá con `--device <device_id>`.
3. Crea la orden, la anota en el ledger y la manda si el teléfono está conectado. Si
   no lo está, la orden **espera** hasta `expires_at` (por omisión 15 minutos) y
   después queda `expired`. En los dos casos se informa en pantalla, no en silencio.
4. Imprime el `id` de la orden. `paynani sms status <id>` muestra en qué estado va.

## 5. Errores

```json
{"type": "error", "code": "unknown_type", "ref": "9f2c…", "detail": "type 'sms.inn' no existe"}
```

| `code` | Cuándo | Qué pasa con la conexión |
|---|---|---|
| `bad_json` | El frame no es JSON | Sigue abierta |
| `unknown_type` | `type` desconocido | Sigue abierta |
| `missing_field` | Falta un campo obligatorio | Sigue abierta |
| `unsupported_protocol` | `hello.protocol` distinto | Se cierra con `4400` |
| `not_allowed` | Número fuera del roster | Sigue abierta |
| `rate_limited` | Se pasó `max_out_per_hour` | Sigue abierta |
| `text_too_long` | `text` de más de 1,000 caracteres | Sigue abierta |

**Códigos de cierre propios:** `4400` protocolo, `4401` token revocado o inválido,
`4409` otra conexión del mismo teléfono la reemplazó. `1001` se usa cuando la
pasarela se apaga.

## 6. Lo que entra a `events.jsonl`

Los eventos usan **el mismo sobre que el correo**, así que el *dispatcher*, los
adaptadores de cada runtime, `paynani event show` y el ledger los manejan sin un
camino aparte. Ejemplo de `sms.received`:

```json
{"schema_version": 1, "event_type": "sms.received",
 "event_id": "sms:d_3f9a1c:9f2c…", "source": "paynani",
 "account": "sms:d_3f9a1c",
 "observed_at": "2026-10-02T09:09:45Z", "sent_at": "2026-10-02T09:09:41Z",
 "sender": {"name": "Ana López", "address": "+525511112222"},
 "roster_match": true,
 "notification_text": "[sms 03:09:45, roster] Ana López +525511112222: Hola, ¿tienen mesa para 4 hoy? [paynani event show sms:d_3f9a1c:9f2c…]",
 "provider_id": "sms:9f2c…"}
```

| `event_type` | Sale de | Qué agrega al sobre |
|---|---|---|
| `sms.received` | `sms.in` | El texto completo se guarda aparte, como el cuerpo de un correo, y se ve con `paynani event show` |
| `call.missed` | `call.missed` | `started_at` |
| `call.answered` | `call.answered` | `started_at`, `duration_s` |
| `sms.gateway.offline` | Sin latido en 3 × `heartbeat_s` | `device_id`, `last_seen` |
| `sms.gateway.online` | Reconexión después de un `offline` | `device_id`, `offline_for_s` |
| `sms.unseen` | `sms.unseen` | `posted_at`, `app`, `title` (limpio, sólo en `paynani event show`) |

- `sender.address` es el E.164 o, si no hay, el remitente original (`AMAZON`).
- `sender.name` sale de la columna de nombre de `roster.md` si el número coincide.
- `roster_match` compara el **E.164 exacto** contra la columna `Phone` del roster. Un
  remitente alfanumérico nunca coincide.
- `sms.unseen` tampoco lleva `roster_match`, porque no trae número: siempre se le
  muestra al agente, con una línea fija («Google Messages recibió un mensaje que
  PaynaniApp no pudo leer (posible RCS)»). El `title` **nunca** va en
  `notification_text`, así que una notificación no puede fabricar una línea falsa.
  `paynani event show --body` se niega: no hay texto.
- `sms.gateway.offline` y `online` son de la pasarela, no de una persona: no llevan
  `roster_match` y siempre se le muestran al agente. Para que una conexión inestable
  no inunde al agente: a lo más un `offline` cada 10 minutos, y `online` sólo si
  estuvo fuera de línea más de 2 minutos.

**El texto del SMS no es confiable** y `session_watch.sh` imprime una línea por
evento, así que en `notification_text`:

- se quitan saltos de línea y caracteres de control, y el extracto se corta a
  **160 caracteres**. Un SMS no puede fabricar una línea falsa como
  `[mail …, roster]`;
- si `roster_match` es `false`, **no va el texto**, sólo el remitente y «mensaje de
  un número fuera del roster». `paynani event show --body` se niega a mostrarlo, igual
  que hoy con el correo de un remitente no reconocido.

## 7. Lo que no se permite que falle en silencio

| Falla | Qué se ve |
|---|---|
| El teléfono pierde la conexión | A los 90 s, `sms.gateway.offline` le llega al agente. La notificación de la app dice «Sin conexión con paynani». `paynani status` muestra la hora del último latido |
| Un SMS llega mientras no hay conexión | Espera en la cola del teléfono y entra al reconectar, con su `sent_at` original. La pantalla de estado de la app muestra cuántos esperan |
| La pasarela se cae antes de escribir | No hubo `ack`: la app reenvía, sin duplicado |
| Una orden de envío no llega a tiempo | Queda `expired` en el ledger, y `paynani sms send` o `paynani sms status` lo dicen |
| La red rechaza un envío | `sms.status` `failed` con el código de Android, en el ledger |
| El teléfono se reinicia | La app arranca su servicio al encender y reconecta sola |
| Llega un RCS, que no pasa por SMS | Con el acceso a notificaciones activo en la app, `sms.unseen` le llega al agente a los 60 s. Sin ese acceso, la pantalla de estado de la app dice que no puede detectarlos |

### Cómo lo vigila la pasarela (SRV-5)

- Cada 5 s la pasarela revisa al teléfono emparejado. Si no hay conexión y lleva
  **90 s** (3 × latido) sin latir, escribe **un** `sms.gateway.offline` en
  `events.jsonl` y en el ledger, con la línea `[sms-gateway HH:MM:SS] el teléfono
  d_… lleva … sin conexión (último latido …)`. Cuando vuelve, un `sms.gateway.online`
  con lo que duró. Sin `roster_match`: es de la instalación, no de un remitente.
- La marca (`offline_notified` en `device.json`) hace que sea un aviso por apagón y
  que reiniciar la pasarela no lo repita. Si el evento no se pudo escribir, la marca
  no se pone y se reintenta a los 5 s.
- Una pasarela recién arrancada no tiene a nadie conectado: el teléfono tiene 90 s
  desde el arranque para volver antes de que se diga que no está. Un teléfono
  emparejado que nunca se conectó cuenta desde el emparejamiento.
- `paynani status` y `healthcheck` leen `state/sms/` sin crearlo: por dispositivo,
  en línea o no, el último latido, las órdenes en cola, y si ya se avisó al agente.
  Un `connected` con el latido de hace más de 90 s cuenta como desconectado (si la
  pasarela murió, nadie quitó la marca). Para `healthcheck` es un aviso, no un
  problema: la instalación en sí está bien. Una pasarela que murió del todo no puede
  avisar de sí misma: eso lo cubre su supervisión (SRV-7).

## 8. Seguridad

- **Cifrado:** `wss://` y `https://` por el túnel. La pasarela no escucha en una
  interfaz pública.
- **Credenciales:** código de un solo uso con vencimiento y límite de intentos; token
  por teléfono, guardado como hash; revocable.
- **A quién se escribe:** `roster.md` en la pasarela (`paynani sms send`) **y** la
  lista `allowed` en el teléfono. Las dos tienen que dejar pasar el número.
- **Cuánto se escribe:** tope de envíos por hora en el teléfono (`max_out_per_hour`,
  por omisión 60).
- **Qué se registra:** ni la app en *release* ni la pasarela escriben en su log el
  texto de los SMS. El texto vive en el diario de eventos, como el cuerpo de un correo.

## 9. Cómo se corre (SRV-1)

```bash
PAYNANI_SMS_PUBLIC_URL=https://<túnel> python3 scripts/sms_gateway.py --port 8770
paynani sms pair       # imprime el código y el contenido del QR
paynani sms pair --web # lo mismo en el navegador: QR, teléfono emparejado y revocar (SRV-4)
paynani sms devices    # el teléfono emparejado, sin su token
paynani sms revoke     # su token deja de abrir la pasarela
```

- La pasarela escucha por omisión en el puerto **8770** (`--port` o `PAYNANI_SMS_PORT`).
  El 8765 es de la página local del onboarding y de `paynani sms pair --web`, que se
  usan con la pasarela corriendo; por eso no comparten puerto.
- **`paynani sms pair --web [--port 8765]`** (SRV-4) abre la misma página local del
  onboarding (sólo loopback, enlace con llave, CSRF) con otro contenido. Sin teléfono
  pide la dirección pública de la pasarela (se prellena con `PAYNANI_SMS_PUBLIC_URL`),
  genera el código de un solo uso y muestra el QR del §1 junto con la dirección y el
  código en texto, para escribirlos a mano. Se actualiza sola cada 3 segundos hasta
  que el teléfono se empareja. Con teléfono emparejado lista sus datos (sin el token ni
  su hash) y ofrece **Revocar**; mientras haya uno no deja generar otro código (DEC-3).
  El QR lo genera `paynani_lib/sms/qr.py`, sólo con la biblioteca estándar. La
  página sigue arriba hasta Ctrl-C.
- La pasarela escucha sólo en `127.0.0.1` (se niega a otra dirección). El túnel
  apunta a ese puerto.
- `GET /sms/health` responde `{"ok": true, "phone_connected": …}` sin secretos, para
  comprobar el túnel.
- Cada SMS y llamada sale también en stdout con la misma línea que le llega al agente.
  El texto completo no.
- Instalarla como servicio supervisado (systemd o launchd) es SRV-7.

### Interfaz local con `paynani sms send` (SRV-3)

Todo bajo `state/sms/` (700, archivos 600):

| Archivo | Quién escribe | Contenido |
|---|---|---|
| `outbox/<id>.json` | `paynani sms send` | `{"id": "o_…", "to": "+52…", "text": "…", "expires_at": "…", "sim_slot": 0}`. Se escribe atómico (temporal y `rename`) |
| `orders.jsonl` | La pasarela | Una línea por estado: `{"id": sha256(order_id + "\n" + status), "order_id", "status", "at", "error"?, "parts"?}` |
| `inbox/<id>.json` | La pasarela | El texto de cada SMS recibido; lo lee `paynani event show --body` |
| `device.json` | La pasarela y `paynani sms` | El teléfono emparejado, con el SHA-256 de su token |

La pasarela revisa `outbox/` cada segundo mientras el teléfono está conectado, manda
cada orden como `sms.out` y la saca de `outbox/` con el primer `sms.status`. Una
orden vencida se anota `expired` sin mandarse. `paynani sms status <id>` lee
`orders.jsonl`.

`paynani sms send [--wait S] [--ttl MIN] [--sim N] <número> <texto…>` (SRV-3):

- Sale con **código 2**, sin crear nada, si el número no es un teléfono, no está en la
  columna `Phone` de `roster.md`, el texto está vacío (`empty_text`) o pasa de 1,000
  caracteres (`text_too_long`). Con **código 1** si no hay teléfono emparejado.
- Escribe `outbox/<id>.json` y anota el estado `queued` en `orders.jsonl` (el único
  estado que escribe la CLI; los demás los escribe la pasarela cuando la app reporta).
- Imprime el `id`, avisa si el teléfono no está conectado y espera hasta `--wait`
  segundos (20 por omisión; 0 vuelve al instante) el primer estado final. Código 0 con
  `sent` o `delivered`, 1 con `failed`, `rejected` o `expired`. Si en ese tiempo no hay
  estado final, sale con **código 3** y dice que la orden sigue en cola;
  `paynani sms status <id>` la sigue.

## 10. Versiones

Este documento describe el protocolo **1**. Un campo nuevo y opcional no cambia la
versión, y las dos partes ignoran los campos que no conocen. Un cambio que rompe a
la otra parte sube `protocol` y se documenta aquí antes de escribir el código.
