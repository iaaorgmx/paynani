# PaynaniWeb

PaynaniWeb es la aplicación web para administrar una instalación de paynani desde
el navegador, sin abrir una terminal y sin depender del teléfono emparejado. El
dueño ve los correos de cada cuenta y los SMS de la pasarela con lo que se
respondió, agrega y quita cuentas de correo, y edita el roster con sus reglas.

Es la parte de documentación del PRD [#434](https://github.com/iaaorgmx/paynani/issues/434)
(paraguas [#435](https://github.com/iaaorgmx/paynani/issues/435)). Describe solo lo
que ya está en `main`.

## Dónde corre

- **Un proceso aparte,** `scripts/paynani_web.py`, que escucha solo en
  `127.0.0.1:8771` (`PAYNANI_WEB_PORT` en `sms.env`). Usa solo la biblioteca
  estándar de Python 3.10 o mayor.
- **Detrás de la pasarela SMS.** La pasarela le reenvía toda petición cuya ruta no
  empiece con `/sms/`, así que PaynaniWeb se abre en la misma dirección del túnel
  de ngrok, sin configurar nada en ngrok. El WebSocket del teléfono (`/sms/ws`)
  nunca pasa por la web. Si la web no contesta, la pasarela responde `503` con una
  página corta, y los SMS siguen llegando.
- **Se instala con la pasarela.** `scripts/install.sh --with-sms` instala y
  enciende `paynani-web.service` junto a `paynani-sms.service`; en macOS,
  `com.paynani.web` junto a `com.paynani.sms`. Un `--upgrade` de un host que ya
  tiene la pasarela la agrega. Un host sin pasarela no la tiene, porque nadie
  podría llegar a ella. `INSTALL.md` §5.1 tiene la instalación a mano.

## El primer uso

Recién instalada, toda página dice cómo crear el usuario, y nada más. El usuario
se crea en la computadora del agente, nunca desde la web, para que nadie que
llegue por internet a una instalación nueva pueda quedarse con ella:

```bash
scripts/paynani web user add --email you@example.com --name "Your Name"
```

Pide la contraseña dos veces, de al menos 12 caracteres. Se guarda solo su hash
`scrypt`, en `web/user.json` (modo 600, en `.gitignore`).

| Comando | Qué hace |
|---|---|
| `scripts/paynani web user add --email … --name …` | Crea el único usuario, el dueño. |
| `scripts/paynani web user show` | El nombre y el correo, sin el hash. |
| `scripts/paynani web passwd` | Cambia la contraseña y cierra todas las sesiones. |

`--password-stdin` lee la contraseña de una línea, para automatizar.
`scripts/version.sh --plan` avisa cuando un host con pasarela llega a una versión
con PaynaniWeb y todavía no hay usuario.

## Entrar

- **Correo y contraseña** en la pantalla de entrar, sin registro ni Google.
- **Bloqueo:** 5 intentos fallidos en 15 minutos desde una dirección la bloquean 15
  minutos. La dirección es el último valor de `X-Forwarded-For`, el que pone el
  túnel. La contraseña actual de Profile pasa por el mismo bloqueo.
- **Sesión:** una cookie `HttpOnly`, `Secure` y `SameSite=Strict` que vence tras 8
  horas sin uso. Cambiar la contraseña cierra las otras sesiones. Reiniciar
  PaynaniWeb las cierra todas.
- **Aviso:** la primera entrada desde una dirección nueva le manda un correo al
  dueño, por `send.sh`.

## Las pantallas

| Pantalla | Qué hace |
|---|---|
| **Cuentas de correo** | Una entrada por cuenta: la del agente y las de `accounts.json`. Lista sus últimos correos, de 50 en 50, con el estado del aviso y la marca del roster. Abrir uno lo pide a IMAP en ese momento, como texto, y no lo guarda. |
| **Agregar y quitar cuentas** | «+ Agregar cuenta» prueba el acceso IMAP y SMTP antes de guardar y escribe como `paynani account add`. «Quitar esta cuenta» deja de vigilarla como `paynani account remove`, sin borrar su buzón ni su roster. Las dos piden la contraseña de la web. |
| **Mensajes** | Las conversaciones SMS de la pasarela, de 50 en 50: lo que llegó, lo que mandó el agente con su estado, lo que contestó el dueño desde PaynaniApp, y las llamadas perdidas y contestadas. |
| **Roster** | Lo mismo que la pantalla «Roster» de PaynaniApp, con el mismo servicio: contactos por cuenta, alta, edición, baja, instrucciones por contacto y reglas generales con vista previa. |
| **Perfil** | El nombre, el correo y la contraseña del dueño. |

Cuentas de correo y Mensajes solo muestran: cerrar o responder un aviso sigue
siendo trabajo del agente.

### Recibido y enviado, como un webmail

Cada cuenta tiene una sola lista, como un webmail: lo que recibió (del ledger) y lo
que envió (de `state/sent.log`, filtrado por `account=`), mezclados por hora, el más
reciente primero, de 50 en 50. Cada fila dice si entró (↙ «De:») o salió (↗ «Para:»),
con el asunto y la hora. Los recibidos llevan su estado y la marca del roster; los
enviados, «Enviado».

Al abrir cualquiera se ve su hilo como en Gmail (PRD #455). El hilo son los correos
de esa cuenta con el mismo asunto (sin `Re:`, `Fw:` ni mayúsculas) y la misma otra
persona (el remitente de un recibido, o un destinatario o Cc de un enviado).
`send.sh` no anota a qué correo responde (#442 se cerró: los destinatarios ven los
correos como siempre), así que el hilo se arma así.

- **Arriba,** el asunto una vez, sin «Re:».
- **Debajo,** todos los mensajes, del más viejo al más nuevo y con el mismo
  formato: avatar, nombre, dirección, «para …» (y Cc), la hora y el cuerpo
  completo. Cada recibido lleva su estado y la marca del roster junto a la hora.
- **El abierto** va con un borde suave, y la página baja hasta él (`#m-<id>`).
- **El texto citado** («On … wrote:», «El … escribió:», la cabecera de Outlook)
  queda plegado detrás de «•••». La firma y los reenvíos se quedan a la vista.
- **Con más de 10 mensajes,** los del medio se pliegan en «N mensajes más»; el
  abierto siempre se ve.
- **Todo se lee de IMAP en ese momento,** con una sola conexión de la cuenta y
  `BODY.PEEK[]`: los recibidos de su buzón y los enviados de Enviados, por su
  Message-ID. `send.sh` guarda esa copia desde #449, salvo en Gmail, que la guarda
  sola. Nada queda leído, nada se mueve y nada se guarda en paynani. Un mensaje
  que no se puede leer dice por qué (un enviado sin copia, por ejemplo), y el
  resto se ve igual.

## Lo que guarda y lo que no

- **Guarda** el usuario y las direcciones desde las que entró (`web/user.json` y
  `web/known_ips.json`, modo 600). Los cambios al roster y a las cuentas quedan
  donde los dejan `paynani roster` y `paynani account`: `state/history/` y
  `state/roster_changes.jsonl`.
- **No guarda** el cuerpo de ningún correo ni el texto de ningún SMS: los lee al
  abrirlos.
- **El log** (`state/web.log`) lleva una línea por petición, con el método y la ruta,
  nunca la consulta ni el cuerpo. `state/web.err.log` lleva los errores, con su
  tipo y sin su texto.

## Seguridad

- Ninguna página carga nada de fuera: ni fuentes, ni scripts, ni imágenes. La
  `Content-Security-Policy` es `default-src 'none'; style-src 'self';
  script-src 'self'; img-src 'self'; form-action 'self'; base-uri 'none'`, con
  `X-Frame-Options: DENY` y `nosniff`. La única imagen que se carga es el favicon
  (`brand/favicon.svg`), del mismo servidor; la marca va en línea en el HTML.
- Todo `POST` tiene que traer `Origin` (o `Referer`) de la misma dirección, y los
  formularios con sesión llevan su token.
- Nunca se muestra un secreto: ni la contraseña de la web, ni la de una cuenta de
  correo, ni el `.env`. El formulario de agregar cuenta no devuelve la contraseña
  del correo cuando hay un error.
- Todo lo que viene de un correo, un SMS, el roster o las reglas se escapa antes de
  ir a la página. El HTML de un correo se muestra como texto, sin enlaces activos.

## Problemas

| Lo que ves | Qué es |
|---|---|
| «PaynaniWeb no responde» (503) en la dirección del túnel | La pasarela está bien y la web no. `systemctl --user status paynani-web.service`, y `state/web.err.log`. |
| La web no arranca y el servicio no se reinicia | Salió con 2: `PAYNANI_WEB_PORT` es igual al puerto de la pasarela, o se le dio un `--host` fuera de loopback. |
| «Falta crear el usuario» en todas las páginas | `scripts/paynani web user add`, en la computadora del agente. |
| «Demasiados intentos desde esta dirección» | El bloqueo de 15 minutos. Esperar, o reiniciar PaynaniWeb, que lo borra. |
| Olvidaste la contraseña | `scripts/paynani web passwd` en la computadora del agente. |
