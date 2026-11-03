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
| **Mensajes de texto** | En inglés «Text Messages» (#633; antes «Mensajes»). Las conversaciones SMS de la pasarela, de 50 en 50: lo que llegó, lo que mandó el agente con su estado, lo que contestó el dueño desde PaynaniApp o desde la web, y las llamadas perdidas y contestadas. «Nuevo SMS» y el cuadro de responder envían por el teléfono emparejado (ver abajo). |
| **Mensajes de WhatsApp** | Sólo con WhatsApp activado (`whatsapp.env` con `WHATSAPP_ENABLED=1`). Las conversaciones de WhatsApp, como «Mensajes de texto» las de SMS, sin mensaje nuevo: sólo se contesta donde el contacto ya escribió. «Cuenta de WhatsApp» (`/whatsapp`) vincula, cancela y desvincula (ver abajo). |
| **Mensajes de Telegram** | Siempre (#635); sin bot configurado lleva a «Cuenta de Telegram». Las conversaciones con el bot de Telegram, sin mensaje nuevo: sólo se contesta donde la persona ya escribió. «Cuenta de Telegram» (`/telegram`) hace la configuración inicial, muestra el estado y cambia el token (ver abajo). |
| **Roster** | Lo mismo que la pantalla «Roster» de PaynaniApp, con el mismo servicio: contactos por cuenta, alta, edición, baja, instrucciones por contacto y reglas generales con vista previa. |
| **Perfil** | El nombre, el correo y la contraseña del dueño. Se abre con el ícono que está junto a tu nombre en el menú lateral, como en el /dash de ServiceButton (#626). Ya no hay avatar arriba a la derecha: «Cerrar sesión» está en el menú lateral. |
| **Acerca de** | Como el About de PaynaniApp (#636), debajo de «API Tokens». Muestra la versión con su commit, con un botón que la copia, y el aviso de código abierto bajo la licencia MIT. Debajo, tres grupos: **Proyecto** (sitio, código y licencia); **Ayuda** (reportar un problema, que abre un issue en paynani con la versión ya escrita, las novedades y esta guía); y **Créditos**. Los enlaces abren en otra pestaña. El estado de la instalación está en el Dashboard. |
| **Agente de IA** | En el menú lateral, debajo de tu nombre y arriba de «Management» (#644), va la sección «AI Agent». Tiene una entrada con el robot, el nombre del agente y, abajo, el harness (Claude Code, OpenClaw, Hermes, Codex u OpenCode) y su estado. Al picarla se abre la página del agente (`/agent`), que no tiene otra entrada en el menú (ver abajo). |
| **Webchat** | En la sección «AI Agent», debajo del agente (#648): platicas con tu agente desde el navegador, con archivos y fotos. Sólo con tu sesión de PaynaniWeb (ver abajo). |

Cuentas de correo no cierra ni responde avisos: eso sigue siendo trabajo del agente.
Desde «Nuevo correo» el dueño sí manda sus propios correos (#590, ver abajo).
Mensajes además envía SMS del dueño (PRD #489).

El menú lateral, la barra de arriba y el título se quedan fijos al hacer scroll,
como en el /dash de ServiceButton (PRD #537). El botón junto al logotipo colapsa el
menú y ☰, en la barra, lo vuelve a abrir; el navegador lo recuerda en la cookie
`paynani_web_nav`. En el celular el menú empieza escondido y ☰ lo abre encima de la
página; se cierra tocando fuera, con Esc o al elegir una entrada.

### Enviar SMS desde «Mensajes de texto»

El dueño escribe como si lo hiciera desde PaynaniApp, y el SMS sale por el teléfono
emparejado (PRD #489).

- **Dónde:** «Nuevo SMS» (`/messages/nuevo`), con el número escrito o elegido del
  roster, y el cuadro de responder al pie de cada conversación.
- **Con un teléfono «solo Webchat»** (la PaynaniApp de Google Play, #671), ni «Nuevo SMS»
  ni el cuadro de responder se ofrecen: un aviso dice que ese teléfono no manda SMS. En el
  Dashboard su fila dice «sólo Webchat, sin SMS» y, con la app cerrada, queda en gris.
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
«Mensajes de texto», junto a «Bajas de la API» (`/messages/catch-all`). La de WhatsApp está en
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

### El agente de IA

El bloque del menú y la página `/agent` (#644) leen lo mismo que el Dashboard, con su
caché de 60 s. Nada de aquí escribe en `state/` ni toca la red.

- **El estado** (Q293). Cada runtime tiene su propia evidencia (revisión de Ximena en #645):
  - verde «Online»: hay evidencia de que el agente recibe los mensajes;
  - ámbar «No session»: el servicio funciona, pero ninguna sesión del agente lee los mensajes,
    que esperan;
  - rojo «Offline»: no le llega nada, porque el despachador está detenido o el runtime los
    rechaza;
  - gris «No data»: todavía no hay evidencia, porque no se le ha entregado nada o el runtime
    no se conoce. No se afirma que esté en línea.

  La evidencia de cada runtime:
  - **Claude Code:** una sesión con la vigilancia viva (`watch_registry_facts`).
  - **Codex y OpenCode:** la sesión lee el spool. Un evento despachado a ese runtime que
    nadie toma en 10 min es «No session». Los que se quedaron con otro runtime no cuentan.
  - **OpenClaw y Hermes:** lo que el runtime contestó al entregarle el último evento
    (`state/delivery.json`). Sólo cuenta lo que dijo el runtime actual: al cambiar de
    runtime, lo que dijo el anterior no es evidencia. Un rechazo más nuevo que la última aceptación, o una cola atorada
    más de 10 min, es «Offline».
- **La sección «AI Agent»** va como «Management» (Q303). Su entrada tiene el robot a la
  izquierda, alineado arriba; a la derecha va el nombre del agente (`AGENT_EMAIL_FROM_NAME`,
  o su correo si no hay nombre), y abajo, el harness y el estado. Si no se puede leer el
  agente, la página sale sin la sección.
- **La página** muestra:
  - el agente y su estado: desde cuándo vigila y cuándo se renueva la vigilancia;
  - cuatro cifras de hoy, en la zona del host:
    - los atendidos, respondidos y cerrados sin respuesta, de correo, SMS, WhatsApp y
      Telegram (los eventos del ledger);
    - lo que espera en la cola;
    - la última respuesta: la última transición `replied` del ledger, en cualquier canal,
      aunque el evento se haya cerrado después, o el último SMS que mandó el agente. No sale de `sent.log`, que también tiene los
      avisos de PaynaniWeb al dueño (revisión de Metis en #645);
    - el tiempo típico de respuesta: la mediana, entre que llega un mensaje y que el
      agente lo responde, de lo respondido hoy;
  - «The agent»: el harness, la vigilancia, el despachador y la versión;
  - «Channels»: el correo, los mensajes de texto, WhatsApp y Telegram;
  - lo que el agente hizo hoy;
  - qué hacer si el estado cambia.

### Webchat

Tú le escribes al agente desde PaynaniWeb, y él te contesta ahí mismo (#648). La
conversación la guarda el núcleo en `state/webchat/` (`WEBCHAT.md`); la web la lee y
escribe con `paynani_lib/webchat/store.py`, sin un servicio aparte.

- **Sólo para ti** (Q307): pide la sesión de PaynaniWeb y no tiene API externa.
- **Cada mensaje tuyo** es un evento `webchat.received`. Le llega al agente como
  trabajo, con tu nombre y tu correo, y él contesta con `paynani webchat send`.
- **El cuadro de escribir**, como Telegram (Q321): una sola barra con el clip («Foto» o «Archivo»), el cuadro, que crece hasta unas 6 líneas, y «Enviar».
- **Adjuntos:** varios archivos o fotos por mensaje, hasta 20 MB cada uno y 25 MB en
  total. El texto puede tener hasta 4000 caracteres. El tipo se revisa por los bytes.
  El POST es `multipart/form-data`, con CSRF y Origin como todo POST, y un cuerpo más
  grande que el límite se rechaza (413) antes de leerlo.
- **Las fotos y los archivos** salen por `/webchat/file?ref=f_…`, nunca por una ruta del
  disco: las fotos `inline` y lo demás como descarga, siempre en sandbox y con `nosniff`.
- **En vivo, por WebSocket** (Q309 = A): `assets/webchat.js` abre `/webchat/ws`, en el
  mismo puerto y origen.
  - **Al abrir:** pide la sesión y el mismo Origin que un POST, y el CSRF de la página en
    el primer frame.
  - **Lo que manda el servidor:**
    - los mensajes nuevos ya dibujados;
    - «escribiendo…»;
    - la respuesta mientras el agente la escribe (`message.delta`, del borrador de
      `paynani webchat send --stream`).

    Mira el almacén cada segundo y manda un ping cada 30 s, para que el proxy del
    gateway no corte la conexión.
  - **Lo que manda el navegador:** el texto solo, por el WebSocket (`message.create`, con
    `request_id` para no duplicar, `message.accepted` y errores con código). El límite es
    de 20 por minuto. Los adjuntos van por el formulario.
  - **Si no conecta:** el script vuelve a pedir `/webchat/updates?after=<id>` cada 3 s,
    sólo con la pestaña visible. Sin script, la página funciona igual y se recarga a mano.
  - **Límite:** como mucho 20 conexiones a la vez.
- **Mensajes anteriores (Q336 = A):** la página trae los últimos 50. Si hay más, arriba
  aparece «Mensajes anteriores», que pide los 50 de antes a
  `/webchat/updates?before=<id>` y los pone arriba sin mover lo que se está leyendo. Sin
  script no aparece.
- **Lo que hace el agente** por Webchat cuenta en la página del agente: atendidos hoy,
  tiempo de respuesta, última respuesta y actividad.
- **Sin el almacén:** si la instalación todavía no trae `webchat/store.py`, la página lo
  dice y no ofrece escribir.

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
  contestaste tú. Una foto se ve en el globo; un documento, con su nombre, su tamaño y la
  descarga por `/whatsapp/file` (#676); lo demás, por su tipo («[audio]»). De un
  número fuera del roster sólo se ven el número y la hora, nunca el texto.
- **Responder** sólo aparece en la conversación de un contacto del roster que ya
  escribió por WhatsApp, con WhatsApp conectado. No hay «Nuevo mensaje»: paynani nunca
  escribe primero, ni el agente ni tú desde aquí. Es la barra de Webchat, igual que en
  Telegram (#670): el cuadro de una línea que crece hasta unas 6 (`barra.js`) y «Enviar»
  redondo, pegada abajo. Si el servicio anuncia `web_files` (#670), lleva el clip
  («Foto», «Archivo»; `adjuntos.js`):
  - **El envío:** hasta 10 archivos y 20 MB por mensaje, que salen uno cada pocos segundos
    (FR-21). La web los sube con `web_uploads.save` y los manda en `whatsapp.send`.
  - **En el hilo:** las fotos que mandaste se ven por `/whatsapp/media?id=wo_…&i=<n>`, y los
    demás archivos sólo con su nombre.

### Telegram

El menú siempre trae «Mensajes de Telegram» (`/telegram/messages`, #635). Sin bot
configurado, las páginas de Telegram llevan a «Cuenta de Telegram» (`/telegram`),
donde se hace la configuración inicial (abajo). La web le
habla al servicio `paynani-telegram` por `state/telegram/control.sock` (`TELEGRAM.md`
§4 y §7).

- **La configuración inicial** (`/telegram` sin bot, #635): pegas el token de
  @BotFather (campo de contraseña, sin autocompletar), escribes el `@usuario` del bot,
  marcas «Este bot es sólo de esta instalación» y escribes la contraseña de la web
  (con el bloqueo de intentos de la entrada). La web hace lo mismo que
  `paynani telegram setup` (`telegram/setup.py`): prueba el token con `getMe`,
  comprueba que el usuario sea el de ese token (Q282), borra un webhook si lo había
  (la casilla lo autoriza, Q283), escribe `telegram.env` (0600) y arranca
  `paynani-telegram`. Si algo falla no se escribe nada. Al terminar te llega un correo
  con el bot, sin el token. Con un token ya puesto pero desactivado, la página no muestra
  el formulario: sólo pide `paynani telegram enable` (#641). La página no enlaza a
  «Mensajes de Telegram», que sin bot es un 404.
- **La cuenta** (`/telegram` con bot): el estado del servicio, el `@usuario` del bot, desde
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
  que se la pide al servicio cada vez). Un documento sale con su nombre, su tamaño y la
  descarga por `/telegram/file` (#676). Un hilo se nombra por un id opaco (`t_…`),
  nunca por un id de Telegram. De alguien fuera del roster se ven el nombre que dio,
  marcado «no verificado», y la hora; el texto sólo con el Catch-All de Telegram
  activo.
- **Contestar** usa la barra de Webchat (Q337): el cuadro de una línea, que crece hasta
  unas 6 (`barra.js`), y «Enviar» redondo, pegada abajo. Si el servicio anuncia
  `web_files` (#662), lleva el clip de Webchat («Foto», «Archivo»; `adjuntos.js`):
  - **El envío:** hasta 10 archivos y 20 MB por mensaje; el texto puede ir vacío. La web
    sube cada archivo con `telegram.uploads.save` y manda los `up_…` en
    `telegram.send`.
  - **En el hilo:** las fotos que mandaste se ven por `/telegram/media?ref=tgo:…&i=<n>`
    y los demás archivos sólo con su nombre.
  - **Con un servicio anterior,** la barra queda sólo con texto.
- **Responder** sólo aparece en la conversación de un contacto del roster que ya le
  escribió al bot, con el servicio funcionando. No hay «Nuevo mensaje»: Telegram no
  deja que un bot escriba primero.
- **Agregar al roster** (FR-15) aparece en la conversación de alguien fuera del
  roster. Pide la contraseña de la web y responde con el formulario de la fila nueva,
  con su nombre y su id de Telegram ya puestos. Es el único lugar donde se ve un id de
  Telegram: no va en la URL, no se guarda en otro lugar y no se escribe en el log. El
  formulario del roster tiene el campo Telegram mientras Telegram esté activado. Si el roster todavía no tiene la columna `Telegram`, guardar un valor la crea en la misma escritura, con las demás filas vacías; sin un valor, el archivo no cambia (#628).
- **El Catch-All de Telegram** es su propia página (`/telegram/catch-all`), junto a
  «Cuenta de Telegram», como los de SMS y WhatsApp (#588). Se guarda en
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
- **Los documentos recibidos** por WhatsApp y Telegram (#676) se bajan siempre como archivo: `attachment` con el nombre limpio (sin `/`, `\\`, comillas ni saltos de línea, y con `filename*` en UTF-8), `application/octet-stream`, `nosniff`, `no-store` y `CSP sandbox`. Así un `.html` o un `.svg` que alguien mande no corre en el origen de PaynaniWeb. El servicio los da en cada pedido sólo si el mensaje se ve en el hilo, y nunca más de 20 MB.
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
