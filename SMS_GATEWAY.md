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
 "pending": {"in": 3, "status": 0},
 "device_status": {"battery_pct": 23, "charging": false, "plugged": "none",
                   "battery_temp_c": 31.5, "measured_at": 1792343122000}}
```

`device_status` es opcional: la última lectura de batería que tiene la app, con los
mismos campos que `device.status` (sección 3) pero sin `id`, para que la pasarela la
tenga en cuanto el teléfono se reconecta. Una app anterior no lo manda.

La pasarela contesta:

```json
{"type": "welcome", "protocol": 1, "server_time": "2026-10-02T03:10:00Z",
  "heartbeat_s": 30, "allowed": ["+525511112222", "+15550001111"], "max_out_per_hour": 60,
  "accepts": ["sms.in", "call.missed", "call.answered", "sms.status", "sms.unseen", "device.status",
              "sms.human"],
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

### `device.status`: la batería del teléfono

La app lee la batería en el `Timer` que ya tiene su servicio (cada minuto) y al
conectar o desconectar la corriente (PaynaniApp#109):

```json
{"type": "device.status", "id": "7d0e…(64 hex)", "battery_pct": 23, "charging": false,
 "plugged": "none", "battery_temp_c": 31.5, "measured_at": 1792343122000}
```

- `id`, `battery_pct` (entero de 0 a 100), `charging` (booleano) y `measured_at`
  (milisegundos de época) son obligatorios. Si falta alguno o no es válido,
  `missing_field` y `ack` `rejected`.
- `measured_at` va en la hora de la pasarela: la app le suma la diferencia de reloj
  que calcula con `welcome.server_time`. Uno que cae más de **5 minutos** en el futuro
  o hace más de **30 días** se rechaza igual (`missing_field`, `ack` `rejected`) y
  queda en el log de la pasarela: una lectura del futuro dejaría todas las reales como
  `duplicate`. En `hello.device_status`, una lectura así se ignora y el `welcome` sale
  igual.
- `battery_temp_c` que no es un número finito entre −40 y 100 se descarta; la
  lectura se guarda sin temperatura.
- `plugged` es `ac`, `usb`, `wireless` o `none`; otro valor se guarda como `none`.
  `battery_temp_c` es opcional.
- Pasa por la cola del teléfono, como todo lo demás: una lectura tomada sin conexión
  llega al reconectar, con su `measured_at`.
- La app **no** la manda cada minuto: sólo cuando cambia `battery_pct` o `charging`,
  o cada **10 minutos** aunque no cambie, para que la pasarela sepa que el dato es
  reciente.
- La pasarela guarda sólo la lectura más nueva por `measured_at`: si la cola entrega
  una vieja después de una nueva, contesta `ack` `duplicate` y no la guarda. Una
  lectura no escribe ningún evento por sí misma; los avisos los decide la vigilancia
  de salud (sección 7).
- La app sólo la manda si `welcome.accepts` incluye `device.status`.

### `sms.human`: un SMS que el dueño del teléfono mandó desde PaynaniApp

Desde «Mensajes» el dueño del teléfono puede contestar una conversación o escribir un
SMS nuevo (PaynaniApp#111). Cada uno se le avisa a la pasarela, para que el agente
sepa qué contestó el humano y no le conteste encima:

```json
{"type": "sms.human", "id": "c41a…(64 hex)", "local_id": "h_6b1e…",
 "to": {"e164": "+525511112222", "raw": "5511112222"},
 "sim": {"slot": 0, "number": "+525512345678"},
 "text": "Sí, mañana a las 10 está bien.", "status": "sent", "parts": 1,
 "at": 1792343122000, "in_reply_to": "9f2c…(64 hex)", "agent_pause_min": 30}
```

- `local_id` lo genera la app al tocar Enviar: `h_` + 16 bytes al azar en hex
  (`^h_[0-9a-f]{32}$`). Así nunca se confunde con una orden del agente (`o_…`).
- Un envío produce **varios** `sms.human`, uno por estado, igual que `sms.status`:
  `id = hex(sha256(local_id + "\n" + status))`. La pasarela lo comprueba: un `id`
  que no sale de esa fórmula se rechaza con `missing_field`.

| `status` | Cuándo lo manda la app |
|---|---|
| `sent` | El `sentIntent` de Android confirmó el envío a la red |
| `failed` | Android reportó error. Va `error` con el código, como en `sms.status` |
| `delivered` | El `deliveryIntent` confirmó la entrega. No todas las redes lo reportan |

- `to.raw` es el número tal como lo escribió o lo eligió el humano; `to.e164`, ese
  número en E.164 con la región de la SIM, o `null` si no se puede (un número corto).
  La pasarela lo recalcula como `from.e164` en `sms.in`.
- `sim` es opcional: la SIM por la que salió, con la misma forma que en `sms.in`.
- `text` va completo, con hasta **1,000 caracteres**, el mismo tope que `sms.out`. Más
  largo, la app no deja enviarlo.
- `at` es la hora del estado en milisegundos de época, en la hora de la pasarela (la
  app le suma la diferencia con `welcome.server_time`), como `device.status`.
- `in_reply_to` es opcional: el `id` del último `sms.in` de esa conversación que la
  app ya mandó a la pasarela. Así el agente sabe a qué mensaje contestó el humano. Un
  SMS nuevo, sin un `sms.in` antes, no lo lleva.
- `agent_pause_min` es la pausa del agente que el dueño configuró en los ajustes de
  PaynaniApp (APP-C4): un entero de 0 a 1,440; 0 es sin pausa y 30 el valor por
  omisión. Si no viene, la pasarela usa 30; fuera de ese rango, `missing_field`. Ver
  «La pausa del agente» en la sección 4.
- `local_id`, `to.raw`, `text`, `status` y `at` son obligatorios. Si falta alguno o no
  es válido, `missing_field` y `ack` `rejected`. `at` tiene el mismo rango que
  `measured_at` de `device.status`: hasta 5 minutos en el futuro y 30 días atrás.
- Pasa por la cola con `ack`: sin conexión, el SMS sale igual y los estados llegan al
  reconectar, con su `at`.
- **Lo que el humano manda no pasa por las reglas de `sms.out`** (Q98 y Q99 de
  PaynaniApp#111): puede escribir a cualquier número, no sólo a los de `allowed`, y
  sus SMS no cuentan para `max_out_per_hour`. Esas reglas protegen de un agente que se
  desboca; el dueño del teléfono las decide él.
- Sólo se detecta lo que se manda desde PaynaniApp, no lo que se manda desde otra app
  de SMS (Q100).
- La app sólo lo manda si `welcome.accepts` incluye `sms.human`. Con una pasarela
  anterior el SMS sale igual, y «Mensajes» avisa «paynani no recibe tus respuestas
  todavía: actualízalo», como la fila Batería de Estado.

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

### La pausa del agente después de que el humano responde

Cuando el humano contesta un número desde PaynaniApp, el agente no le contesta a ese
número durante la pausa, salvo que el humano se lo pida (Q101 de PaynaniApp#111):

- La pausa empieza con el `sms.human` `sent` y dura `agent_pause_min` minutos:
  `pause_until = at + agent_pause_min`, con el reloj de la pasarela. Un `failed` no
  pausa: ese SMS no salió.
- Va por número E.164: un `sms.human` con `to.e164` `null` no pausa nada, porque el
  agente no puede escribirle a ese número de todos modos (no está en el roster).
- Un `sms.human` nuevo al mismo número la reinicia con su propio `agent_pause_min`;
  con 0 la termina.
- Durante la pausa, `paynani sms send` a ese número sale con **código 4**
  (`human_replied`) sin crear la orden, y dice hasta cuándo. `--override-pause` la
  manda de todos modos, sólo cuando el humano se lo pidió al agente (`AGENTS.md`).
- `paynani sms thread <número>` muestra la pausa vigente, si la hay.

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

Los mensajes del Roster y las reglas tienen sus propios códigos (sección 11).

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
| `sms.gateway.battery_low` | La batería, sin cargar, bajó del aviso o del crítico (sección 7) | `device_id`, `battery_pct`, `charging`, `level` (`warn` o `critical`) |
| `sms.gateway.battery_ok` | Después de un `battery_low`: empezó a cargar o volvió a superar el aviso | `device_id`, `battery_pct`, `charging` |
| `sms.unseen` | `sms.unseen` | `posted_at`, `app`, `title` (limpio, sólo en `paynani event show`) |
| `sms.human_sent` | `sms.human` con `sent` o `failed` | `recipient` (como `sender`), `status`, `parts`, `in_reply_to` (el `event_id` de ese `sms.received`, si lo hay), `agent_pause_min`, `pause_until` (sólo con `sent` y pausa mayor que 0). El texto se guarda aparte, como en `sms.received` |

- `sender.address` es el E.164 o, si no hay, el remitente original (`AMAZON`).
- `sender.name` sale de la columna de nombre de `roster.md` si el número coincide.
- `roster_match` compara el **E.164 exacto** contra la columna `Phone` del roster. Un
  remitente alfanumérico nunca coincide.
- `sms.human_sent` se escribe **una vez** por envío: con `sent` o con `failed`, el que
  llegue primero. `delivered` sólo actualiza el ledger (`state/sms/human.jsonl`,
  sección 9). Lleva `roster_match` del **destinatario**, con la misma regla, y la línea
  dice quién lo mandó: «[sms-human 03:31:12, roster] Tú → Ana López +525511112222: Sí,
  mañana a las 10 está bien. [paynani event show sms-human:d_3f9a1c:c41a…]». El texto
  lo escribió el dueño, pero pasa por la misma limpieza de `notification_text`, y con
  un destinatario fuera del roster no va el texto.
- Un `sms.out` del agente **nunca** produce `sms.human_sent`: sólo sale de un
  `sms.human`, que la app manda únicamente cuando el humano toca Enviar.
- `sms.unseen` tampoco lleva `roster_match`, porque no trae número: siempre se le
  muestra al agente, con una línea fija («Google Messages recibió un mensaje que
  PaynaniApp no pudo leer (posible RCS)»). El `title` **nunca** va en
  `notification_text`, así que una notificación no puede fabricar una línea falsa.
  `paynani event show --body` se niega: no hay texto.
- `sms.gateway.offline` lleva también `last_battery_pct` si la app mandó alguna
  lectura, y la línea dice «última batería 8 % a las 03:12»: así se sabe si el
  teléfono probablemente se descargó.
- `sms.gateway.offline`, `online`, `battery_low` y `battery_ok` son de la pasarela, no de una persona: no llevan
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
| La batería del teléfono se acaba | Sin cargar, `sms.gateway.battery_low` al bajar de 25 % (`warn`) y de 10 % (`critical`), una vez cada uno por descarga; `battery_ok` al conectar el cargador. Si aun así se apaga, `sms.gateway.offline` dice la última batería |
| Llega un RCS, que no pasa por SMS | Con el acceso a notificaciones activo en la app, `sms.unseen` le llega al agente a los 60 s. Sin ese acceso, la pantalla de estado de la app dice que no puede detectarlos |

### Cómo lo vigila la pasarela (SRV-5)

- Cada 5 s la pasarela revisa al teléfono emparejado. Si no hay conexión y lleva
  **90 s** (3 × latido) sin latir, escribe **un** `sms.gateway.offline` en
  `events.jsonl` y en el ledger, con la línea `[sms-gateway HH:MM:SS] el teléfono
  d_… lleva … sin conexión (último latido …)`, que termina pidiendo que abran Paynani
  en el teléfono si no vuelve sola, porque un ahorro de energía del fabricante pudo
  haberla cerrado (INSTALL.md §5.2, paso 4). Cuando vuelve, un `sms.gateway.online`
  con lo que duró. Sin `roster_match`: es de la instalación, no de un remitente.
- El «último latido» (`last_seen` en `device.json`) es la hora del último frame que
  mandó el teléfono, no la de la última revisión: si el teléfono se queda sin red,
  la conexión sigue abierta hasta que el watchdog la cierra (3 × latido sin frames),
  y los 90 s se cuentan desde ese último frame (#385).
- Al volver, el teléfono manda lo que tenía en cola en cuanto se conecta, así que los
  `sms.received` de ese apagón pueden quedar en `events.jsonl` **antes** que el
  `sms.gateway.online`. No se pierde nada; sólo el orden no es el de la reconexión.
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


### La batería (PaynaniApp#109)

- En la misma revisión de cada 5 s, con el teléfono **conectado** y **sin cargar**:
  - al bajar de `PAYNANI_SMS_BATTERY_WARN_PCT` (25 % por omisión) escribe
    `sms.gateway.battery_low` con `level` `warn`;
  - al bajar de `PAYNANI_SMS_BATTERY_CRITICAL_PCT` (10 %), otro con `level`
    `critical`.

  Los dos umbrales viven en `sms.env` (INSTALL.md). Un valor inválido, o un crítico
  que no queda por debajo del aviso, vuelve a 25 y 10, y la pasarela lo dice en su log
  al arrancar. `paynani status` muestra los umbrales con los que avisa.
- **Una vez por nivel y por descarga:** la marca `battery_alert_level` en
  `device.json` sobrevive a un reinicio de la pasarela, como `offline_notified`. A lo
  más son dos avisos por descarga. Si la batería baja de golpe por debajo del crítico,
  sale sólo `critical`.
- **La recuperación:** `sms.gateway.battery_ok` sale una vez, cuando el teléfono empieza
  a cargar o cuando vuelve a superar el aviso por **5 puntos** (30 % por omisión). Los
  5 puntos evitan que un teléfono que oscila en el borde mande avisos de ida y vuelta.
  Luego la marca se limpia.
- **Un cable flojo no repite avisos:** `battery_low` sólo sale cuando el teléfono lleva
  **5 minutos** sin cargar (`battery_unplugged_at` en `device.json`, con el reloj de la
  pasarela). Un cargador que conecta y desconecta cada minuto da un `warn`, un
  `battery_ok` y nada más hasta que pasen 5 minutos seguidos sin cargar.
- **Un dato viejo no avisa:** si la última lectura **llegó** hace más de **20 minutos**
  (la app manda una cada 10, y un ahorro de energía del fabricante puede congelarla,
  #92), no sale ningún aviso de batería por ella, y `paynani status` la marca como
  vieja. Se mide con la hora de llegada (`battery_received_at`, reloj de la pasarela),
  no con `measured_at`: un reloj del teléfono atrasado no apaga los avisos, y uno
  adelantado no deja el dato fresco para siempre.
- **Sin lecturas** (una app anterior), no hay avisos de batería y `paynani status` dice
  «battery unknown».
- **Sin conexión** no hay avisos de batería: para eso está `sms.gateway.offline`, que
  ahora incluye la última batería conocida.

## 8. Seguridad

- **Cifrado:** `wss://` y `https://` por el túnel. La pasarela no escucha en una
  interfaz pública.
- **Credenciales:** código de un solo uso con vencimiento y límite de intentos; token
  por teléfono, guardado como hash; revocable.
- **A quién se escribe:** `roster.md` en la pasarela (`paynani sms send`) **y** la
  lista `allowed` en el teléfono. Las dos tienen que dejar pasar el número.
- **Cuánto se escribe:** tope de envíos por hora en el teléfono (`max_out_per_hour`,
  por omisión 60).
- **Lo que manda el humano (`sms.human`):** no pasa por el roster, `allowed` ni el tope
  por hora, porque lo decide el dueño del teléfono (PaynaniApp#111). Ningún SMS del
  humano sale sin que el humano toque Enviar en PaynaniApp, y la pasarela no tiene
  forma de pedirlo: el agente sigue enviando sólo con `sms.out`. El texto viaja por la
  misma conexión autenticada que un `sms.in`.
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
| `inbox/<id>.json` | La pasarela | El texto de cada SMS recibido, y de cada `sms.human` (PaynaniApp#111); lo lee `paynani event show --body` |
| `sent/<id>.json` | La pasarela | La orden de `outbox/` cuando el teléfono ya la tomó: el estado no dice a quién ni qué, y `paynani sms thread` lo necesita |
| `human.jsonl` | La pasarela | Una línea por cada `sms.human` guardado: `{"id", "local_id", "to", "status", "at", "agent_pause_min", "parts"?, "error"?, "in_reply_to"?, "pause_until"?, "event_id"?}`. `to` es el E.164, o el número tal cual si no tiene; `event_id` sólo en el estado que escribió el evento. De aquí salen la pausa del agente y `paynani sms thread` |
| `device.json` | La pasarela y `paynani sms` | El teléfono emparejado, con el SHA-256 de su token |

La pasarela revisa `outbox/` cada segundo mientras el teléfono está conectado, manda
cada orden como `sms.out` y la pasa de `outbox/` a `sent/` con el primer `sms.status`. Una
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
- Sale con **código 4** (`human_replied`), sin crear nada, si el número está en la
  pausa del agente (sección 4); `--override-pause` la ignora.

`paynani sms thread [--limit N] <número>` (PaynaniApp#111) muestra la conversación con
ese número en orden de hora: los `sms.received`, las órdenes `sms.out` del agente con su
último estado, y los `sms.human_sent`, cada uno marcado (`recibido`, `agente`,
`humano`; en la salida, `received`, `agent` y `human`) con su último estado, más la
pausa vigente si la hay. Es el contexto completo para el agente. Las órdenes del agente
de antes de esta versión no salen: la pasarela las borraba de `outbox/`.
Con un número fuera del roster, igual que `paynani event show --body`, no muestra
textos.

## 10. Versiones

Este documento describe el protocolo **1**. Un campo nuevo y opcional no cambia la
versión, y las dos partes ignoran los campos que no conocen. Así entraron
`sms.unseen` y `device.status` (con `hello.device_status`): una pasarela que no los
anuncia en `accepts` nunca los recibe, y una app que no los manda sólo deja la batería
como desconocida. `sms.human` entró igual: con una pasarela que no lo anuncia, el SMS
del humano sale y la app sólo avisa que paynani no lo recibe. Los mensajes del Roster
(sección 11) también: con una pasarela que no los anuncia, la app no muestra «Roster».
Un cambio que rompe a la otra parte sube `protocol` y se documenta aquí antes de
escribir el código.

## 11. Roster y reglas desde PaynaniApp (#409)

Desde la pantalla «Roster» el dueño ve y edita, en su teléfono emparejado, el roster
de cada cuenta de la instalación y las instrucciones del agente para cada contacto
(PRD #409). Esta sección es el contrato entre la app y la pasarela. El formato de las
reglas y lo que paynani hace con ellas están en el PRD (I-1 a I-6).

### Cómo se habla

- **Sólo el teléfono emparejado**, por su WebSocket autenticado. Nada de esto se puede
  pedir por SMS ni por correo (Q5), y la pasarela no tiene otra puerta para hacerlo.
- **Pregunta y respuesta, sin cola.** A diferencia de la sección 3, estos mensajes
  **no** pasan por la cola SQLite de la app. Sin conexión no se edita (Q7): la app
  muestra «Sin conexión con paynani» y no guarda nada.
- Cada pedido lleva un `id` que genera la app: `q_` + 16 bytes al azar en hex
  (`^q_[0-9a-f]{32}$`). La pasarela contesta **una sola vez**, con `result` o con
  `error`, y en los dos casos con `ref` igual a ese `id`:

```json
{"type": "result", "ref": "q_5d0c…", "ok": true, "data": {…}}
{"type": "error", "code": "invalid", "ref": "q_5d0c…", "field": "email",
 "reason": "email_format", "detail": "«ana@» no es un correo válido"}
```

- La app arma el mensaje para el dueño con `code`, `field` y `reason`, en su idioma.
  `detail` es opcional, en español y para el log: la app lo muestra sólo si no conoce
  el `reason`.

- La app espera la respuesta **15 segundos**. Mientras no llegue, el cambio **no** se
  muestra como guardado (R-5).
  - Si pasan los 15 segundos con la conexión viva, la escritura pudo haberse aplicado:
    la app reenvía el pedido **una vez, con el mismo `id`**. Si ya se aplicó, la
    pasarela contesta `replayed`. Si tampoco llega esa respuesta, la app avisa y vuelve
    a leer la lista.
  - Si se cae la conexión, la app avisa y vuelve a leer la lista al reconectar.
- **Reenvío seguro.** Si la app reenvía un pedido de escritura con el **mismo `id`**
  (porque se cortó antes de la respuesta), la pasarela no lo aplica dos veces:
  contesta el mismo `result` de la primera vez, con `"replayed": true`. Guarda las
  respuestas de los últimos 64 `id` durante 10 minutos.
- **Sin pisar cambios ajenos.** Cada lectura trae un `etag`: el SHA-256 en hex del
  archivo tal como está en disco. Cada escritura manda el `etag` que leyó. Si el
  archivo cambió entretanto (otra edición, `paynani roster add` en la terminal), la
  pasarela no escribe y responde `conflict` con el `etag` actual. La app vuelve a
  leer y le muestra al dueño la versión nueva.

### Anuncio en el `welcome`

La pasarela que entiende estos mensajes los pone en `welcome.accepts`, como cualquier
tipo nuevo (sección 10):

```json
"accepts": ["sms.in", …, "sms.human", "roster.accounts", "roster.list", "roster.save",
            "roster.delete", "rules.get", "rules.preview", "rules.save",
            "rules.get_default", "rules.save_default"]
```

- La app muestra «Roster» en el menú sólo si `accepts` incluye `roster.list`, y el
  editor de instrucciones sólo si incluye `rules.get`.
- Además, la app revisa **cada tipo** en `accepts` antes de mandarlo. Por ejemplo, sin
  `rules.preview` la vista previa usa el `effective` que trajo `rules.get`, y sin
  `roster.delete` no ofrece la baja.
- Una pasarela anterior no los anuncia, y si la app los mandara de todos modos
  contestaría `unknown_type` (sección 5).

### Las cuentas y las filas

- **`account`** dice qué roster se usa: `null` es la cuenta del agente (`roster.md`),
  y un id de `accounts.json` (`^[a-z0-9][a-z0-9-]{0,30}$`) es esa cuenta adicional. Un
  id que no existe da `not_found`.
- **`row`** es la posición del contacto en la tabla de contactos de ese roster,
  empezando en 1, tal como la devolvió `roster.list`. Sólo vale junto con su `etag`:
  si el archivo cambió, la escritura responde `conflict` antes de mirar `row`.
- **La fila del dueño** es el primer contacto con `Type` = `Human` de cada roster.
  `roster.list` la marca con `owner: true`. No se puede borrar desde la app, y al
  editarla su `type` no puede dejar de ser `Human` (R-4).

### `roster.accounts`: las cuentas de la instalación

```json
{"type": "roster.accounts", "id": "q_…"}
```

```json
{"type": "result", "ref": "q_…", "ok": true, "data": {"accounts": [
  {"account": null, "email": "agente@dominio.com", "roster": "roster.md", "members": 6, "status": "ok"},
  {"account": "ventas", "email": "ventas@dominio.com", "roster": "rosters/ventas.md", "members": 2,
   "status": "ok"}]}}
```

- La primera es siempre la cuenta del agente; después, las de `accounts.json` en su
  orden.
- `status`: `ok`, `missing` (el archivo no existe: la lista sale vacía y la primera alta
  lo crea) o `unreadable` (no se puede leer ni reescribir: la app lo muestra y no deja
  editar esa cuenta).
- No trae contraseñas ni nada de `.env`.

### `roster.list`: los contactos de una cuenta

```json
{"type": "roster.list", "id": "q_…", "account": null}
```

```json
{"type": "result", "ref": "q_…", "ok": true, "data": {
  "account": null, "etag": "9c1e…(64 hex)",
  "columns": ["Name", "Email", "Type", "GitHub", "Phone", "Rules"],
  "members": [
    {"row": 1, "name": "Julián Flores", "email": "julian@dominio.com", "type": "Human",
     "github": "julianflores", "phones": ["+525511112222"], "owner": true,
     "rules": "julian-flores-3f2a", "has_rules": true, "rules_enabled": true},
    {"row": 2, "name": "Iris", "email": "iris@dominio.com", "type": "AI Agent",
     "github": "", "phones": [], "owner": false,
     "rules": null, "has_rules": false, "rules_enabled": false}],
  "default_rules": true}}
```

- `columns` son las columnas que tiene la tabla de contactos de ese roster, en su
  orden y con los nombres canónicos (`Name`, `Email`, `Type`, `GitHub`, `Phone`,
  `Rules`). Así la app distingue «este contacto no tiene teléfono» de «este roster no
  tiene la columna `Phone`», y deshabilita el campo en el segundo caso.
- `phones` es la celda `Phone` separada por comas, cada número ya en E.164. Una fila
  puede traer varios, y la app los edita como lista. Sin columna `Phone`, `phones` es
  `[]`; sin `GitHub`, `github` es `""`.
- `rules` es el valor de la columna `Rules` (o `null`). `has_rules` dice si
  `rules/<id>.md` existe, y `rules_enabled`, si además tiene `enabled: true`.
- `default_rules` dice si existe `rules/default.md`.
- Sólo la tabla de contactos. Los notificadores (la sección 2 de `roster.md`) no se
  muestran ni se editan desde la app.

### `roster.save`: alta o edición

```json
{"type": "roster.save", "id": "q_…", "account": null, "etag": "9c1e…", "row": null,
 "member": {"name": "Ana Ruiz", "email": "ana@dominio.com", "type": "Human",
            "github": "", "phones": ["+525511113333"]}}
```

- `row: null` es un alta, que se agrega al final de la tabla. Un número es la edición
  de esa fila.
- `member` lleva siempre los cinco campos, ya completos. Lo que no venga se toma como
  vacío, no como «sin cambio».
- **Validación** (R-3); la primera que falla responde `invalid` con `field` y `reason`:

| `field` | `reason` | Cuándo |
|---|---|---|
| `name` | `required` | Vacío, o con `\|` o un salto de línea |
| `email` | `email_format` | No es un correo válido |
| `phones` | `phone_e164` | Un número no está en E.164 (`^\+[1-9][0-9]{7,14}$`) |
| `email` | `no_channel` | Sin correo y sin teléfono |
| `email` | `duplicate_email` | Otra fila de ese roster ya tiene ese correo (sin distinguir mayúsculas) |
| `phones` | `duplicate_phone` | Otra fila de ese roster ya tiene ese número |
| `type` | `type` | No es `Human`, `AI Agent` ni vacío |
| `github` | `github` | No es un login de GitHub válido |
| `type` | `owner_type` | La fila del dueño dejaría de ser `Human` |
| `phones` | `no_phone_column` | Trae teléfonos y el roster no tiene columna `Phone` (ver abajo) |
| `github` | `no_github_column` | Trae GitHub y el roster no tiene columna `GitHub` |

- **Columnas.** La pasarela no agrega columnas por su cuenta (Q3: los cinco campos de
  hoy). Si el roster no tiene la columna `Phone` o `GitHub` y el campo viene lleno,
  responde `invalid`. La app deja esos campos deshabilitados si no están en
  `columns`, y el dueño agrega la columna con `paynani roster`.
- **Escritura** (sección 4.4 del PRD): copia fechada de `roster.md` antes, escritura
  atómica con el mismo mecanismo de `roster_cli` (temporal, relectura, y se revierte si
  no cuadra), una línea en el log de cambios y el correo al humano. Si la relectura no
  cuadra, se revierte y responde `write_failed`.
- **Respuesta:** la lista completa, como `roster.list`, con el `etag` nuevo y el `row`
  de la fila guardada:

```json
{"type": "result", "ref": "q_…", "ok": true, "data": {"row": 7, "etag": "41aa…",
 "columns": [ … ], "members": [ … ]}}
```

- Cuando la edición cambia un teléfono, la pasarela manda además el `allowed` nuevo,
  como hoy cuando cambia el roster (sección 2).

### `roster.delete`: baja

```json
{"type": "roster.delete", "id": "q_…", "account": null, "etag": "9c1e…", "row": 2}
```

- La fila del dueño responde `owner_row` y no se toca.
- Misma copia fechada, escritura, log y correo que `roster.save`. Responde la lista
  nueva con su `etag`.
- Si el contacto tenía reglas, `rules/<id>.md` **no se borra**: se renombra a
  `rules/<id>.removed-<AAAAMMDDTHHMMSSZ>.md`. Si alguien vuelve a darlo de alta, sus
  reglas se recuperan a mano.

### `rules.get` y `rules.preview`: leer las instrucciones

```json
{"type": "rules.get", "id": "q_…", "account": null, "row": 1, "roster_etag": "9c1e…"}
```

```json
{"type": "result", "ref": "q_…", "ok": true, "data": {
  "row": 1, "name": "Julián Flores", "email": "julian@dominio.com",
  "rules": "julian-flores-3f2a", "exists": true, "etag": "77b0…",
  "text": "---\nversion: 1\nenabled: true\nreply:\n  email: normal\n  sms: never\n…---\n\n## General\n…",
  "effective": "## General\n…\n\n## SMS\n…"}}
```

- `roster_etag` es el de la lista que tiene la app. Si `roster.md` cambió (alguien quitó
  una fila desde la terminal y `row: 3` ya es otro contacto), responde `conflict` y no
  muestra las reglas de otra persona. La respuesta trae además `name` y `email` de la
  fila, y la app comprueba que sean los del contacto que abrió.
- `text` es el archivo completo, cabecera incluida. Sin archivo: `exists: false`,
  `text` y `etag` vacíos (`""`), y `effective` es la regla general sola.
- `effective` es la **regla efectiva** (R-7): `rules/default.md` con las secciones del
  contacto aplicadas como dice I-4b (una sección con el mismo nombre sustituye a la
  general completa). La calcula la pasarela, para que la app y el agente vean
  exactamente lo mismo.
- `rules.preview` es igual pero con un `text` que manda la app y no se guarda, para la
  vista previa mientras se edita:

```json
{"type": "rules.preview", "id": "q_…", "account": null, "row": 1, "roster_etag": "9c1e…",
 "text": "---\n…"}
```

  Lleva `roster_etag` por lo mismo que `rules.get`. Responde `row`, `name`, `email` y
  `effective`, o el mismo `invalid` que daría `rules.save`. No escribe nada.

### `rules.save`: escribir las instrucciones

```json
{"type": "rules.save", "id": "q_…", "account": null, "row": 1, "etag": "77b0…",
 "roster_etag": "9c1e…", "text": "---\nversion: 1\n…"}
```

- `etag` es el del archivo de reglas que se leyó (`""` si no existía). `roster_etag`,
  el de `roster.md`: hace falta porque la fila tiene que seguir siendo la misma, y
  porque la primera vez se escribe la columna `Rules`.
- **El id.** Si la fila no tiene `Rules`, la pasarela genera uno (el nombre en minúsculas
  sin acentos, con guiones, más 4 hex al azar: `ana-ruiz-9b1c`, que cumple
  `^[a-z0-9][a-z0-9-]{0,47}$`) y lo escribe en la columna `Rules` de esa fila, con el
  mismo mecanismo atómico. Si el roster no tiene la columna `Rules`, la agrega: es la
  única columna que la pasarela agrega por su cuenta (I-1).
- **La cabecera** la valida la pasarela (I-2, I-6), y la primera que falla responde
  `invalid`:

| `field` | `reason` | Cuándo |
|---|---|---|
| `text` | `too_large` | Más de 32,768 bytes en UTF-8 |
| `header` | `header_missing` | No empieza con una cabecera YAML entre `---` |
| `header.version` | `value` | No es `1` |
| `header.enabled` | `value` | No es `true` ni `false` |
| `header.reply.email`, `header.reply.sms` | `value` | No es `normal` ni `never` |
| `header` | `unknown_key` | Trae una llave que no es de las de arriba ni `updated_at`/`updated_by` |

- `updated_at` y `updated_by` **los escribe la pasarela**, con la hora y el
  `device_id` del teléfono (`updated_by: phone d_3f9a1c`). Si la app los manda, se
  reemplazan.
- Antes de escribir, la copia fechada del archivo (I-4c). Después, el log y el correo
  al humano, igual que en el roster.
- **Respuesta:** `{"rules": "<id>", "etag": "…", "roster_etag": "…", "effective": "…"}`.
- **Para dejar de usarlas** sin perderlas se guarda con `enabled: false` (I-4). Borrar
  el archivo desde la app no entra en v1.

### `rules.get_default` y `rules.save_default`: las reglas generales

Iguales a `rules.get` y `rules.save`, sin `account`, `row` ni `roster_etag`, sobre
`rules/default.md`. `rules.get_default` sin archivo responde `exists: false`, y el
primer `rules.save_default` lo crea. La cabecera es la misma; en `default.md` la
política `reply` es la de todos los contactos que no tengan la suya.

### Errores de esta sección

Además de los de la sección 5:

| `code` | Cuándo |
|---|---|
| `not_found` | `account` no existe, o `row` está fuera de la tabla |
| `conflict` | El `etag` (o el `roster_etag`) no es el del archivo en disco. Va `etag` con el actual |
| `invalid` | Un campo no pasa la validación. Van `field` y `reason` |
| `owner_row` | Se quiso borrar la fila del dueño |
| `write_failed` | La escritura no se pudo hacer o no cuadró al releer, y se revirtió. Nada cambió |
| `unreadable` | El roster o el archivo de reglas no se puede leer |

Ningún error cierra la conexión.

### Lo que se registra

- **Log de cambios** de la instalación: una línea JSON por cambio, con la hora, el
  `device_id`, el mensaje (`roster.save`, `rules.save`…), la cuenta, la fila y el
  nombre del contacto, el `etag` de antes y el de después, y la ruta de la copia
  fechada. **No** lleva el texto de las reglas ni los datos del contacto que no
  cambiaron.
- **Correo al humano** por cada cambio, con qué cambió y desde qué teléfono (Q5).
- **Nada va a `events.jsonl`**: estos mensajes no son avisos para el agente, y el
  roster y las reglas no salen hacia otros agentes (PRD, sección 5). El agente ve las
  reglas sólo cuando le llega un mensaje de ese contacto, por la ruta
  `[reglas: rules/<id>.md]` del aviso (A-1).
- La pasarela no escribe en su log el texto de las reglas ni los datos de los
  contactos, igual que con el texto de los SMS (sección 8).
