# La API de paynani

La API deja que otro agente o un programa use tu instalación de paynani sin
entrar a PaynaniWeb. Puede leer el correo y los SMS, editar el roster y sus
reglas, agregar cuentas de correo y enviar SMS desde el teléfono emparejado. Cada
quien entra con un API Token que tú creas y que puedes revocar en cualquier
momento.

Es la documentación del PRD [#491](https://github.com/iaaorgmx/paynani/issues/491)
(paraguas [#492](https://github.com/iaaorgmx/paynani/issues/492)). La guía para el
agente, en inglés, está en `/api/agents.md` de tu instalación (en el repo,
`scripts/paynani_lib/assets/api_agents.md`), con cada parámetro y ejemplos de
`curl`. Este documento dice lo mismo para ti.

## Dónde está

- **En PaynaniWeb.** `POST /api/agent` en la misma dirección del túnel que la web.
  No hay que encender nada aparte.
- **`/api/agents.md` no pide contraseña ni token.** Es sólo la guía y no lleva
  datos de la instalación.

## Dar acceso a un agente

1. En PaynaniWeb, abre «API Tokens» y pulsa «Crear token».
2. Ponle un nombre que diga para qué es (por ejemplo `citas`). Ese nombre aparece
   en «Mensajes» junto a cada SMS que mande el token.
3. Elige cuándo vence: 5 minutos, 1 hora, 1 día, 7 días, 30 días, una fecha o «no
   vence». Lo más corto que sirva es lo más seguro.
4. Elige los permisos (la tabla de abajo) y, si quieres, otros topes de SMS.
5. Escribe la contraseña de la web.
6. El token se ve una sola vez. Copia el mensaje listo para el agente, que trae
   el token, el vencimiento en UTC y la dirección de `/api/agents.md`, y mándaselo
   por un canal privado.

paynani guarda sólo el SHA-256 y el prefijo del token (`pn_` y 8 caracteres) en
`web/api_tokens.json`, con permisos 600. Si pierdes el token, revócalo y crea otro.

Para quitar el acceso, abre el token en «API Tokens» y pulsa «Revocar». Pide la
contraseña, y un token revocado no se puede reactivar.

## Permisos

| Permiso | Deja usar |
|---|---|
| `read` | `ListAccounts`, `ListMail`, `GetMailThread`, `ListSmsConversations`, `GetSmsThread`, `ListSmsReplies`, `ListWhatsAppConversations`, `GetWhatsAppThread`, `ListRoster`, `GetRules`, `GetDefaultRules`, `GetCatchAll` |
| `roster.write` | `SaveRosterContact`, `DeleteRosterContact`, `SaveRules`, `SaveDefaultRules` |
| `accounts.write` | `AddAccount`, `RemoveAccount` |
| `catchall.write` | `SaveCatchAll` |
| `sms.send` | `SendSms`, `GetSmsStatus` |

`GetTokenInfo` y `GetUsage` funcionan con cualquier permiso. Una acción sin su
permiso responde `forbidden`. `catchall.write` va aparte de `roster.write` porque
encender el Catch-All deja que tu agente lea los SMS de números fuera del roster;
ningún token creado antes lo tiene. El perfil y la contraseña de la web no están en la
API.

## Las acciones

| Acción | Qué hace |
|---|---|
| `GetTokenInfo` | Nombre, prefijo, permisos, topes, vencimiento y último uso del token |
| `GetUsage` | Llamadas aceptadas y SMS encolados de este token en ventanas móviles de 60 segundos, 1 hora y 24 horas; incluye la llamada actual |
| `ListAccounts` | Las cuentas de correo de la instalación |
| `ListMail` | Recibidos y enviados de una cuenta, de 50 en 50, como la web |
| `GetMailThread` | El hilo de un correo, leído de IMAP en ese momento |
| `ListSmsConversations` | Las conversaciones SMS, de 50 en 50 |
| `GetSmsThread` | Una conversación, con estados y llamadas; un SMS que llegó con el Catch-All activo lleva `catch_all: true` |
| `ListSmsReplies` | Las respuestas a los SMS de ese token desde una hora (`since`) |
| `ListWhatsAppConversations` | Las conversaciones de WhatsApp, de la más reciente a la más vieja, de 50 en 50 (`limit` de 1 a 100, `before`) |
| `GetWhatsAppThread` | Una conversación de WhatsApp (`number`), con el estado de lo enviado |
| `SendSms` | Envía un SMS |
| `GetSmsStatus` | El estado de una orden del token |
| `ListRoster`, `SaveRosterContact`, `DeleteRosterContact` | El roster por cuenta, con el mismo servicio que la web y PaynaniApp |
| `GetRules`, `SaveRules`, `GetDefaultRules`, `SaveDefaultRules` | Instrucciones por contacto y generales |
| `GetCatchAll`, `SaveCatchAll` | El Catch-All de SMS (`rules/catch-all.md`): si está activo y sus instrucciones; cada cambio te llega por correo |
| `AddAccount`, `RemoveAccount` | Como «Agregar cuenta» y «Quitar esta cuenta», con la prueba de IMAP y SMTP |

Cuando la API agrega o quita una cuenta, te llega el mismo correo que cuando lo
haces en la web, con el nombre y el prefijo del token.

## WhatsApp, sólo lectura

Con WhatsApp activado (`INSTALL.md` 5.4), `ListWhatsAppConversations` y
`GetWhatsAppThread` dejan que el agente lea los mismos hilos que ves en «Mensajes de
WhatsApp», con el permiso `read` (PRD #550 FR-26). La API no manda mensajes de
WhatsApp: no hay acción para eso.

- De un número que no está en el roster sólo se ven la hora y la dirección de cada
  mensaje, con `hidden: true`, ni el texto ni el archivo (FR-16a). La excepción es un
  mensaje que llegó con el Catch-All activo, mientras siga activo. Es la misma regla que
  en la web y en PaynaniApp, y la aplica el servicio de WhatsApp, no la API.
- `name` sale del roster, nunca del nombre que el contacto puso en WhatsApp.
- Las páginas van con `before`: se manda el `next_before` que llegó; `null` es que no
  hay más.
- Sin WhatsApp activado, o con el servicio caído, responden `whatsapp_unavailable`.

## Los SMS que manda la API

- **Salen de tu teléfono,** como los del agente, y en «Mensajes» se ven como
  «API: <token>». PaynaniApp tiene que ser la 0.9.0 o posterior; con una anterior,
  la API responde `app_outdated`.
- **A cualquier número,** en E.164 o con la región de la SIM del teléfono, sin
  pasar por el roster. Por eso los topes son por token.
- **Cada envío lleva una `idempotency_key`.** Si el agente repite la llamada con
  la misma llave, recibe la misma orden y el SMS no sale dos veces.
- **Con el teléfono desconectado,** la orden espera 15 minutos en la cola, como
  las demás, y la respuesta lo dice. Si el teléfono no vuelve, vence.
- **Tu SMS va primero.** Si acabas de escribirle a un número desde el teléfono o la
  web con la pausa del agente, la API responde `human_replied` hasta que termine la
  pausa.

### Topes

- **60 llamadas por minuto por token.** Pasarse responde `rate_limited`.
- **SMS por token: 30 por hora y 200 por día,** salvo que pongas otros al crear el
  token. Pasarse responde `quota_exceeded` con la hora en que se libera.
- **Android deja a cada app unos 30 SMS cada 30 minutos.** Por encima de eso, el
  teléfono te pregunta antes de enviar más, y la orden puede quedarse en
  `accepted` o terminar en `failed`. Si un agente va a mandar muchos, que los
  reparta.
- **10 fallos de autenticación en 15 minutos desde una dirección** la bloquean 15
  minutos (`too_many_attempts`).

## Respuestas y bajas

- **Respuestas.** Si un número al que la API le envió un SMS en los últimos 7 días
  contesta, esa respuesta es del token que le escribió: la ve con `ListSmsReplies`
  y nadie más por la API. Sólo cuenta una orden que tu teléfono envió de verdad
  (`sent` o `delivered`); una que falló o venció no.
- **Tu agente también la ve,** marcada «respuesta a la API: <token>». Por omisión
  no contesta. Si quieres que conteste ese token con sus reglas generales, activa
  «El agente local contesta las respuestas» en el detalle del token. Si revocas el
  token o vence, sus conversaciones dejan de contar: las respuestas que lleguen
  después le llegan a tu agente sin marca, como cualquier SMS.
- **Bajas.** Un SMS que dice sólo STOP, BAJA, ALTO o CANCELAR (sin importar
  mayúsculas ni acentos) da de baja ese número para la API, y START o ALTA lo da
  de alta. La pasarela le confirma una sola vez, en el idioma de la palabra, si la
  API le había escrito en los últimos 7 días. Desde entonces `SendSms` a ese número
  responde `opted_out`. La baja sólo detiene a la API: tú y tu agente pueden seguir
  escribiéndole.
- **La lista** está en «Mensajes → Bajas de la API». Ahí ves quién la pidió y
  cuándo, das de baja un número a mano o lo quitas de la lista. Se guarda en
  `state/sms/optout.json`.

No hay webhooks: el agente pregunta por las respuestas con `ListSmsReplies`.

## Errores

Toda respuesta es JSON con `result` y un `request_id`, que también va en el
encabezado `X-Request-Id`. Si un agente te reporta un problema, pídele el
`request_id`.

| Código | HTTP | Qué significa |
|---|---|---|
| `invalid_token` | 401 | Sin token, uno que no existe, o un token en la URL |
| `token_revoked` | 401 | Revocaste el token |
| `token_expired` | 401 | El token venció |
| `too_many_attempts` | 429 | Demasiados fallos de autenticación desde esa dirección |
| `rate_limited` | 429 | Más de 60 llamadas por minuto |
| `quota_exceeded` | 429 | Pasó el tope de SMS del token |
| `invalid_content_type` | 415 | El cuerpo no es JSON ni formulario |
| `invalid_body` | 400 | El cuerpo no se puede leer |
| `method_not_allowed` | 405 | `/api/agent` sólo acepta POST |
| `invalid_action` | 400 | La acción no existe |
| `forbidden` | 403 | Al token le falta el permiso de esa acción |
| `missing_parameter`, `invalid_parameter` | 400 | Falta un parámetro o no tiene la forma correcta |
| `invalid_number` | 400 | `to` no es un número de teléfono |
| `empty_text`, `text_too_long` | 400 | El texto está vacío o pasa de 1,000 caracteres |
| `not_found` | 404 | No existe esa cuenta, correo, conversación, contacto u orden del token |
| `conflict` | 409 | El roster o las reglas cambiaron desde que el agente los leyó |
| `invalid`, `missing_field` | 400 | Un campo del roster o de las reglas no es válido o falta |
| `owner_row` | 403 | Tu fila del roster no se puede borrar |
| `agent_account` | 403 | La cuenta del agente no se puede quitar |
| `invalid_account`, `probe_failed` | 400 | Los datos de la cuenta no sirven, o el servidor de correo la rechazó |
| `idempotency_conflict` | 409 | Esa `idempotency_key` ya se usó con otro número o texto |
| `opted_out` | 403 | El número pidió la baja |
| `human_replied` | 409 | Le acabas de escribir a ese número; trae hasta cuándo |
| `no_phone` | 409 | No hay teléfono emparejado |
| `app_outdated` | 409 | El teléfono tiene una PaynaniApp anterior a la 0.9.0 |
| `busy` | 503 | El roster se está escribiendo; hay que reintentar en unos segundos |
| `whatsapp_unavailable` | 503 | WhatsApp no está activado en la instalación, o el servicio `paynani-whatsapp` no contesta |
| `internal_error` | 500 | Algo falló en paynani. El detalle queda en el log de `paynani-web`, nunca en la respuesta |

## Seguridad

- **El token nunca se guarda en claro** ni se escribe en logs, y la API no lo
  acepta en la URL.
- **`state/api_security.jsonl`** guarda 90 días de llamadas aceptadas (para
  `GetUsage`), fallos de autenticación, tokens revocados o vencidos que se usaron, topes, bajas, permisos negados y errores
  internos, con `request_id`, prefijo del token y dirección. Nunca guarda el token
  ni el texto de un SMS.
- **Te llega un correo** con 10 fallos de autenticación seguidos desde una
  dirección, o cuando un token llega a su tope diario.
- **Todo texto que llega por la API** se valida y se escapa como en la web.
