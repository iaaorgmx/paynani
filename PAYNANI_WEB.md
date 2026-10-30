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
| **Mensajes** | Las conversaciones SMS de la pasarela, de 50 en 50: lo que llegó, lo que mandó el agente con su estado, lo que contestó el dueño desde PaynaniApp o desde la web, y las llamadas perdidas y contestadas. «Nuevo SMS» y el cuadro de responder envían por el teléfono emparejado (ver abajo). |
| **Mensajes de WhatsApp** | Sólo con WhatsApp activado (`whatsapp.env` con `WHATSAPP_ENABLED=1`). Las conversaciones de WhatsApp, como «Mensajes» las de SMS, sin mensaje nuevo: sólo se contesta donde el contacto ya escribió. «Cuenta de WhatsApp» (`/whatsapp`) vincula, cancela y desvincula (ver abajo). |
| **Roster** | Lo mismo que la pantalla «Roster» de PaynaniApp, con el mismo servicio: contactos por cuenta, alta, edición, baja, instrucciones por contacto y reglas generales con vista previa. |
| **Perfil** | El nombre, el correo y la contraseña del dueño. |

Cuentas de correo no cierra ni responde avisos: eso sigue siendo trabajo del agente.
Desde «Nuevo correo» el dueño sí manda sus propios correos (#590, ver abajo).
Mensajes además envía SMS del dueño (PRD #489).

El menú lateral, la barra de arriba y el título se quedan fijos al hacer scroll,
como en el /dash de ServiceButton (PRD #537). El botón junto al logotipo colapsa el
menú y ☰, en la barra, lo vuelve a abrir; el navegador lo recuerda en la cookie
`paynani_web_nav`. En el celular el menú empieza escondido y ☰ lo abre encima de la
página; se cierra tocando fuera, con Esc o al elegir una entrada.

### Enviar SMS desde «Mensajes»

El dueño escribe como si lo hiciera desde PaynaniApp, y el SMS sale por el teléfono
emparejado (PRD #489).

- **Dónde:** «Nuevo SMS» (`/messages/nuevo`), con el número escrito o elegido del
  roster, y el cuadro de responder al pie de cada conversación.
- **El número** se normaliza con la región de la SIM del teléfono emparejado. Un
  número que no se puede leer no sale (`invalid_number`).
- **Fuera del roster** pide la contraseña de la web, con el mismo bloqueo de
  intentos que la entrada. A un número del roster se envía sin contraseña.
- **El texto** admite hasta 1,000 caracteres. `assets/sms.js` cuenta caracteres y
  partes (GSM-7 o UCS-2); sin script, el límite lo pone el navegador y el servidor.
- **«Pausar al agente por X minutos»** viene sin marcar. Marcada, cuando el SMS
  sale el agente no le escribe a ese número durante X minutos, igual que después
  de una respuesta desde PaynaniApp. X es `PAYNANI_WEB_AGENT_PAUSE_MIN` en
  `sms.env` (1 a 1,440; 30 si no está).
- **Tope:** 30 envíos por hora desde la web, o `PAYNANI_WEB_SMS_PER_HOUR` en
  `sms.env`. Al llegar al tope la web dice a qué hora se libera. El conteo y la
  escritura de la orden van bajo un candado (`state/sms/queue.lock`), así que dos
  envíos simultáneos no lo rebasan.
- **Estados:** cada SMS de la web dice «desde PaynaniWeb» y En cola, Aceptado,
  Enviado, Entregado, Falló (con el código), Rechazado (con la razón) o Vencido.
  `sms.js` pregunta a `/messages/estados?n=<número>` cada 5 segundos y recarga si
  llegó algo nuevo, salvo que haya texto a medio escribir.
- **Teléfono desconectado:** la orden se acepta y queda en cola; la conversación lo
  dice. Si a los 15 minutos no salió, se ve Vencida.
- **Sin teléfono emparejado** («No hay teléfono emparejado»), **o con una PaynaniApp
  anterior a la 0.9.0** («Actualiza PaynaniApp para enviar desde aquí»), los botones
  se ven deshabilitados y la web no envía.

Por dentro es una orden `w_` con `origin: owner` en `state/sms/outbox/`, con la
dirección de la web en `orders.jsonl`; la pasarela la manda sólo a una app que
anunció `accepts_owner_out` (SMS_GATEWAY.md §2 y §4). El agente se entera por una
línea `sms-human` con «Tú (PaynaniWeb)».

### El Catch-All de cada canal

Cada canal tiene su página «Catch-All», que decide qué pasa con los mensajes de
números que no están en el roster (PRD #535, PRD #576). La de SMS está en
«Mensajes», junto a «Bajas de la API» (`/messages/catch-all`). La de WhatsApp está en
«Mensajes de WhatsApp», junto a «Cuenta de WhatsApp» (`/whatsapp/catch-all`), y sólo
existe con WhatsApp activado (#588). Cada una se activa y se guarda por separado:
cambiar una no toca la otra, y cada página dice dónde está la otra. Apagado, como
hasta ahora, al agente le llega sólo «mensaje de un número fuera del roster», sin el
texto. Activo, le llegan los mensajes de ese canal con su texto y el agente sigue
sólo las instrucciones de ese canal. Nunca le contesta al número. Telegram no tiene
página mientras paynani no tenga ese canal.

- **La casilla y las instrucciones** de cada página se guardan en
  `rules/catch-all-sms.md` o `rules/catch-all-whatsapp.md` con `catchall.save` y su
  `channel`, el mismo mensaje que usan PaynaniApp y la API (`SaveCatchAll`). El
  canal sale de la página: si un formulario viejo manda otro `channel`, no se guarda
  nada y la página lo dice.
- **Mientras un canal no tenga su archivo**, su página muestra lo que hay en
  `rules/catch-all.md`, el archivo único de antes, y lo dice. El primer guardado le
  da a cada canal su archivo, con lo que tenía el viejo, y quita el viejo.
- **La contraseña** de la web se pide para activar un canal y para cambiar sus
  instrucciones mientras está activo, con el mismo bloqueo de intentos que la
  entrada. Apagarlo no la pide.
- **Activo sin instrucciones** (vacío, o sólo espacios) no se guarda, ni más de
  32 KB. Si alguien más cambió ese canal mientras lo editabas, la página lo dice y
  muestra la versión actual.
- **Los códigos de verificación** (WhatsApp, Telegram, bancos) también le llegan al
  agente cuando está activo. La pantalla lo advierte, y las instrucciones pueden
  decirle que los ignore.
- Cada cambio te llega por correo, con el canal, desde dónde se hizo y sin las
  instrucciones.

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
  completo. La hora va en la zona del navegador (`assets/time.js`), o en la del
  host si el script no corre; si es de hoy, con «hace …», y con la fecha completa
  al pasar el cursor. Cada recibido lleva su estado y la marca del roster junto a la hora.
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
- **En el navegador** quedan dos cookies que no son de la sesión: el idioma
  (`paynani_web_lang`) y si el menú va colapsado (`paynani_web_nav`). Ninguna
  lleva datos del dueño.
- **No guarda** el cuerpo de ningún correo ni el texto de ningún SMS: los lee al
  abrirlos.
- **El log** (`state/web.log`) lleva una línea por petición, con el método y la ruta,
  nunca la consulta ni el cuerpo. `state/web.err.log` lleva los errores, con su
  tipo y sin su texto.

### WhatsApp

Con WhatsApp activado en la instalación (PRD #550), el menú agrega «Mensajes de
WhatsApp» (`/whatsapp/messages`). Sin activar, no aparece nada de WhatsApp. La web le
habla al servicio `paynani-whatsapp` por `state/whatsapp/control.sock`
(`WHATSAPP_BRIDGE.md` §11), con las mismas peticiones que PaynaniApp.

- **La cuenta** (`/whatsapp`): el estado, el número vinculado y, sin vincular, la
  advertencia del bloqueo de WhatsApp y dos formas de vincular: con QR, que se
  escanea desde WhatsApp → Dispositivos vinculados, o con código, para escribirlo en
  el teléfono. Vincular, cancelar y desvincular piden la contraseña de la web, con el
  mismo bloqueo de intentos que la entrada.
- **El QR** se dibuja en la página y `whatsapp.js` lo cambia por el vigente cada 3 s
  (`/whatsapp/link/current`), porque WhatsApp lo rota cada ~20 s. Sólo lo ve la sesión
  del navegador que empezó a vincular. Si cierras la página, a los 60 s el servicio
  cancela la vinculación. **El código** se muestra una sola vez, en la respuesta que
  lo pidió; recargar ya no lo enseña. Ninguno de los dos se guarda.
- **Las conversaciones**: lo que llegó, lo que mandó el agente con su estado y lo que
  contestaste tú. Un archivo se muestra por su tipo («[foto]»), sin descargarlo. De un
  número fuera del roster sólo se ven el número y la hora, nunca el texto.
- **Responder** sólo aparece en la conversación de un contacto del roster que ya
  escribió por WhatsApp, con WhatsApp conectado. No hay «Nuevo mensaje»: paynani nunca
  escribe primero, ni el agente ni tú desde aquí.

## Seguridad

- Ninguna página carga nada de fuera: ni fuentes, ni scripts, ni imágenes. La
  `Content-Security-Policy` es `default-src 'none'; style-src 'self';
  script-src 'self'; img-src 'self'; form-action 'self'; base-uri 'none';
  connect-src 'self'`, con
  `X-Frame-Options: DENY` y `nosniff`. La única imagen que se carga es el favicon
  (`brand/favicon.svg`), del mismo servidor; la marca va en línea en el HTML.
  `connect-src 'self'` deja que los scripts de la página le pregunten a este mismo
  servidor (el QR de WhatsApp y los estados de los SMS), y a nada más.
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
