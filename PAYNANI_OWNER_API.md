# La API del dueño

`POST /api/owner` es la API que usan las apps del dueño, como PaynaniWebMT, para
administrar paynani a distancia: todo lo que hace PaynaniWeb. No es la API de los
agentes: ésa es `/api/agent` ([PAYNANI_API.md](PAYNANI_API.md)), con API Tokens `pn_…`
y permisos. Aquí entra sólo una app emparejada, con un token `pw_…`, y puede todo.

PRD: [iaaorgmx/PaynaniWebMT#2](https://github.com/iaaorgmx/PaynaniWebMT/issues/2).
Emparejamiento: #719. Marco: #720. Acciones de Iris: #721. Acciones de Andy: #722.

## Emparejar

1. El dueño pide un código a su agente (`scripts/paynani web pair`) o lo genera en
   PaynaniWeb, «Apps conectadas». Recibe la dirección del gateway
   (`PAYNANI_SMS_PUBLIC_URL`) y un código de 8 caracteres, que sirve una vez y vence
   en 10 minutos.
2. La app lo canjea:

```bash
curl -sS https://<gateway>/api/owner/pair \
  -H 'Content-Type: application/json' \
  -d '{"code": "K7MP2QXR", "name": "PaynaniWebMT de Julian", "app": {"name": "PaynaniWebMT", "version": "0.1.0"}}'
```

```json
{"result": "success", "client_id": "w_1a2b3c4d", "token": "pw_…", "request_id": "…"}
```

El token sólo se ve en esta respuesta: paynani guarda su SHA-256. Un código vencido,
usado o equivocado da `410 code_expired`. Diez equivocados en 10 minutos dan
`429 too_many_attempts` hasta que el dueño genere otro código. El dueño recibe un
correo por cada app emparejada, desconectada o revocada.

## Llamar

```bash
curl -sS https://<gateway>/api/owner \
  -H 'Authorization: Bearer pw_…' \
  -H 'Content-Type: application/json' \
  -d '{"action": "GetInstance"}'
```

- El token va **sólo** en el encabezado `Authorization`. En la URL da `401`; en el
  cuerpo, `400`.
- El cuerpo es JSON, o `multipart/form-data` cuando la acción sube archivos.
- Cada respuesta trae `request_id`, también en el encabezado `X-Request-Id`.
- Éxito: `200` con `{"result": "success", …, "request_id"}`. Error:
  `{"result": "error", "code", "message", "request_id"}`, con los códigos de la tabla.
- Un token `pn_` de agente no sirve aquí, y un `pw_` no sirve en `/api/agent`.

### Topes

- 120 llamadas por minuto por app (el doble que un token de agente, por el polling).
  Pasado el tope, `429 rate_limited` con `retry_after` en segundos.
- 10 fallos de autenticación desde una dirección la bloquean 15 minutos
  (`429 too_many_attempts`), igual que en `/api/agent`. Detrás del túnel la dirección
  es la de `X-Forwarded-For`.
- Cuerpo JSON: hasta 208 KB. Subidas: 20 MB por archivo y 25 MB por mensaje
  (`413 body_too_large`).

### Errores

| `code` | HTTP | Cuándo |
|---|---|---|
| `invalid_token` | 401 | Sin token, token en la URL, malformado o desconocido |
| `token_revoked` | 401 | La app se desconectó o el dueño la revocó |
| `too_many_attempts` | 429 | Demasiados fallos desde esa dirección; `retry_after` |
| `rate_limited` | 429 | Más de 120 llamadas en un minuto; `retry_after` |
| `invalid_content_type` | 415 | Ni JSON ni `multipart/form-data` |
| `invalid_body` | 400 | JSON roto, no es un objeto, o trae `api_token` |
| `body_too_large` | 413 | Pasa los topes de arriba |
| `invalid_action` | 400 | `action` no existe |
| `invalid_parameter`, `missing_parameter` | 400 | Un parámetro con mal tipo o que falta; `field` dice cuál |
| `internal_error` | 500 | Falló algo en paynani; el `request_id` está en su bitácora |

Las acciones de canales agregan los suyos, en su sección.

### Lo que queda registrado

`state/api_security.jsonl` (modo 600) guarda cada llamada con su `request_id`, el
prefijo del token (`pw_` y 8 caracteres) y la dirección: `call`, `owner_sensitive`
para las acciones delicadas, y los fallos. Nunca el token ni el texto de un mensaje.

### Acciones delicadas

Agregar, quitar o configurar cuentas, crear o revocar API Tokens, vincular o
desvincular WhatsApp, el token de Telegram y el correo fuera del roster. En PaynaniWeb
piden la contraseña; aquí paynani no la pide, porque la pide la app con la suya. Quedan
como `owner_sensitive` en la bitácora, y los correos que le llegan al dueño por ellas
dicen «desde PaynaniWebMT (<nombre de la app>)».

## Instancia

### `GetInstance`

Sin parámetros. Lo que la app necesita para dibujar el marco:

```json
{
  "paynani": {"version": "0.23.0", "commit": "abc1234"},
  "agent": {"name": "Metis", "email": "agente@example.com", "runtime": "claude-code",
            "runtime_label": "Claude Code", "status": "ok"},
  "owner": {"name": "Julian", "email": "dueño@example.com"},
  "channels": {"mail": true, "sms": true, "whatsapp": true, "telegram": false, "webchat": true},
  "languages": ["en-US", "es-ES", "es-MX", "fr-FR", "pt-BR"],
  "client": {"client_id": "w_1a2b3c4d", "name": "…", "app_name": "PaynaniWebMT", "app_version": "0.1.0",
             "paired_at": "…", "last_used_at": "…", "revoked_at": null},
  "now": "2026-11-05T08:00:00+00:00"
}
```

Un canal en `false` no está instalado o no está configurado: la app lo muestra como
PaynaniWeb, sin suponer que todos los canales permiten lo mismo.

### `GetChanges`

Qué cambió desde la última vez, para que la app sólo vuelva a pedir eso.

| Parámetro | |
|---|---|
| `cursor` | El que devolvió la llamada anterior. Vacío la primera vez |

```json
{"cursor": "c1.eyJ…", "changed": ["dashboard", "mail:agente@example.com", "sms"], "reset": false}
```

- Las áreas son `mail:<cuenta>`, `mail:*` (todas las cuentas: rotó la bitácora de
  eventos o salió un correo), `sms`, `whatsapp`, `telegram`, `webchat`, `roster`,
  `agent` y `dashboard`. Si cambió cualquier otra, también cambia `dashboard`.
- Sin cambios, `changed` viene vacío; es una llamada barata, de pocos milisegundos.
- Sin cursor, o con uno que no se entiende, vienen todas las áreas y `reset: true`.
- Guarda siempre el cursor nuevo. Un cambio sale una sola vez, y nada se pierde
  entre dos llamadas: lo que pase mientras responde sale en la siguiente.
- El cursor es opaco: no lo armes ni lo leas.

La app pregunta cada 3 segundos con Webchat o una conversación abierta, y cada 30 en
lo demás.

### `Disconnect`

Sin parámetros. La app se revoca a sí misma («Desconectar» en PaynaniWebMT). Responde
`{"client_id", "revoked_at"}`, y le llega un correo al dueño. Después, el token da
`401 token_revoked`.

## Archivos

- **Subir:** la acción que acepta archivos se llama con `multipart/form-data`: los
  parámetros como campos y los archivos como partes con `filename`.
- **Bajar:** las acciones de archivos (`GetWebchatFile`, `GetWhatsAppMedia`,
  `GetTelegramMedia`) responden los bytes, no JSON: `application/octet-stream`,
  `Content-Disposition: attachment` con el nombre limpio, `Cache-Control: no-store`,
  `Content-Security-Policy: sandbox` y `X-Request-Id`. Los errores siguen en JSON.

## Para quien agrega acciones (A3, A4)

Las acciones viven en módulos que se registran en `scripts/paynani_lib/web/owner_api.py`
(ver su docstring). Llaman a la misma función que la página de PaynaniWeb; si esa
lógica está mezclada con el HTML, primero se separa en un servicio. Cada acción nueva
agrega su sección aquí, con parámetros, respuesta, errores y un `curl`, y su prueba
`scripts/test_owner_api_*.py`.
