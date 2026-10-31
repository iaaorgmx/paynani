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
| **Inicio** | El Dashboard: si todo funciona, qué pasó hoy, qué necesita atención y lo último que ocurrió (PRD #602, ver abajo). |
| **Cuentas de correo** | Una entrada por cuenta: la del agente y las de `accounts.json`. Lista sus últimos correos, de 50 en 50, con el estado del aviso y la marca del roster. Abrir uno lo pide a IMAP en ese momento, como texto, y no lo guarda. |
| **Agregar y quitar cuentas** | «+ Agregar cuenta» prueba el acceso IMAP y SMTP antes de guardar y escribe como `paynani account add`. «Quitar esta cuenta» deja de vigilarla como `paynani account remove`, sin borrar su buzón ni su roster. Las dos piden la contraseña de la web. |
| **Mensajes** | Las conversaciones SMS de la pasarela, de 50 en 50: lo que llegó, lo que mandó el agente con su estado, lo que contestó el dueño desde PaynaniApp o desde la web, y las llamadas perdidas y contestadas. «Nuevo SMS» y el cuadro de responder envían por el teléfono emparejado (ver abajo). |
| **Mensajes de WhatsApp** | Sólo con WhatsApp activado (`whatsapp.env` con `WHATSAPP_ENABLED=1`). Las conversaciones de WhatsApp, como «Mensajes» las de SMS, sin mensaje nuevo: sólo se contesta donde el contacto ya escribió. «Cuenta de WhatsApp» (`/whatsapp`) vincula, cancela y desvincula (ver abajo). |
| **Mensajes de Telegram** | Sólo con Telegram activado (`telegram.env` con `TELEGRAM_ENABLED=1` y el token). Las conversaciones con el bot de Telegram, sin mensaje nuevo: sólo se contesta donde la persona ya escribió. «Bot de Telegram» (`/telegram`) muestra el estado y cambia el token (ver abajo). |
| **Roster** | Lo mismo que la pantalla «Roster» de PaynaniApp, con el mismo servicio: contactos por cuenta, alta, edición, baja, instrucciones por contacto y reglas generales con vista previa. |
| **Perfil** | El nombre, el correo y la contraseña del dueño. Se abre con el ícono que está junto a tu nombre en el menú lateral, como en el /dash de ServiceButton (#626). El menú del avatar, arriba a la derecha, queda con tu nombre, tu correo y «Cerrar sesión». |

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

### Nuevo correo

El dueño manda sus propios correos desde cualquier cuenta (#590 cambio 2). El envío
es del núcleo, `paynani_lib/owner_mail.py` (#591 N1); `send.sh` no cambia y el agente
sigue limitado al roster.

- **Dónde:** «Nuevo correo» en la lista de cada cuenta (`/email/<cuenta>/nuevo`).
  Sale de esa cuenta, con su nombre y su firma si tiene.
- **Para, CC y CCO** aceptan varias direcciones separadas por comas, hasta 50 en
  total. La libreta es el roster de esa cuenta: elegir un contacto lo agrega al
  campo donde estaba el cursor (`assets/compose.js`). Sin script, las direcciones se
  escriben a mano. Vale cualquier dirección válida, esté o no en el roster; una
  dirección inválida se rechaza (`invalid_address`) y no sale nada.
- **Fuera del roster** pide la contraseña de la web, con el mismo bloqueo de
  intentos que la entrada. Si todos están en el roster se envía sin contraseña.
- **El permiso** es de un solo uso y dura 60 segundos: queda ligado a la cuenta, a
  esos destinatarios y a si se escribió la contraseña. Si el roster cambia antes de
  mandar y alguien queda fuera sin contraseña, no sale (`not_authorized`).
- **Al terminar** la página vuelve a la lista y dice cuántos estaban fuera del
  roster, si no se guardó la copia en Enviados y si no salió el aviso. Las
  direcciones no van en la URL.
- **El aviso:** si alguien fuera del roster recibió el correo, al dueño le llega un
  aviso por correo, con `send.sh` y a su propia dirección.
- **Resultado desconocido:** si el envío se corta a medias, la página no invita a
  reenviar; dice que se revise Enviados antes, para no mandarlo dos veces.

Cada envío deja una línea en `state/owner_sends.jsonl` y otra en `state/sent.log`,
sin el cuerpo. La copia queda en Enviados, como con `send.sh`.

### Configuración de la cuenta principal

Cambia el buzón del agente: correo, nombre visible, servidores y puertos IMAP y
SMTP, y la contraseña del buzón (#590 cambio 3). Sólo existe para la cuenta del
agente; las cuentas de `accounts.json` se quitan y se vuelven a agregar.

- **Dónde:** «Configuración» en la lista de la cuenta del agente
  (`/email/main/configuracion`).
- **La contraseña del buzón** nunca se muestra: el campo viene vacío y vacío
  quiere decir que no cambia.
- **Guardar** pide siempre la contraseña de la web, con el mismo bloqueo de
  intentos que la entrada.
- **Por dentro** es `paynani_lib/main_account.update` (#591 N2): prueba IMAP y SMTP
  con los datos nuevos sin mandar nada, escribe juntos el `.env` y la cuenta
  `paynani` de Himalaya, reinicia el listener y espera a que vuelva. Si algo falla,
  intenta restaurar los tres archivos (`.env`, Himalaya y el estado del listener)
  y la página dice si la restauración funcionó; si no (`rollback: failed`), lo
  dice y pide revisar `paynani doctor`.
  La prueba se ve paso por paso, con el error de cada uno.
- **Sólo el nombre visible** no prueba ni reinicia nada: se guarda y la página lo
  dice. Es la forma segura de probar la pantalla.
- **Formulario viejo:** si los datos cambiaron desde que se abrió la página, no se
  guarda nada (409) y se muestran los actuales.
- **Otro cambio en curso:** dos cambios no corren a la vez; el segundo no se guarda
  y la página dice que lo intentes cuando termine el primero.
- Cada cambio te llega por correo, con los campos que cambiaron, sin sus valores
  ni la contraseña.

### El Dashboard de la página inicial

`/` muestra el estado de paynani de un vistazo (PRD #602). Sólo lee lo que ya existe;
no marca avisos, no abre IMAP y no escribe en `state/`. La lectura está en
`web/dashboard.py` y la página en `web/dashboard_pages.py`.

- **Estado general:** verde si todas las revisiones están en `ok`, amarillo si alguna
  está en `warning` o `unknown`, rojo si alguna está en `blocked`. Debajo dice cuántas
  están en orden y enlaza a las que no.
- **De dónde salen las revisiones:**
  - Las locales (listener, despachador, cola, credenciales, roster, `smtp`, cuentas
    adicionales, sesión del agente y teléfono de la pasarela) las calcula la web con
    `healthcheck`, con caché de 60 s.
  - La única que toca la red, `himalaya` (corre `himalaya account check`), nunca se
    corre desde la web: se lee del último `paynani doctor` guardado en
    `state/doctor.json` (#603), con su hora.
  - Sin ese archivo, o con uno de más de 24 h, cuenta como `unknown` y dice su
    antigüedad: un `doctor` viejo no pinta el estado de verde.
- **Hoy y los últimos 7 días** se cuentan en la zona horaria del host, y la página la
  muestra.
- **Los cuatro indicadores:**
  - **Correo hoy**, con atendidos, respondidos y abiertos.
  - **Avisos abiertos**: correo del roster de los últimos 7 días que sigue sin
    cerrarse, con el más viejo.
  - **SMS hoy**: recibidos, enviados y fallidos.
  - **Roster**: contactos y la hora del último cambio.
- **Selector de cuenta:** con más de una cuenta, filtra el correo, los avisos y la
  gráfica (`/?cuenta=<id>`). Una cuenta que no existe muestra todas y lo dice.
- **Servicios:** el listener, el despachador, la sesión del agente, la pasarela SMS
  (modelo, PaynaniApp, batería y última conexión), WhatsApp (sólo si está activado) y
  cada cuenta adicional. Nada que paynani no administre, como el túnel.
- **Necesita tu atención,** en este orden y cada uno con su enlace:
  1. revisiones que no están en `ok`;
  2. cuentas desconectadas;
  3. avisos abiertos;
  4. SMS fallidos o vencidos de hoy;
  5. tokens de API que vencen en 7 días o menos, o que ya vencieron y no están
     revocados;
  6. una versión nueva de paynani (de `state/version.check`).

  Sin nada, «Nada pendiente».
- **Correo, últimos 7 días:** barras por día, cerradas y abiertas, en SVG con
  atributos (la CSP no cambia) y una tabla para lectores de pantalla.
- **Actividad reciente:** los últimos 10 de correo recibido y enviado, SMS, llamadas,
  WhatsApp y cambios al roster. Cada uno lleva quién, el asunto en un correo (nunca el
  texto de un SMS o un WhatsApp), su estado y la hora, y enlaza a su pantalla.
- **Actualización:** `assets/dashboard.js` pide `/dashboard.json` cada 60 s, sólo con
  la pestaña visible, y cambia los números y el estado general sin recargar. Si
  cambió un servicio o lo pendiente, dice «Hay cambios · Actualizar». `/dashboard.json`
  y el script piden sesión. El JSON responde con `no-store` y sólo trae números y
  estados: ni direcciones, ni teléfonos, ni asuntos, ni nombres. El modelo se guarda
  30 s en memoria, así que el ledger no se relee en cada petición. Sin script, la
  página se ve completa al cargarla.

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

### Telegram

Con Telegram activado en la instalación (PRD #609), el menú agrega «Mensajes de
Telegram» (`/telegram/messages`). Sin activar, no aparece nada de Telegram. La web le
habla al servicio `paynani-telegram` por `state/telegram/control.sock` (`TELEGRAM.md`
§4 y §7).

- **El bot** (`/telegram`): el estado del servicio, el `@usuario` del bot, desde
  cuándo funciona, la última consulta a Telegram y cuántos mensajes llegaron y
  salieron hoy. Si otro programa lee el mismo bot o tiene un webhook, o si Telegram
  rechazó el token, la página lo dice.
- **Cambiar el token** (FR-10) va en dos pasos:
  1. Pegas el token de @BotFather en un campo de contraseña, sin autocompletar, y
     escribes la contraseña de la web (con el mismo bloqueo de intentos que la
     entrada). La web lo revisa con el servicio (`telegram.token_check`) y te dice de
     qué bot es.
  2. Confirmas que el token es sólo de esta instalación y, si el bot tenía un
     webhook, que se borre. El servicio lo aplica (`telegram.token_apply`) y, si el
     bot nuevo no funciona, vuelve al anterior y la página lo dice.

  El token nunca vuelve a la página, ni completo ni en parte. La revisión del paso 1
  sólo vive 5 minutos en la memoria del servidor y es de esa sesión del navegador. Al
  terminar, te llega un correo con el bot nuevo, sin el token.
- **Las conversaciones:** lo que llegó, lo que mandó el agente y lo que contestaste
  tú. Un mensaje editado lo dice, y una foto se ve en el globo (`/telegram/media`,
  que se la pide al servicio cada vez). Un hilo se nombra por un id opaco (`t_…`),
  nunca por un id de Telegram. De alguien fuera del roster se ven el nombre que dio,
  marcado «no verificado», y la hora; el texto sólo con el Catch-All de Telegram
  activo.
- **Responder** sólo aparece en la conversación de un contacto del roster que ya le
  escribió al bot, con el servicio funcionando. No hay «Nuevo mensaje»: Telegram no
  deja que un bot escriba primero.
- **Agregar al roster** (FR-15) aparece en la conversación de alguien fuera del
  roster. Pide la contraseña de la web y responde con el formulario de la fila nueva,
  con su nombre y su id de Telegram ya puestos. Es el único lugar donde se ve un id de
  Telegram: no va en la URL, no se guarda en otro lugar y no se escribe en el log. El
  formulario del roster tiene el campo Telegram mientras Telegram esté activado.
- **El Catch-All de Telegram** es su propia página (`/telegram/catch-all`), junto a
  «Bot de Telegram», como los de SMS y WhatsApp (#588). Se guarda en
  `rules/catch-all-telegram.md`.
- **El Dashboard** agrega el bot de Telegram a Servicios, con su estado.

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
