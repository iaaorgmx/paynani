# Changelog

## Sin publicar

- **PaynaniWeb: «Messages» ahora se llama «Text Messages» (#633).** El cambio aplica en todos los lugares donde «Messages» nombra la pantalla de SMS (Q273=A):
  - el menú;
  - el título;
  - «Back to…»;
  - los avisos del Catch-All de WhatsApp y de Telegram.

  Por idioma (Q274=A): en-US «Text Messages», es-MX y es-ES «Mensajes de texto», fr-FR «SMS» y pt-BR «Mensagens de texto». La columna «Messages» (el número de mensajes) no cambia. PaynaniApp hace lo mismo en su propio issue.
## 0.19.0 (2026-10-31)

Telegram (PRD #609, #612): un bot propio por instalación, para recibir y contestar mensajes de los contactos del roster, con Catch-All, multimedia, respuesta por partes, PaynaniWeb y PaynaniApp. Es opcional: sin `--with-telegram` nada cambia en tu instalación. La prueba real TG-9 pasó T9-01 a T9-09 en una instalación de Claude Code; las rondas con OpenClaw y Hermes vienen después de publicar.

### Si actualizas desde 0.18.0

```bash
git fetch --tags --force origin
git pull --ff-only origin main
git describe --tags          # tiene que decir v0.19.0
python3 scripts/upgrade_plan.py --from v0.18.0     # y haz lo que imprima
```

El plan corre `install.sh --upgrade` y reinicia los servicios de paynani, porque cambia `VERSION`. En Claude Code y Codex dice además que el hook de sesión cambió: la siguiente sesión lo toma. `scripts/healthcheck.py` y `scripts/paynani doctor` tienen que salir bien, y `version_drift` tiene que decir `ok`.

- **OpenClaw:** el plan pide `python3 scripts/openclaw_rules.py --install`. Córrelo: trae las instrucciones del aviso `[telegram …]`.
- **`telegram.env` en `.gitignore`:** si ya instalaste Telegram desde `main` antes de esta versión, revisa con `git status --short` que `telegram.env` no aparezca en ningún commit tuyo. Guarda el token del bot.
- **Telegram (opcional):** crea un bot con @BotFather que sea sólo de esta instalación, corre `scripts/install.sh --runtime <runtime> --with-telegram` y después `scripts/paynani telegram setup` (el token se lee de stdin). Todo está en `INSTALL.md` 5.5 y `TELEGRAM.md`. Para que el agente reconozca a alguien, pon su `@usuario` o su id en la columna `Telegram` del roster: si el roster no la tiene, guardarla desde PaynaniWeb, PaynaniApp o `paynani roster edit <correo> --telegram @usuario` la crea.
- **Hermes, antes de instalar Telegram:** copia a `~/.hermes/config.yaml` la lista de eventos y el `prompt` de la ruta `paynani-roster` de `examples/hermes-routes.yaml`, que ahora incluye `telegram.received` y `telegram.edited`, y corre `hermes gateway restart` (`HERMES.md`). Sin eso, Hermes ignora los mensajes de Telegram y la cola del despachador se detiene detrás de ellos, con el correo incluido.
- **Si `version.sh --apply` te dijo «selected runtime is unknown»** al actualizar a 0.18.0, ya está corregido aquí. Para llegar a 0.19.0 desde 0.18.0, el plan que corre es el de 0.19.0, así que no hace falta `PAYNANI_RUNTIME`.
- **PaynaniApp 0.12.0** (opcional): «Mensajes de Telegram», el Catch-All de Telegram y el campo «Usuario de Telegram» en la ficha del contacto. Se instala encima, como siempre. PaynaniApp 0.11.0 no muestra nada de Telegram.

- **`paynani telegram send` y `whatsapp send` aceptan `--file` en cualquier lugar (hallazgo de TG-9, #612).** `paynani telegram send ana --file foto.jpg "texto"` fallaba con «unrecognized arguments», porque argparse deja de juntar las palabras del texto en cuanto ve una opción. Ahora lo que sigue a la opción es la continuación del texto. Una opción desconocida sigue siendo un error. `test_telegram_send.py`.
- **`telegram.env` en `.gitignore` (hallazgo de TG-9, #612).** Guarda el token del bot y no estaba ignorado, a diferencia de `sms.env` y `whatsapp.env`: un `git add -A` en la carpeta de la instalación lo metía en un commit. En la prueba real pasó en un commit local, que se borró sin llegar al remoto. `test_telegram_token.py` lo comprueba.
- **PaynaniWeb: el acceso a Perfil va junto a tu nombre, en el menú lateral (#626).** Como en el /dash de ServiceButton, un ícono de perfil a la derecha del nombre abre `/profile`, y queda resaltado mientras estás ahí. Lleva `aria-label` y `title` «Perfil» en los cinco idiomas. Sale del menú del avatar (Q265=B), y el avatar de arriba a la derecha se quita (Q267=B): «Cerrar sesión» queda en el menú lateral. Funciona igual en el celular, porque es el mismo menú.
- **Roster: el campo Telegram en la CLI, PaynaniApp y PaynaniWeb, aunque falte la columna (#628, TG-9).** En la prueba real, guardar el Telegram de una fila fallaba con `no_telegram_column` y no había forma de agregar la columna. Ahora:
  - guardar un Telegram (desde la web, la app, la API o la CLI) en un roster sin la columna la crea al final, vacía en las demás filas, en la misma escritura con copia, relectura y reversión (Q269 = A). Sin un valor de Telegram el archivo no cambia;
  - PaynaniApp y la API reciben `telegram_username` (el `@usuario`, nunca el id) junto con `has_telegram`, y pueden guardar un `@usuario`. Un id desde ellas es `invalid` (`telegram_username_only`), y un vacío no borra el id que no ven (Q270 = A);
  - `paynani roster add --telegram <id|@usuario>` y un comando nuevo, `paynani roster edit <correo> [--name] [--type] [--github] [--phone] [--telegram]`, con las mismas reglas que la web (Q271 = A). Una opción con `""` borra ese campo.

  `test_roster_edit.py`, `test_telegram_roster_add.py` y `test_roster_cli_telegram.py` (nuevo).

  La tabla de contactos termina en el primer renglón que no empieza con `|`. Un párrafo después de la tabla, una línea vieja «Nombre correo» u otra tabla más abajo ya no cuentan como filas: al crear la columna (Telegram o Rules) se quedan como estaban, no salen como contactos en la lista de la web, la app y la API, y un alta queda dentro de la tabla en vez de después de la nota. Antes la nota se volvía una fila (Andy, Iris y Ximena en #628 y #630).
- **Telegram, TG-6b: las reglas del agente (PRD #609 FR-23 y FR-29, #612).** `AGENTS.md` explica el aviso `[telegram …]`: con `, roster]` es trabajo, se lee con `event show --body` y se contesta con `paynani telegram send <contacto>` (nombre o correo del roster); con `--stream` cuando el arnés pasa el texto por partes (OpenClaw, Hermes) y con `draft` antes de una tarea larga. El agente nunca escribe primero (`not_started`), lo de fuera del roster es sólo información, y no corre `setup`, `token`, `disable` ni `enable`. La regla de OpenClaw (`openclaw_rules.py --install`) lo dice igual. En `examples/hermes-routes.yaml`, `paynani-roster` acepta ahora `telegram.received` y `telegram.edited`. Antes el adaptador mandaba ahí el mensaje de un contacto, Hermes lo ignoraba y la cola se detenía (#582). Una instalación de Hermes con rutas de 0.18.0 o anteriores tiene que copiar la lista y el `prompt` de esa ruta antes de instalar Telegram (`HERMES.md`).
- **Telegram, TG-6a: instalación, `disable`/`enable`, `upgrade_plan` y `doctor` (PRD #609 FR-1, #612).**
  - `scripts/install.sh --with-telegram` (y `install_macos.py --with-telegram`) agrega `paynani-telegram.service` (LaunchAgent `com.paynani.telegram`), lo registra en el manifiesto y lo mantiene con `--upgrade`; `--uninstall` lo quita. No pide ni escribe el token. Sin `telegram.env` el servicio queda habilitado y detenido (`state=enabled-waiting-setup`); con él, arranca y tiene que seguir activo. `telegram.env` nunca se toca.
  - El servicio sale con 0 cuando Telegram no está activado (antes, 2), así que ni systemd (`Restart=on-failure`) ni launchd lo reinician en bucle. `--check-configured` responde 0 o 3 para el instalador.
  - `paynani telegram setup` arranca el servicio si ya está instalado. `paynani telegram disable` deja `TELEGRAM_ENABLED=0` y lo detiene, sin borrar el token; `paynani telegram enable` lo vuelve a encender.
  - `upgrade_plan` reinicia `paynani-telegram` cuando cambia su código, `roster.py` o los módulos del arnés que importa; `telegram/config.py` reinicia también la pasarela y PaynaniWeb, y `sms/telegram_api.py`, la pasarela. Antes todo eso se leía como «se lee en cada llamada» y un upgrade no reiniciaba nada.
  - `paynani doctor` tiene un check `telegram`: `running` es ok; `conflict`, `token_invalid`, `journal_mismatch` y el servicio caído bloquean, cada uno con su arreglo; sin token o sin el servicio instalado, avisa. Nunca muestra el token ni ids.
  - La pasarela avisa `telegram.changed` `status` a PaynaniApp cuando pierde y cuando recupera la conexión con el servicio (sugerencia de Andy en #612).
  - `INSTALL.md` 5.5 explica cómo instalarlo.
- **Roster: la columna Telegram se guarda desde PaynaniWeb, PaynaniApp y la API (PRD #609 FR-11 y FR-15, #612).** «Agregar al roster» en «Mensajes de Telegram» llenaba el formulario con el id, pero `roster.save` lo descartaba: la celda quedaba vacía, y un contacto que sólo tenía Telegram se rechazaba con «hace falta un correo o un teléfono». Ahora `roster_edit`:
  - acepta `member.telegram`, lo valida y lo normaliza con `roster.telegram_value`, como el servicio;
  - cuenta Telegram como canal;
  - rechaza un id o `@usuario` repetido (`duplicate_telegram`, sin decir el valor);
  - falla con `no_telegram_column` si el roster no tiene la columna, sin agregarla;
  - lo incluye en la relectura y en `roster.list` (`telegram`), que sólo PaynaniWeb recibe: PaynaniApp y la API reciben `has_telegram` (FR-15, `TELEGRAM.md` §8).

  Sin la llave `telegram`, una edición conserva lo que la fila tenía y lo cuenta como canal, así que PaynaniApp 0.11 puede editar incluso una fila que sólo tiene Telegram; desde PaynaniWeb, vaciar el campo lo borra. El correo al dueño dice «Telegram: sí» sin el id, y `roster_changes.jsonl` tampoco lo lleva. `test_roster_edit.py` (16 casos nuevos) y `test_telegram_roster_add.py`, de punta a punta con el servicio real: después de guardar, el mensaje siguiente de esa persona llega con `roster_match: true`.
- **Telegram, TG-5: PaynaniApp y la API (PRD #609 FR-29a y FR-30, #612).** Con Telegram configurado, la pasarela anuncia `telegram.status`, `telegram.threads`, `telegram.thread` y `telegram.send` en el `welcome` (sin `grants`) y se los pasa al servicio `paynani-telegram` con `by: phone:<device_id>`, que lo guarda como `owner`. `telegram.send` lleva sólo `thread` y `text`; un reenvío con el mismo `id` no manda otra vez. La pasarela avisa `telegram.changed` y cierra con `1012` si Telegram se activa o desactiva con la app conectada. En la API, `ListTelegramConversations` y `GetTelegramThread` leen con su propio permiso, `telegram.read`, y `SaveCatchAll` acepta `channel: telegram` con `catchall.telegram.write`. Los dos permisos nuevos están en «API Tokens»; un token que ya tenías no los recibe.
- **Telegram, TG-4: mandar (PRD #609 FR-20 a FR-27, #612).** `paynani telegram send <contacto> "<texto>"` contesta a un contacto del roster que ya le escribió al bot; a nadie más (`not_allowed` o `not_started`). Un texto de más de 4096 caracteres sale en varios mensajes, y `--file` manda un archivo de `state/telegram/outbox/` o `TELEGRAM_ATTACH_DIRS` (foto o documento). `--stream` lee stdin mientras llega y lo muestra en el chat con `sendMessageDraft`, o editando un mensaje si Telegram no acepta el borrador, y al cerrar queda como mensaje normal. `paynani telegram draft` muestra un avance que el siguiente `send` reemplaza. Al llegar el mensaje de un contacto, la persona ve «escribiendo…» hasta que sale la respuesta, el agente cierra el evento o pasan 2 minutos. Límites: un mensaje por segundo por chat (el servicio espera) y 300 al día por instalación (`TELEGRAM_SEND_PER_DAY`); un 429 se espera y se reintenta una vez. `paynani telegram threads` y `thread <contacto>` muestran las conversaciones. En `control.sock`: `telegram.send`, `telegram.draft`, `telegram.stream_*`, `telegram.threads`, `telegram.thread`, `telegram.image` y `telegram.watch`, para PaynaniWeb y la pasarela.
- **Telegram, TG-3: contactos, Catch-All y multimedia (PRD #609 FR-11 a FR-18, #612).** Un mensaje se reconoce sólo por el id de quien lo manda. Un `@usuario` de la columna `Telegram` queda fijado al id de su primer mensaje en `links.json` del bot, y el dueño recibe «@usuario quedó vinculado a <contacto>»; otra cuenta con el mismo `@usuario` no se reconoce y el dueño recibe un aviso. Si el dueño cambia la columna, el vínculo se borra. `doctor` tiene el check `roster:telegram` con las filas cuyo valor no vale o está repetido, sin mostrar el valor. Los avisos de un contacto nombran sus reglas, como en WhatsApp. El Catch-All de Telegram es `rules/catch-all-telegram.md`: `catchall.get` y `catchall.save` aceptan `channel: telegram`, el viejo `rules/catch-all.md` no lo abre y la migración de #576 no lo crea; al apagarlo, los avisos que se repiten al iniciar una sesión pierden el extracto (#544). `scripts/paynani event show tg:… --body` da el texto y el archivo con las mismas reglas que WhatsApp, sin ids de Telegram. `telegram.roster_candidate` da a PaynaniWeb el id para «Agregar al roster». Fotos, documentos, audio y video se bajan sólo de alguien del roster (o con el Catch-All activo) a `state/telegram/media/`, hasta 20 MB (`TELEGRAM_MAX_MEDIA_MB`), cortando la descarga al pasar el límite; el tipo se decide por el contenido y tiene que coincidir con el declarado; de oficina sólo `.docx`, `.xlsx` y `.pptx` sin macros, revisando el ZIP sin extraerlo. Lo rechazado se borra y el evento dice `media_rejected`.
- **Telegram, TG-2: el token (PRD #609 FR-8 a FR-10, #612).** `paynani telegram setup` lee el token de stdin (sin eco en una terminal), lo prueba con `getMe`, muestra el `@usuario` del bot y escribe `telegram.env` en `0600`. Si el bot tiene un webhook, lo borra sólo si el dueño lo confirma, y siempre pide confirmar que el token es sólo de esta instalación (`--dedicated` y `--delete-webhook` cuando no hay terminal). `paynani telegram token` (o PaynaniWeb, con `telegram.token_check` y `telegram.token_apply`) cambia de bot sin reiniciar el servicio. Guarda el token anterior en `telegram.env.bak`, espera una ronda de `getUpdates` sin 409, y si hay 409, el bot nuevo no queda listo en 60 s o Telegram deja de aceptar el token, regresa al anterior (`rollback`). Cada bot sigue con su propia carpeta. Al aplicar, el dueño recibe un correo con el `@usuario` nuevo. El token no sale en el log, `status`, los eventos ni las respuestas. `paynani telegram status` dice el estado del servicio.
- **PaynaniWeb: Telegram (TG-7 de #612, PRD #609 FR-28).** Con Telegram activado, el menú agrega «Mensajes de Telegram»:
  - las conversaciones con el bot, con su foto y sus mensajes editados;
  - responder sólo donde la persona ya escribió, sin «Nuevo mensaje»;
  - «Agregar al roster» para alguien fuera del roster, con la contraseña de la web; es el único lugar donde se ve un id de Telegram (FR-15);
  - el Catch-All de Telegram en su propia página, `/telegram/catch-all`, como SMS y WhatsApp (#588).

  «Bot de Telegram» (`/telegram`) muestra el estado y el `@usuario`, y cambia el token en dos pasos (FR-10). El token va en un campo de contraseña, se revisa con `telegram.token_check` y se aplica con `telegram.token_apply` después de confirmar; nunca vuelve a la página, y la revisión vive sólo 5 minutos en la memoria del servidor, por sesión. El dueño recibe un correo sin el token. El Dashboard suma el bot a Servicios y el formulario del roster tiene el campo Telegram. La web habla con `paynani-telegram` por `control.sock` (`TELEGRAM.md` §4) desde `web/telegram_source.py`, con una fuente de demostración (`PAYNANI_WEB_TELEGRAM=demo`). Textos en los cinco idiomas; `test_web_telegram.py` revisa además que ni el token ni los ids salgan en las páginas ni en el log.
- `scripts/version.sh --apply` ya no se niega con «selected runtime is unknown». El plan de la
  versión nueva corre desde una copia temporal y buscaba `runtime.env` junto a esa copia;
  ahora lo lee del clon, como el manifiesto. Mientras tanto, `PAYNANI_RUNTIME=<runtime>`
  antes del comando lo evita.
- **Telegram, TG-1: el servicio `paynani-telegram` (PRD #609 FR-1 a FR-7 y FR-19, #612).** `scripts/telegram_service.py` toma el candado `state/telegram/lock`, valida el token con `getMe`, no toca un webhook ajeno (queda en `conflict`) y recibe con `getUpdates` y espera larga. Cada mensaje privado es un evento `telegram.received` (y una edición, `telegram.edited`) con referencia `tg:…`, sin ids de Telegram, y `account` es `tg:` + un alias aleatorio guardado en la carpeta del bot. El diario por bot y el inbox hacen que una caída en cualquier paso no pierda ni repita un mensaje, y un hash distinto para el mismo update detiene el servicio en `journal_mismatch`. Los grupos y canales sólo dan `leaveChat`. Con 401 queda en `token_invalid`; con 409, en `conflict`; con la red caída reintenta de 1 a 60 s y avisa `offline` a los 10 minutos. `control.sock` contesta `telegram.status`. La columna `Telegram` del roster reconoce por id o `@usuario`, y un `@usuario` ya no se confunde con un correo: `send.sh`, `roster.py` y `roster_edit.py` toman como dirección el campo con `@` que no empieza con `@`. Todavía no se instala (TG-6), y mandar, la multimedia y el Catch-All llegan en TG-3 y TG-4.
- **Telegram, TG-0: el contrato y un servidor falso de la Bot API (PRD #609, #612).** `TELEGRAM.md` fija lo que harán TG-1 a TG-8: las carpetas por bot, los métodos de la Bot API que se usan, los eventos `telegram.received`, `telegram.edited` y `telegram.health` (con referencia opaca `tg:…` y sin ids de Telegram), los tipos de `control.sock` (hilos con id opaco `t_…`, envío, streaming con `stream_open`/`append`/`close`, borrador, cambio de token en dos pasos y la única respuesta con un id, para «Agregar al roster»), los mensajes de PaynaniApp por la pasarela y lo que nunca se registra. `scripts/paynani_lib/telegram/fake_api.py` habla HTTP como la Bot API, sin red: un solo `getUpdates` a la vez (409 al segundo), 409 con webhook, 401 con token revocado, 429 con `retry_after`, confirmación por `offset`, ediciones, grupos, archivos con tamaño declarado distinto del real y chats que rechazan `sendMessageDraft`. `test_telegram_fake_api.py` lo prueba. Todavía no hay servicio: nada cambia en una instalación.

## 0.18.0 (2026-10-31)

**WhatsApp con el mismo número del SMS (PRD #550), un Catch-All por canal (PRD #576) y
una PaynaniWeb que ya administra la cuenta principal y abre en un Dashboard (PRD #602).**
WhatsApp es opcional: no se instala ni se vincula al actualizar. Lo probaron en real
Ocelotl (Codex), Ximena (OpenClaw) y Atenea (Hermes) en WA-8 (#560); el turno de John
(OpenClaw) sigue abierto, y su desvinculación por QR la arregla #604 en esta versión.
Desde PaynaniWeb el dueño ya puede escribir un correo nuevo, cambiar los datos de la
cuenta principal sin que `.env` y Himalaya se separen (#590, #591), y ver el estado de
paynani en la página inicial.

- **`upgrade_plan.py`: un cambio en las dependencias del puente de WhatsApp pide el instalador, no un `npm ci` suelto.** Al preparar 0.18.0, el plan desde v0.17.1 imprimía `npm ci --ignore-scripts --prefix scripts/whatsapp_bridge` en todos los hosts, también en los que no tienen WhatsApp. Ese `npm` sale del PATH: en un host sin Node, o con sólo el Node que bajó el instalador en `~/.local/lib/paynani`, el comando falla, y `--apply` se detenía ahí, después de actualizar el código y antes de reiniciar los servicios, así que seguía corriendo el código anterior. Ahora `package.json` y `package-lock.json` piden `install.sh --upgrade`, que ya corre `npm ci --ignore-scripts` con su Node y sólo si es dueño de la unidad de WhatsApp. `UPGRADE.md` dice lo mismo.
- **PaynaniWeb: la página inicial es un Dashboard con el estado de paynani (PRD #602, de #601).** `/` deja de ser sólo un saludo y muestra:
  - el estado general en verde, amarillo o rojo, con las revisiones de `doctor`: las locales con caché de 60 s y las de red del último `paynani doctor` guardado (#603);
  - cuatro indicadores del día (correo, avisos abiertos, SMS y roster), con un selector de cuenta;
  - Servicios (listener, despachador, sesión del agente, pasarela SMS, WhatsApp y cuentas adicionales);
  - «Necesita tu atención»;
  - una gráfica del correo de los últimos 7 días;
  - los 10 eventos más recientes, sin textos de SMS ni de WhatsApp.

  «Hoy» se cuenta en la zona del host. `assets/dashboard.js` actualiza los números cada 60 s desde `/dashboard.json`, que sólo trae números y estados. Sólo lee: no marca avisos, no abre IMAP y no escribe en `state/`. Textos en los cinco idiomas; `test_web_dashboard.py`.
- **`paynani doctor` guarda su último resultado en `state/doctor.json` (#603, para el Dashboard #602).** PaynaniWeb no puede correr la revisión que toca la red (`himalaya account check`, que con Gmail tarda de 2 a 45 s, #478), así que el Dashboard la toma del último `doctor`. Cada `paynani doctor`, con o sin `--json`, escribe lo mismo que `--json` sin `paths` (`schema_version`, `status`, `generated_at`, `checks`). Lo escribe completo o no lo escribe (archivo temporal y `os.replace`), en modo `0600`. No escribe nada si la carpeta de estado no existe o es un enlace. Si no puede guardar, avisa en stderr y la salida y el código de salida no cambian.
- **WhatsApp: una sesión vinculada por QR ya se puede desvincular y reconecta (#604).** En la prueba de John (WA-8 #560), Julian vinculó por QR desde PaynaniWeb y al desvincular la web respondió 503: el puente contestó `not_connected` y la sesión siguió conectada. El puente sólo contaba como vinculadas las credenciales con `creds.registered`, pero Baileys sólo pone ese campo en el flujo de código. Con QR se queda en `false`. Así, una sesión QR no se podía desvincular, se perdía con el primer corte de red y no volvía al reiniciar el servicio. Ahora `credsLinked()` (`lib.js`) pide `me.id` y `account`, la identidad firmada que Baileys guarda al terminar cualquier vinculación. Un código pedido y todavía no aceptado tiene `me.id` sin `account`, así que no cuenta como vinculación. Además, después de un `logout` correcto el servicio pone su estado en `unlinked` sin esperar el siguiente `status` del puente (lo encontró Iris), y la web y `paynani whatsapp status` ya no muestran «vinculado» por un momento. El puente falso escribe credenciales como las de Baileys y `test_whatsapp_service.py` prueba una sesión QR completa: `already_linked`, reconexión tras un corte y tras reiniciar, y unlink con `auth/` vacío.
- **PaynaniWeb: «Configuración» de la cuenta principal (#590 cambio 3).** Un botón junto a «Nuevo correo» en `/email/main` abre los datos de la cuenta del agente: correo, nombre, IMAP y SMTP con sus puertos, y una contraseña nueva opcional. La actual nunca se muestra. Guardar pide la contraseña de la web con el bloqueo de la entrada (Q10). Al núcleo (#591 N2/N3) sólo va lo que cambió, y los saltos de línea se rechazan. La página muestra la prueba contra el servidor, y el dueño recibe un correo con los campos que cambiaron, sin la contraseña del buzón. Hasta que N2 entre, la pantalla dice que todavía no se puede guardar y no escribe nada. Textos en los cinco idiomas; `test_web_config.py`. `PAYNANI_WEB.md` tiene secciones nuevas para «Nuevo correo» y «Configuración» (#600).
- **Cambiar la cuenta principal desde PaynaniWeb sin que `.env` y Himalaya se separen (#591, N2; para W2 de #590).** La cuenta `paynani` de Himalaya guarda su propia copia de la dirección, los servidores y los usuarios; del `.env` sólo lee la contraseña. Por eso cambiar sólo el `.env` dejaba al listener en un buzón y a `send.sh` en otro (Iris, en #591). `paynani_lib/main_account.py` es un módulo nuevo, sin CLI, y hace el cambio como una sola operación. `check(changes)` valida y prueba IMAP y SMTP sin escribir. `update(changes, by=...)` hace todo con un candado: prueba, escribe `.env` y sólo los valores de `[accounts.paynani]` que nombran el buzón, reinicia el listener con N3 y espera que vuelva con la dirección esperada. Si algo falla, restaura los tres archivos y vuelve a la configuración anterior. Lo que había antes queda en un respaldo `0600`, dentro de `state/main_account.txn/` (`0700`), escrito con fsync antes de tocar nada y nunca reescrito. El cambio sólo cuenta como confirmado si además existe `committed.json`, un marcador aparte con el mismo identificador de transacción, escrito con fsync. Si un commit falla y su marcador no se puede borrar, se escribe `aborted.json` para la misma transacción, y ese marcador gana. Un marcador que existe pero no se puede verificar (truncado, ilegible o un enlace) detiene la recuperación, igual que un respaldo ilegible. Si tampoco se puede escribir, el cambio nuevo se deja completo en vez de restaurar a medias. Si el proceso se cae a la mitad, el siguiente `update()` o `recover()` deshace un cambio sin marcador de commit (o con uno anulado) y sólo limpia uno confirmado. Si el respaldo no se puede leer, no se pueden restaurar los archivos o el listener anterior no vuelve, no sigue ningún cambio: el respaldo se queda como evidencia y `update()` responde `recovery_failed`. Si el nombre del remitente queda vacío, `display-name` sale de Himalaya. Si al bloque principal de Himalaya le falta un valor, se agrega en su tabla, o se agrega la tabla, sin quitar nada más. Si no se puede guardar en disco que el cambio quedó confirmado, el cambio se deshace (`commit_failed`) en vez de reportarse como hecho. Si cambia la dirección, el listener sigue desde el `UIDNEXT` que vio la prueba (guarda `UIDNEXT - 1`): el correo que llegue después se entrega y el anterior no. Las otras cuentas de Himalaya, sus permisos, `password.cmd` y `roster.md` no se tocan. El `Result` y el registro (`state/main_account_changes.jsonl`) sólo llevan nombres de campos, nunca contraseñas, direcciones ni valores. Además, `probe.py` ya no muestra el error de una contraseña con una ñ o un acento, que citaba un carácter de la contraseña y su posición. En su lugar da un mensaje traducido.
- **Instalación: el agente sólo manda la liga del formulario, sin el comando del túnel.** En la prueba de instalación con un agente de Hermes (10-30), el agente le mandó al dueño, junto con la liga, «Si accedes desde otra computadora, crea primero el túnel… `ssh -L 8765:127.0.0.1:8765 usuario@host`». Así lo pedía el paso 2 de `AGENTS.md`, y `scripts/paynani onboard` lo imprimía debajo de la liga. Julian pidió quitarlo: confunde a quien sí está en la máquina, y el nombre del host casi nunca es el correcto. Ahora `onboard` imprime sólo la liga, y `AGENTS.md` le pide al agente mandar sólo eso. Si el dueño dice que la liga no abre, el agente le da el comando de `INSTALL.md` §2.1 (nueva) con el host que el dueño usa. El Paso 2 del README dice lo mismo en los cinco idiomas.
- **PaynaniWeb: «Nuevo correo» en la lista de cada cuenta (#590 cambio 2).** Un botón en `/email/<cuenta>`, como «Catch-All» en «Mensajes», abre un formulario con Para, CC y CCO (Q6=B), asunto y mensaje, que sale desde esa cuenta con su firma (Q7=A). La libreta es el roster de esa cuenta (`compose.js` agrega el contacto al campo donde está el cursor), y se puede escribir cualquier otra dirección. Si alguien está fuera del roster, pide la contraseña de la web con el bloqueo de la entrada (Q5). Las direcciones se validan antes (un salto de línea no cuela un encabezado), y el aviso de la lista dice cuántos estaban fuera del roster sin poner sus direcciones en la URL. El envío es del núcleo (#591 N1, `owner_mail`), con un permiso de un solo uso que la web pide y usa en la misma petición. `send.sh` y la API siguen sin mandar fuera del roster. Textos en los cinco idiomas; `test_web_compose.py`.
- **Núcleo: el correo que escribe el dueño desde PaynaniWeb (N1 de #591, para el cambio 2 de #590).** `scripts/paynani_lib/owner_mail.py` es la pieza del núcleo que usará «Nuevo correo» en PaynaniWeb (W1 de Iris). El dueño puede escribir a direcciones fuera del roster si vuelve a teclear la contraseña de la web (Q5 y Q8 en #590). `outside_roster(cuenta, direcciones)` dice cuáles están fuera del roster de esa cuenta (`roster.md` para la principal, `rosters/<id>.md` para las demás) y compara en forma canónica: sin espacios, parte local en minúsculas y dominio en IDNA. La web llama `authorize(...)`, con `allow_outside=True` sólo después de revisar la contraseña, y recibe un permiso de un solo uso que dura 60 s en el reloj monotónico. El permiso vive sólo en la memoria del proceso de PaynaniWeb, no se puede copiar ni serializar, y queda ligado a la operación, la cuenta, los destinatarios, `by` y la dirección del aviso. `send(permiso, asunto, cuerpo)` lo consume bajo un lock y vuelve a comprobar cada uno de esos datos. También vuelve a calcular quién está fuera del roster: si alguien quedó fuera entre las dos llamadas y el permiso no lo autorizó, responde `not_authorized` antes de mandar nada. El mensaje sale igual que uno de texto de `send.sh`: el mismo From y la misma firma, Bcc sólo en el sobre SMTP, copia en Enviados y su línea en `sent.log`. Cada llamada deja una línea en `state/owner_sends.jsonl`, sin asunto ni cuerpo. Si alguna dirección estaba fuera del roster, el dueño recibe un aviso por `send.sh`; un aviso que no sale queda como `notice: failed` y no cambia el resultado del envío. `send.sh` y la API no cambian: siguen rechazando a quien no está en el roster, y no hay opción nueva. Es una autorización operativa contra errores y contra correos que intenten convencer al agente, no una separación de privilegios: el mismo usuario del sistema puede leer `.env`. `AGENTS.md` prohíbe a los agentes usar este módulo.
- **Reiniciar el listener desde PaynaniWeb y saber cuándo volvió (#591, N3; para W2 de #590).** `paynani_lib/listener_control.py` es un módulo nuevo, sin CLI. Lo llama PaynaniWeb después de guardar la configuración del buzón. `restart(account=None)` reinicia sólo un listener de paynani: el principal o el de una cuenta adicional, con `systemctl --user` en Linux o `launchctl kickstart -k` en macOS. El nombre del servicio sale de un valor fijo o de `account_service`, nunca de quien llama, y nada usa sudo. `status(since=..., expect=..., previous_pid=...)` dice `connected` sólo con un latido posterior al reinicio, de un proceso nuevo y de la dirección esperada; mientras tanto dice `waiting`, con el error de entrada o de conexión en `last_error`. `wait()` hace lo mismo con un límite de tiempo. Para eso el listener guarda en `idle.json` la dirección del buzón que lee. Un cursor guardado para otra dirección ya no se reutiliza: el listener empieza en el mensaje más nuevo del buzón. Cuando el servidor rechaza la contraseña, el listener deja el motivo en `imap_last_login_error` sin tocar el latido, y sigue saliendo con código 1. Un `idle.json` anterior, sin dirección, se conserva como siempre.
- **PaynaniWeb: el Catch-All de WhatsApp está en «Mensajes de WhatsApp» (#588, Q231=A).** La tarea 2 de #584 puso las secciones de SMS y de WhatsApp juntas en la página «Catch-All» de «Mensajes». Julian pidió que el de WhatsApp vaya con WhatsApp. Ahora «Mensajes» → «Catch-All» (`/messages/catch-all`) muestra sólo el de SMS, y «Mensajes de WhatsApp» tiene su propia liga «Catch-All», junto a «Cuenta de WhatsApp», que abre `/whatsapp/catch-all` con sólo el de WhatsApp. Cada página tiene su casilla, sus instrucciones y su contraseña, como antes, y dice dónde está la otra. `/whatsapp/catch-all` responde 404 si WhatsApp no está activado. El canal lo decide la ruta: un formulario viejo que mande otro `channel` no guarda nada y la página lo dice. Después de guardar, la página vuelve a sí misma (`?ok=on` u `?ok=off`). Textos nuevos en los cinco idiomas. No cambian los archivos, la API ni PaynaniApp.
- **Docs y reglas del agente: el Catch-All por canal (PRD #576, tarea 4 de #584).** `AGENTS.md` explica que cada canal tiene su propio Catch-All (`rules/catch-all-sms.md`, `rules/catch-all-whatsapp.md`), que mientras el dueño no guarde uno los dos canales leen el `rules/catch-all.md` de antes, y que la etiqueta del aviso nombra el archivo que se usó. Un WhatsApp del Catch-All sigue sólo las instrucciones de WhatsApp, sin importar si el de SMS está activo, y lo mismo al revés. La regla permanente de OpenClaw (`openclaw_rules.py`) ya no busca el texto exacto `catch-all: rules/catch-all.md` en un SMS: reconoce cualquier archivo del Catch-All, en SMS o en WhatsApp. En un host de OpenClaw hay que volver a correr `scripts/openclaw_rules.py --install`, y el plan de actualización ya lo pide. `SMS_GATEWAY.md` y `WHATSAPP_BRIDGE.md` dicen qué Catch-All cuenta en cada caso. Los ejemplos usan `+1XXXXXXXXXX`.
- **PaynaniWeb: una sección del Catch-All por canal (PRD #576, tarea 2 de #584).** La página «Catch-All» tiene ahora una sección para SMS y otra para WhatsApp, cada una con su casilla, sus instrucciones y su botón. Cada sección dice qué abre («SMS de números fuera del roster», «WhatsApp de números fuera del roster»), se guarda sola y pide la contraseña como antes. El aviso de guardado y los errores salen en la sección del canal que se cambió. Mientras un canal sigue leyendo `rules/catch-all.md`, su sección lo dice. El texto de #575, que decía que activarlo o apagarlo cambiaba los dos canales, ya no aplica y se reemplazó en los cinco idiomas.
- **Catch-All: un archivo por canal, SMS y WhatsApp (PRD #576, tarea 1 de #584).** Antes había un solo `rules/catch-all.md` para los dos canales: no se podía, por ejemplo, recibir los SMS de números desconocidos sin abrir también los WhatsApp de cualquiera. Ahora cada canal tiene su archivo, `rules/catch-all-sms.md` y `rules/catch-all-whatsapp.md`, y se lee solo: si uno falta, está apagado o está roto, el otro sigue igual. La pasarela de SMS lee sólo el de SMS, el servicio de WhatsApp sólo el de WhatsApp, y la etiqueta del aviso nombra el archivo que se usó. `event show --body`, los avisos que se repiten al iniciar una sesión y el hilo y las fotos de WhatsApp siguen el Catch-All de su canal. Al actualizar no cambia nada: mientras un canal no tenga su archivo, usa `rules/catch-all.md`. El primer guardado (desde la web, PaynaniApp o la API) crea el archivo de cada canal que falte con lo que tenía el viejo, aplica el cambio y quita el viejo, con su copia en `state/history/`. Si algo falla, también al quitar el viejo, se deshace lo escrito, el viejo se queda y el guardado devuelve error. El correo al dueño dice qué canal cambió y, esa primera vez, que hubo migración. `catchall.get` y `catchall.save` (y `GetCatchAll`, `SaveCatchAll` en la API) reciben `channel` (`sms` o `whatsapp`); sin `channel` es `sms`, para que PaynaniApp 0.10.0 siga funcionando, y eso queda como obsoleto. Cambiar el Catch-All por la API pide el permiso de ese canal, `catchall.sms.write` o `catchall.whatsapp.write`. Un token que tenía `catchall.write` queda sólo con `catchall.sms.write`: PaynaniWeb lo reescribe al arrancar y le manda al dueño un correo con los tokens que cambiaron. «API Tokens» ofrece las dos casillas nuevas. `catch-all-sms`, `catch-all-whatsapp` y `catch-all-telegram` quedan reservados como `catch-all`. PaynaniWeb tiene una sección por canal (entrada de arriba) y PaynaniApp, desde su PR #159, un selector SMS / WhatsApp.
- **Hermes: las rutas del ejemplo aceptan SMS, WhatsApp y llamadas (#582).** `HERMES.md` decía que los SMS y los mensajes de WhatsApp llegaban por las mismas dos rutas, pero `examples/hermes-routes.yaml` sólo aceptaba correo (`email.received`, más `listener.error` en la ruta de avisos). Hermes contestaba `200 ignored` a todo lo demás, y el despachador dejaba la cola detenida detrás, con el correo incluido. En la prueba real de Hermes (WA-8 #560) quedaron 4 eventos de WhatsApp detenidos. Ahora `paynani-notify` acepta todos los tipos que escribe paynani y `paynani-roster` los que tienen remitente (`email.received`, `sms.received`, `sms.human_sent`, `whatsapp.received`, `call.missed`, `call.answered`). El `prompt` de la ruta del roster dice cómo leer un SMS o un WhatsApp (`paynani event show <id> --body`) y una llamada (`paynani event show <id>`, sin `--body`, porque una llamada no tiene cuerpo), que nunca se escribe primero y que el agente nunca vincula ni desvincula WhatsApp. `scripts/test_hermes_examples.py` revisa las dos listas exactas y falla si un tipo nuevo de `harness/event.py` no está en la ruta de avisos. Cuando Hermes ignora un evento, el error que muestra `healthcheck.py` dice qué tipo fue y qué cambiar. `HERMES.md` tiene una sección nueva, «Event lists», que explica cómo actualizar las rutas de una instalación de 0.17.1 o anterior: cambiar las dos listas y el `prompt`, y reiniciar el gateway. En un host de Hermes, `upgrade_plan.py` lo pide como paso manual cuando cambia `examples/hermes-routes.yaml`.
- **WhatsApp: al desvincular siempre se pide revisar «Dispositivos vinculados» en el teléfono (#578).** En la prueba real 1 (WA-8 #560), `paynani whatsapp unlink` terminó bien y WhatsApp aceptó la salida (`remote: true`), pero el teléfono siguió mostrando el dispositivo más de cuatro minutos y hubo que quitarlo a mano. Hasta ahora el aviso de quitarlo a mano sólo salía cuando WhatsApp no contestaba. Ahora el CLI y PaynaniWeb, en los cinco idiomas, siempre piden revisar «Dispositivos vinculados» y quitar el dispositivo si sigue ahí. Si WhatsApp no contestó, el CLI también lo dice. `INSTALL.md` 5.4 y `AGENTS.md` dicen lo mismo. No cambia el comportamiento. PaynaniApp lleva el mismo texto en su propio PR.
- **PaynaniWeb: el texto del Catch-All dice que también aplica a WhatsApp (#575).** La página «Catch-All» decía sólo «los SMS de números que no están en el roster…», aunque el servicio de WhatsApp lee el mismo `rules/catch-all.md`. Quien lo apagaba pensando en los SMS apagaba también WhatsApp sin saberlo. Ahora el texto, en los cinco idiomas, dice SMS y WhatsApp y aclara que activarlo o apagarlo cambia los dos canales. `AGENTS.md` dice lo mismo en la línea del aviso de SMS. No cambia el comportamiento; separar el Catch-All por canal es el PRD #576.
- **PaynaniWeb: las fotos de WhatsApp se ven en «WhatsApp messages» (#573, Q199=A).** Antes un mensaje con foto decía sólo `[photo]`. Ahora la foto sale en el globo, reducida; al tocarla se abre completa en otra pestaña, y el pie va debajo. Sólo se muestra si también se mostraría el texto (FR-16a), y eso se vuelve a revisar cada vez que se carga: apagar el Catch-All o sacar al contacto del roster deja de servirla, también a una pestaña ya abierta. La web la pide al servicio con `whatsapp.image` por `control.sock` (`WHATSAPP_BRIDGE.md` §11), con el id del mensaje y nunca con una ruta. El servicio abre sólo un archivo regular directamente dentro de `state/whatsapp/media/`, sin seguir enlaces simbólicos y hasta 10 MB, y el tipo (JPEG, PNG o WebP) sale de sus primeros bytes, no de la extensión. `GET /whatsapp/media` responde con `no-store`, `nosniff`, `inline` y una CSP `sandbox`. Un id inventado, uno de fuera del roster, uno que no es foto o uno sin archivo dan el mismo 404. Audio, video, documentos y stickers siguen como antes, y la API sigue sin archivos. `upgrade_plan.py` reinicia el servicio de WhatsApp, la pasarela y PaynaniWeb cuando cambia `whatsapp/media.py`, porque la web también lo carga.
- **WhatsApp: una llamada dice quién llamó aunque WhatsApp mande su LID (prueba de campo WA-8 #560).** En la prueba real, la llamada perdida de un contacto del roster llegó como «número sin resolver». WhatsApp mandó la llamada con el LID del contacto (un id interno) y el número en `callerPn`. El puente usaba sólo `from`, mientras que a los mensajes sí les buscaba el número. Ahora mensajes y llamadas pasan por la misma `resolveJid()` de `lib.js`: primero el número alterno (`remoteJidAlt` en un mensaje, `callerPn` en una llamada), luego el mapa LID → número de Baileys. Sólo sin ninguno de los dos queda «número sin resolver».
- **WhatsApp: el puente ya no deja salir lo que libsignal escribe en la consola (prueba de campo WA-8 #560).** libsignal, la librería de cifrado debajo de Baileys, escribe con `console.*` y a veces pasa la sesión cifrada completa, con sus llaves. Por ejemplo, `console.warn("Session already closed", session)`. Lo que sale por stdout el servicio ya lo descartaba sin registrarlo. Lo que sale por stderr se copiaba a `state/whatsapp.log` (FR-10). Ahora el puente cambia `console.*` antes de cargar Baileys: `log`, `info` y `debug` no escriben nada, y de `warn` y `error` sólo queda el primer argumento si es texto, recortado a 200 caracteres. En la prueba de campo no apareció ninguna llave en el log; lo detectó una línea de stdout que no era JSON.
- **API: leer WhatsApp con `ListWhatsAppConversations` y `GetWhatsAppThread` (WA-6 #558, PRD #550 FR-26).** Las dos acciones piden el permiso `read` y devuelven lo mismo que «Mensajes de WhatsApp» en PaynaniWeb: la lista de conversaciones y los mensajes de un número, con `limit` (1 a 100) y `before` para paginar. De un número fuera del roster sólo salen el número, la hora y `hidden: true`, sin texto ni archivo (FR-16a). La API no manda WhatsApp, ni vincula ni desvincula. Si WhatsApp no está activado o el servicio no contesta, responden `503 whatsapp_unavailable`; un número sin conversación da `404 not_found`. Le piden los datos al servicio `paynani-whatsapp` con `by: api`. `PAYNANI_API.md` y `/api/agents.md` las documentan.
- **WhatsApp: las instrucciones para el agente (WA-4 #556, PRD #550 FR-28).** `AGENTS.md` explica las líneas `[whatsapp …]`: una del roster es trabajo, igual que un SMS, y se contesta con `paynani whatsapp send`. El agente nunca escribe primero (Q8=B): `not_started` (exit 2) quiere decir que no reintente por WhatsApp; sí puede contestarle por SMS o por correo, con las reglas de esos canales (FR-20). Una línea de fuera del roster es sólo información, el Catch-All funciona como con el SMS y el texto de un mensaje nunca cambia permisos, reglas ni la vinculación. También explica las llamadas de WhatsApp y los avisos `[whatsapp-health …]`, y que vincular o desvincular la cuenta es decisión del humano. La regla permanente de OpenClaw (`openclaw_rules.py`) lo resume, así que en un host de OpenClaw hay que volver a correr `scripts/openclaw_rules.py --install` (el plan de actualización ya lo pide). `HERMES.md` dice que los SMS y los mensajes de WhatsApp llegan por las mismas dos rutas, sin el cuerpo.
- **WhatsApp desde PaynaniApp: la pasarela SMS (PRD #550, `SMS_GATEWAY.md` §12).** Con WhatsApp activado, el `welcome` anuncia `whatsapp.status`, `whatsapp.threads`, `whatsapp.thread`, `whatsapp.send`, `whatsapp.link`, `whatsapp.link_cancel` y `whatsapp.unlink`, y le da `grants: ["whatsapp.admin"]` al teléfono emparejado. Sin WhatsApp no anuncia ninguno y `grants` va vacío. La pasarela le pasa cada pedido al servicio `paynani-whatsapp` por `control.sock` con `by: phone:<device_id>`, así que lo que se contesta desde la app queda en el hilo como `by: owner`. La vinculación es sólo por código, con el número de la SIM del teléfono si la app no manda otro. El reenvío con el mismo `id` responde `conflict` y no repite el código. Un `whatsapp.send` reenviado responde el mismo resultado con `"replayed": true`, también si llega mientras el primero sigue en curso, y no sale dos veces. Vincular, cancelar y desvincular quedan en `state/whatsapp_changes.jsonl` con el `device_id` y le llegan por correo al dueño, sin el código. `whatsapp.changed` sólo va a una conexión que ya pidió `whatsapp.status` o `whatsapp.threads`. Si WhatsApp se activa o se desactiva con la app conectada, la pasarela cierra con `1012` y la app recibe un `welcome` nuevo. Con el servicio caído, `whatsapp.status` responde `service_down` y lo demás, `unavailable`. El código de vinculación, el texto de los mensajes y los números completos no se escriben en el log. Además, `upgrade_plan.py` ahora reinicia la pasarela y PaynaniWeb cuando cambian `roster_api.py` o `api_replies.py`, porque los dos los cargan al arrancar y antes el plan decía que no hacía falta. Y cuando cambia `whatsapp/config.py`, reinicia también el servicio de WhatsApp. Si cambia el teléfono emparejado, el anterior se sigue cerrando con `4401` (sección 5), no con `1012`: su token ya no sirve para reconectar. §12 ahora lo dice así. Arreglo del servicio `paynani-whatsapp`: `stop()` esperaba a que se cerraran todas las conexiones a `control.sock` antes de cerrar la de `whatsapp.watch`, así que con la pasarela conectada un `systemctl stop` se colgaba hasta que systemd lo mataba a los 90 s. Ahora cierra primero las conexiones.
- **PaynaniWeb: WhatsApp, la cuenta y «Mensajes de WhatsApp» (WA-5 #557, PRD #550 FR-7, FR-24).** Con WhatsApp activado, el menú agrega «Mensajes de WhatsApp» (`/whatsapp/messages`): la lista de conversaciones y cada una, como «Mensajes» muestra las de SMS, sin botón de mensaje nuevo (Q189=A). El cuadro de responder sólo aparece cuando el servicio dice `can_reply` (FR-20), y de un número fuera del roster sólo se ven el número y la hora (FR-16a). `/whatsapp` muestra el estado y vincula con QR o con código, cancela y desvincula. Las tres acciones piden la contraseña de la web, el CSRF y el `Origin`, con el bloqueo de intentos de la entrada (FR-6a). El `link_id` vive sólo en la memoria del servidor, ligado a la sesión del navegador. `whatsapp.js` pide el QR vigente a `/whatsapp/link/current` cada 3 s y lo dibuja con `sms/qr.py`; el código sólo sale en la respuesta que lo pidió. Sin `whatsapp.env` activado no aparece nada. La web habla con el servicio por `control.sock` (`WHATSAPP_BRIDGE.md` §11) desde `web/whatsapp_source.py`, que también trae una fuente de demostración (`PAYNANI_WEB_WHATSAPP=demo`) para las pruebas. Textos en los cinco idiomas.
- **PaynaniWeb: la CSP deja `fetch()` al mismo origen (`connect-src 'self'`).** Sin esa directiva, `fetch()` caía en `default-src 'none'` y el navegador lo bloqueaba. Por eso los estados de los SMS mandados desde la web no se actualizaban solos en la conversación (PRD #489 FR-5): había que recargar. Ahora `sms.js` y `whatsapp.js` pueden preguntarle a este mismo servidor, y a nada más.
- **WhatsApp: la instalación con `--with-whatsapp` (WA-3 #555, PRD #550).** `scripts/install.sh --with-whatsapp` (y `install_macos.py --with-whatsapp`) instala el servicio sólo cuando el dueño lo pide (FR-1). Usa el Node 20 o más nuevo de la terminal si tiene `npm` en la misma carpeta. Si no lo hay (Ubuntu 24.04 y Debian 12 traen Node 18), baja de `nodejs.org` el Node 22 fijado en `scripts/node_release.json` a `~/.local/lib/paynani/`, sin `sudo`, y sólo lo usa si su SHA-256 coincide con el del repositorio; si no, se detiene antes de escribir nada (Q197=B, `scripts/node_runtime.py`). Los hashes salen del `SHASUMS256.txt` firmado de esa versión. `--dry-run` dice qué Node usaría sin bajarlo, y `upgrade_plan.py` pide el instalador otra vez cuando cambia el Node fijado. Corre `npm ci --ignore-scripts` en `scripts/whatsapp_bridge/` (FR-3). Escribe `whatsapp.env` con `WHATSAPP_ENABLED=1` si no existe; después es del dueño y ninguna instalación lo cambia ni lo borra. Agrega `paynani-whatsapp.service` (LaunchAgent `com.paynani.whatsapp` en macOS) con la carpeta de `node` primero en su `PATH`, y lo registra en `install.manifest`; las llaves de `state/whatsapp/auth/` nunca entran ahí (FR-10). `--upgrade` lo mantiene y `--uninstall` lo quita, sin la bandera. `INSTALL.md` 5.4 explica de dónde sale Node, cómo vincular y advierte del riesgo de bloqueo de Meta antes de vincular (PRD sección 5).

- **WhatsApp: `paynani whatsapp`, el diario y las reglas de envío (WA-2 #554, PRD #550).** El servicio `paynani-whatsapp` escribe cada mensaje directo como `whatsapp.received` en el diario, con el mismo sobre que un SMS. Su id es `wa:<número>:<hash>` y WhatsApp puede reentregarlo sin que se duplique (FR-11a). Las llamadas llegan como `call.missed` o `call.answered` con `channel: whatsapp`, y la salud como `whatsapp.health` (FR-5, FR-18). Un número del roster lleva sus reglas. Un número de fuera no muestra su texto, salvo que el Catch-All esté activo (FR-12 a FR-16a), y `paynani event show --body` aplica la misma regla que con el SMS. Sólo se le contesta a un contacto del roster que ya escribió por WhatsApp desde que se vinculó la cuenta (FR-20), con un envío cada 3 s y 200 al día como máximo (`whatsapp.env`, FR-21). Un archivo tiene que estar en `state/whatsapp/outbox/` o en `WHATSAPP_ATTACH_DIRS` y no puede ser un enlace simbólico (FR-22). Respeta `reply.sms: never` de las reglas del contacto. `paynani whatsapp status`, `link` (QR en la terminal, o `--code --number`), `unlink`, `send` y `thread` le hablan al servicio por `state/whatsapp/control.sock` (0600), el mismo socket que usan la pasarela SMS y PaynaniWeb (`WHATSAPP_BRIDGE.md` §11). Cada vinculación tiene su `link_id`. Un QR que nadie consulta en 60 s se cancela. El código vive 180 s y sale una sola vez. `scripts/whatsapp_service.py` sale con 2 si `whatsapp.env` no tiene `WHATSAPP_ENABLED=1`.
- **WhatsApp: el puente de Baileys y el servicio `paynani-whatsapp` (WA-1 #553, PRD #550).** `scripts/whatsapp_bridge/` es el puente en Node, con Baileys fijo en `7.0.0-rc14` y su `package-lock.json` con hashes (FR-3). Las pruebas revisan que ninguna dependencia directa tenga un rango (FR-3a). El puente se conecta sin presencia ni historial (FR-4, FR-4a), sólo deja pasar chats directos (FR-17) y no abre ningún puerto (FR-2). `scripts/whatsapp_service.py` lo arranca como proceso hijo y lo relanza a los 5, 10 y 30 s y luego cada 60 s. Si deja de contestar tres pings, lo reinicia, y avisa cuando pasan 10 minutos sin conexión o WhatsApp cierra la sesión (FR-5). Las llaves quedan en `state/whatsapp/auth/` con 0700/0600, y ni el servicio ni el puente arrancan si están abiertas o si una carpeta de `state/whatsapp/` es un enlace simbólico, para no tocar nada fuera de ahí (FR-10). `upgrade_plan.py` reinicia `paynani-whatsapp` cuando cambia su código, y corre `npm ci --ignore-scripts` antes cuando cambia el lockfile. El QR y el código de vinculación nunca se escriben en disco ni en el log (FR-6a). La plantilla de systemd y la instalación llegan con WA-3. Las pruebas usan un puente falso con el mismo contrato (`fake_bridge.py`), y nada se conecta a WhatsApp.
- **WhatsApp: el contrato del puente y los mensajes de PaynaniApp (WA-0 #552, PRD #550).** `WHATSAPP_BRIDGE.md` describe cómo se hablan el servicio `paynani-whatsapp` y el puente de Baileys: un JSON por línea por stdin/stdout, sin puerto; arranque, estado, vinculación por QR o código (credenciales de un solo uso que nunca se guardan ni se registran), mensajes directos sin historial ni grupos, archivos, llamadas, envío con su lista `allowed`, acuses, salud, desvincular y cierre. `SMS_GATEWAY.md` §12 agrega para PaynaniApp `whatsapp.status`, `whatsapp.link`, `whatsapp.link_cancel`, `whatsapp.unlink`, `whatsapp.threads`, `whatsapp.thread`, `whatsapp.send` y el aviso `whatsapp.changed`, anunciados en `welcome.accepts`, y `welcome.grants` con la capacidad `whatsapp.admin`, que la pasarela sólo le da al teléfono emparejado. Todavía no hay código: es el contrato que siguen WA-1 a WA-7.
- **`bootstrap.sh` corre los comandos del dueño desde su `$HOME`** (#562). Un `git` reciente no arranca si no puede leer el directorio donde lo lanzaron. Por eso `git clone` fallaba con `Invalid path ...: Permission denied` cuando root corría `bootstrap.sh` desde `/root` o desde el checkout de CI. Un `--dir` relativo se resuelve contra el directorio de quien llama, como antes.

Lo hicieron Metis, Iris y Andy, con la revisión de Ximena. Sin requisitos nuevos para
quien no instala WhatsApp. Con PaynaniApp 0.11.0.

### Si actualizas desde 0.17.1

```bash
git fetch --tags --force origin
git pull --ff-only origin main
git describe --tags          # tiene que decir v0.18.0
python3 scripts/upgrade_plan.py --from v0.17.1     # y haz lo que imprima
```

El plan corre `install.sh --upgrade` y reinicia todos los servicios de paynani, porque
cambia `VERSION`. En Claude Code y Codex dice además que el hook de sesión cambió: la
siguiente sesión lo toma, y ahí se vuelve a armar la vigilancia del correo.
`scripts/healthcheck.py` y `scripts/paynani doctor` tienen que salir bien, y
`version_drift` tiene que decir `ok`. `doctor` deja su resultado en `state/doctor.json`,
que es lo que el Dashboard muestra como revisión de red.

- **OpenClaw:** el plan pide `python3 scripts/openclaw_rules.py --install`. Córrelo: trae
  el Catch-All por canal y las instrucciones de WhatsApp.
- **Hermes:** el plan pide copiar las dos listas de eventos y el `prompt` de
  `examples/hermes-routes.yaml` a `~/.hermes/config.yaml` y correr `hermes gateway
  restart` (`HERMES.md`, «Event lists»). Sin eso, Hermes ignora los SMS, los WhatsApp y
  las llamadas, y la cola del despachador se detiene detrás de ellos, con el correo
  incluido.
- **Catch-All:** no cambia nada al actualizar. Los dos canales siguen leyendo
  `rules/catch-all.md` hasta el primer guardado, que lo separa en
  `rules/catch-all-sms.md` y `rules/catch-all-whatsapp.md` con lo que tenía.
- **Tokens de la API:** un token con `catchall.write` queda sólo con
  `catchall.sms.write`. PaynaniWeb lo reescribe al arrancar y le manda al dueño un correo
  con los tokens que cambiaron.
- **WhatsApp (opcional):** `scripts/install.sh --with-whatsapp` (`INSTALL.md` 5.4). Lee
  antes el aviso de riesgo de bloqueo de Meta de esa sección. Después se vincula desde
  PaynaniWeb, «WhatsApp», con QR o con código. El agente nunca vincula ni desvincula.
- **PaynaniApp 0.11.0** (opcional): «WhatsApp» y «Mensajes de WhatsApp», el Catch-All por
  canal y los globos con los colores de PaynaniWeb. Se instala encima, como siempre
  (`INSTALL.md`, sección del teléfono). PaynaniApp 0.10.0 sigue funcionando con la
  pasarela nueva.

### Si actualizas desde 0.17.0 o anterior

Un solo salto desde la versión que tienes instalada. Cambia `v0.17.0` por tu versión
(la que dice `scripts/version.sh` antes de actualizar):

```bash
git fetch --tags --force origin
git pull --ff-only origin main
git describe --tags          # tiene que decir v0.18.0
python3 scripts/upgrade_plan.py --from v0.17.0     # y haz lo que imprima
```

Después, lo mismo que arriba y lo que pidan las secciones «Si actualizas» de las
versiones que te saltaste.

## 0.17.1 (2026-10-26)

**Dos arreglos que salieron después de 0.17.0: el plan de actualización en hosts de
OpenClaw con el runtime entre comillas, y el extracto de un SMS del Catch-All después
de apagarlo.** Los dos los encontró la ronda de 0.17.0: Ximena al actualizar su Mac
y John en la prueba real.

- **`upgrade_plan.py` reconoce el runtime con comillas en `runtime.env`** (#546). El instalador escribe `PAYNANI_RUNTIME="openclaw"`, y el plan leía el valor con las comillas, así que en un host de OpenClaw marcaba `openclaw_rules.py` y `session_start.py` como «not on this host» y no pedía reinstalar la regla permanente (Ximena, al actualizar su Mac a 0.17.0). Ahora quita las comillas igual que `harness/session_start.py`. `--runtime` y la variable `PAYNANI_RUNTIME` siguen mandando.
- **Catch-All apagado: el extracto tampoco se vuelve a ver** (#544). Con el Catch-All apagado o roto, `event show` de un SMS que llegó con él activo ya no repite el extracto en el sobre: `notification_text` dice `catch-all apagado` y «mensaje de un número fuera del roster», y `catch_all_now` dice `off` o `invalid`. Al iniciar una sesión, ese aviso sin cerrar ya no se repite como trabajo pendiente, y los avisos del Catch-All que vengan del spool o del journal salen sin el extracto. `--body` se sigue negando como en 0.17.0. Lo encontró John en la prueba real (#533).

Lo hizo Metis, con la revisión de Ximena. Sin requisitos nuevos. Con PaynaniApp
0.10.0.

### Si actualizas desde 0.17.0

```bash
git fetch --tags --force origin
git pull --ff-only origin main
git describe --tags          # tiene que decir v0.17.1
python3 scripts/upgrade_plan.py --from v0.17.0     # y haz lo que imprima
```

El plan reinicia todos los servicios de paynani, porque cambia `VERSION`. En Claude
Code y Codex dice además que el hook de sesión cambió: la siguiente sesión lo toma, y
en Claude Code ahí se vuelve a armar la vigilancia del correo. En OpenClaw y Hermes ese
hook no se usa, y el plan lo marca «not on this host». `scripts/healthcheck.py` y
`scripts/paynani doctor` tienen que salir bien, y `version_drift` tiene que decir `ok`.

### Si actualizas desde 0.16.2 o anterior

Un solo salto desde la versión que tienes instalada. Cambia `v0.16.2` por tu versión
(la que dice `scripts/version.sh` antes de actualizar):

```bash
git fetch --tags --force origin
git pull --ff-only origin main
git describe --tags          # tiene que decir v0.17.1
python3 scripts/upgrade_plan.py --from v0.16.2     # y haz lo que imprima
```

Después, lo que pidan las secciones «Si actualizas» de 0.17.0 (OpenClaw, Hermes,
tokens y PaynaniApp 0.10.0) y de las versiones que te saltaste. En OpenClaw, el plan
ya pide `openclaw_rules.py --install` aunque `runtime.env` tenga las comillas.

## 0.17.0 (2026-10-25)

**El Catch-All de SMS: con él activo, los SMS de números que no están en el roster
le llegan al agente con las instrucciones del dueño (PRD #535, #533).** Se activa y
se edita desde PaynaniWeb, desde PaynaniApp 0.10.0 o con la API. Mientras esté
apagado, que es como queda al actualizar, los SMS se manejan igual que en 0.16.2. Trae
también el menú fijo y colapsable de PaynaniWeb (PRD #537).

- **PaynaniWeb: el menú se queda fijo y se colapsa, como en ServiceButton** (PRD #537, #536). El menú lateral, la barra de arriba y el encabezado grana se quedan fijos al hacer scroll (`position: sticky` sobre el scroll de la ventana; un `scroll-padding-top` evita que un `#m-<id>` del hilo quede debajo de ellos). El botón nuevo junto al logotipo colapsa el menú y el contenido usa todo el ancho; ☰ y el logotipo aparecen en la barra y lo vuelven a abrir. El estado va en la cookie `paynani_web_nav`, que escribe `assets/nav.js` (servido desde `/assets/` con `defer`, así que la CSP no cambia) y que el servidor lee para dibujar la página ya colapsada, sin parpadeo. En el celular hay un solo menú, que empieza escondido y se abre encima del contenido con un velo; se cierra con el velo, con Esc o al elegir una entrada. Se quita la segunda copia del menú (`menu-movil`). Sin JavaScript, el menú queda abierto en el escritorio y ☰ lo abre en el celular por `:target`. Los textos nuevos van en los cinco idiomas; la animación dura 150 ms y se quita con `prefers-reduced-motion`.
- **Catch-All de SMS, primera parte: la pasarela y el agente (PRD #535, FR-12 a FR-20).** Con `rules/catch-all.md` en `enabled: true` y con instrucciones, un SMS de un número fuera del roster llega al agente con el extracto y la etiqueta `catch-all: rules/catch-all.md` dentro del primer corchete, donde el texto del SMS no puede escribir. Nunca dice `roster`. `paynani event show --body` lo muestra precedido de las instrucciones del dueño, pero sólo si llegó con el Catch-All activo y si sigue activo al leerlo: apagarlo corta el acceso a lo que ya llegó. Si el archivo está roto o está encendido sin instrucciones, el aviso dice `catch-all inválido` y no lleva el texto. Sin el archivo, o con `enabled: false`, todo queda como antes. `catch-all` queda reservado como id de reglas. El ledger guarda `{file, status}` (nunca el texto) para que el aviso de un SMS del Catch-All sin cerrar vuelva al iniciar la sesión.
- **Catch-All de SMS, segunda parte: el canal compartido y la API (PRD #535, FR-0a, FR-0b, FR-10, FR-P1 a FR-P5).** `catchall.get` y `catchall.save` en el mismo servicio que el roster y las reglas, para la web, PaynaniApp y la API. Guardar valida igual que las reglas (32 KB como máximo), rechaza activarlo sin instrucciones y un `etag` viejo, lo anota en `roster_changes.jsonl` y le manda un correo al dueño que dice desde dónde se cambió (PaynaniWeb, el teléfono o el token de la API). Ni el log ni el correo llevan las instrucciones. No se guarda si un contacto del roster ya usa `catch-all` como nombre de reglas, y las reglas de un contacto no pueden escribir `rules/default.md` ni `rules/catch-all.md`. En la API, `GetCatchAll` usa el permiso `read` y `SaveCatchAll` un permiso nuevo, `catchall.write`, que no forma parte de `roster.write`: ningún token existente lo recibe, y «API Tokens» explica qué permite. En `GetSmsThread`, un SMS que llegó con el Catch-All activo lleva `catch_all: true`. `api_agents.md` y `PAYNANI_API.md` documentan las dos acciones, el permiso y la marca. Un cambio de reglas hecho por la API ahora dice `API token <prefijo>` en `updated_by` y en el correo, en vez de `phone api:…`.
- **Catch-All de SMS: la regla para los agentes (PRD #535, FR-21, FR-22).** `AGENTS.md` y el bloque que `scripts/openclaw_rules.py` escribe en el `AGENTS.md` de OpenClaw explican la etiqueta `catch-all: rules/catch-all.md`. Un SMS que la trae no es trabajo del roster: el agente lee con `event show --body` las instrucciones del dueño y el texto, sigue sólo esas instrucciones y nunca le contesta al número. Con `catch-all inválido`, le avisa al dueño que el archivo está roto. `SMS_GATEWAY.md` §6 describe el aviso. En OpenClaw, el plan de actualización ya pide volver a correr `python3 scripts/openclaw_rules.py --install`. En Hermes, un SMS del Catch-All sigue yendo por la ruta `notify`, que se lo entrega al humano sin pasar por el agente.
- **Catch-All de SMS en PaynaniWeb (PRD #535, FR-1 a FR-8).** «Mensajes» tiene un botón «Catch-All» junto a «Bajas de la API». Abre `/messages/catch-all`, con la casilla «Activar Catch-All», las instrucciones para el agente, la advertencia de los códigos de verificación y quién lo cambió por última vez. Guarda con `catchall.save`, igual que PaynaniApp y la API. Para activarlo o cambiar las instrucciones con él activo pide la contraseña de la web, con el mismo bloqueo de intentos que la entrada; para apagarlo no. No guarda activo sin instrucciones ni más de 32 KB, y dice cuándo alguien más lo cambió mientras se editaba. Textos en los cinco idiomas.

Lo hizo Metis, con la revisión de Ximena; el menú lo hizo Iris, con la revisión de
Metis, Ximena y Andy. Sin requisitos nuevos. Con PaynaniApp 0.10.0, que agrega la
pantalla del Catch-All; PaynaniApp 0.9.0 sigue funcionando, sólo que sin esa
pantalla.

### Si actualizas desde 0.16.2

```bash
git fetch --tags --force origin
git pull --ff-only origin main
git describe --tags          # tiene que decir v0.17.0
python3 scripts/upgrade_plan.py --from v0.16.2     # y haz lo que imprima
```

El plan reinicia todos los servicios de paynani, porque cambia `VERSION`, y dice que
el hook de sesión cambió: la siguiente sesión lo toma, y ahí se vuelve a armar la
vigilancia del correo. `scripts/healthcheck.py` y `scripts/paynani doctor` tienen
que salir bien, y `version_drift` tiene que decir `ok`.

- **OpenClaw:** el plan pide `python3 scripts/openclaw_rules.py --install`. Córrelo:
  es lo que le enseña al agente qué hacer con un SMS del Catch-All.
- **Hermes:** un SMS del Catch-All sigue yendo por la ruta `notify`, al humano, sin
  pasar por el agente.
- **No hace falta activar nada.** Sin `rules/catch-all.md`, ningún SMS de fuera del
  roster le llega al agente con su texto, igual que antes. Activarlo lo decide el
  dueño, desde «Mensajes → Catch-All» en PaynaniWeb.
- **Tokens de la API:** ningún token existente recibe `catchall.write`. Si un
  sistema tuyo va a cambiar el Catch-All, hace falta un token nuevo con ese permiso.
- **PaynaniApp 0.10.0** (opcional): la pantalla «Catch-All» aparece en «Mensajes»
  cuando el teléfono está emparejado con una pasarela 0.17.0. Se instala encima,
  como siempre (INSTALL.md, sección del teléfono).

### Si actualizas desde 0.16.1 o anterior

Un solo salto desde la versión que tienes instalada. Cambia `v0.16.1` por tu versión
(la que dice `scripts/version.sh` antes de actualizar):

```bash
git fetch --tags --force origin
git pull --ff-only origin main
git describe --tags          # tiene que decir v0.17.0
python3 scripts/upgrade_plan.py --from v0.16.1     # y haz lo que imprima
```

Después, lo mismo que arriba para OpenClaw y PaynaniApp, y lo que pidan las
secciones «Si actualizas» de las versiones que te saltaste (por ejemplo, la nota de
`CODEX_HOME` de 0.16.2).

## 0.16.2 (2026-10-25)

**Dos arreglos que salieron al actualizar a 0.16.1: el `--apply` de `upgrade_plan.py`
en macOS y una prueba que escribía en el `hooks.json` real de Codex.** Ximena (macOS)
y Lisa (con `CODEX_HOME` definido) se detuvieron en esos dos puntos; los dos hosts ya
quedaron bien en 0.16.1.

- **En macOS, `upgrade_plan.py --apply` ya reinicia bien los LaunchAgents.** Le pasaba a `launchctl kickstart` el patrón (`com.paynani.idle.*`, `com.paynani.sms*`, `com.paynani.web*`) en vez de los nombres, y se detenía con exit 113 después de reiniciar el listener (Ximena, al actualizar a 0.16.1). Ahora busca en `launchctl list` los LaunchAgents que coinciden y reinicia cada uno; si no hay ninguno cargado, no hace nada, igual que en Linux. Los pasos impresos para macOS también son comandos en vez de un comentario.
- **`test_bootstrap_user.py` ya no escribe en el `hooks.json` real de Codex.** La prueba cambiaba `HOME` a una carpeta temporal pero dejaba `CODEX_HOME`, que manda sobre `HOME`. En un host con `CODEX_HOME` definido, la prueba escribía los hooks de paynani en el `hooks.json` real de Codex y fallaban dos pruebas de #474/#483, lo que detuvo el `--apply` de Lisa a 0.16.1 en `test_all.sh`. Ahora la prueba quita `CODEX_HOME` mientras corre y lo restaura al terminar.

Lo hizo Metis, con la revisión de Ximena, que probó #531 en su Mac. Sin requisitos
nuevos. Con PaynaniApp 0.9.0.

### Si actualizas desde 0.16.1

```bash
git fetch --tags --force origin
git pull --ff-only origin main
git describe --tags          # tiene que decir v0.16.2
python3 scripts/upgrade_plan.py --from v0.16.1     # y haz lo que imprima
```

Corre `upgrade_plan.py` después del `git pull`, como arriba: así el plan ya es el
corregido. El plan reinicia todos los servicios de paynani, porque cambia `VERSION`.
`scripts/healthcheck.py` y `scripts/paynani doctor` tienen que salir bien, y
`version_drift` tiene que decir `ok`.

Si `CODEX_HOME` está definido en tu host y corriste `scripts/test_all.sh` (o un
`--apply` con cambios locales) con 0.16.1 o anterior, revisa si apareció un
`$CODEX_HOME/hooks.json` que no tenías: lo pudo crear la prueba. No lo borres sin
avisar; muévelo a un lado.

### Si actualizas desde 0.16.0 o anterior

Un solo salto desde la versión que tienes instalada. Cambia `v0.16.0` por tu versión
(la que dice `scripts/version.sh` antes de actualizar):

```bash
git fetch --tags --force origin
git pull --ff-only origin main
git describe --tags          # tiene que decir v0.16.2
python3 scripts/upgrade_plan.py --from v0.16.0     # y haz lo que imprima
```

Si venías de 0.15.1 o anterior, después sigue los pasos 1–3 de «Si actualizas desde
0.15.1 o anterior» de 0.16.1 (PaynaniApp 0.9.0, `sms devices`, healthcheck y doctor).

## 0.16.1 (2026-10-24)

**Un token de la API revocado o vencido ya no deja al agente sin contestar.** Es
lo que encontró la prueba de la API (A9, #501) después de 0.16.0, en el PR #529.

- (PRD #491 FR-11.) Las respuestas de un número al que le escribió un token revocado o vencido seguían llegando marcadas «respuesta a la API: <token>, el agente no contesta» durante 7 días, aunque ese token ya no podía leerlas. Ahora su conversación deja de contar: el SMS llega sin marca y el agente lo atiende con sus reglas. Un STOP sigue dando de baja el número, pero sin la confirmación de ese token.

Lo hizo Metis, con la revisión de Ximena. Sin requisitos nuevos. Con PaynaniApp 0.9.0.

### Si actualizas desde 0.16.0

```bash
git fetch --tags --force origin
git pull --ff-only origin main
git describe --tags          # tiene que decir v0.16.1
python3 scripts/upgrade_plan.py --from v0.16.0     # y haz lo que imprima
```

El plan reinicia todos los servicios de paynani, porque cambia `VERSION`: el
listener, los listeners por cuenta, el dispatcher, la pasarela SMS y PaynaniWeb.
`scripts/healthcheck.py` y `scripts/paynani doctor` tienen que salir bien, y
`version_drift` tiene que decir `ok`.

### Si actualizas desde 0.15.1 o anterior

Un solo salto desde la versión que tienes instalada; `upgrade_plan.py` calcula
juntos los cambios de todas las versiones intermedias. Cambia `v0.15.1` por tu
versión (la que dice `scripts/version.sh` antes de actualizar):

```bash
git fetch --tags --force origin
git pull --ff-only origin main
git describe --tags          # tiene que decir v0.16.1
python3 scripts/upgrade_plan.py --from v0.15.1     # y haz lo que imprima
```

Después:

1. Actualiza PaynaniApp en el teléfono a la **0.9.0** (`INSTALL.md` §5.2). Abre
   la app una vez para que se vuelva a conectar.
2. Corre `scripts/paynani sms devices`: `app_version` tiene que decir `0.9.0`.
3. `scripts/healthcheck.py` y `scripts/paynani doctor` tienen que salir bien, y
   `version_drift` tiene que decir `ok`.

Los comandos de actualización de la sección 0.16.0 no hacen falta: los de arriba ya
cubren los dos saltos. Lo que 0.16.0 cuenta de la API y de la web sigue valiendo.

## 0.16.0 (2026-10-24)

**El dueño envía SMS desde PaynaniWeb, y otros agentes o programas usan paynani por
una API con tokens.** Son los dos features de los PRD #489 y #491.

- **SMS desde «Mensajes».** Hay «Nuevo SMS» y un cuadro para responder en cada
  conversación, con estados que se actualizan solos y el aviso de teléfono
  desconectado. Un número fuera del roster pide la contraseña de la web, y una
  casilla pausa al agente.
- **La API.** `POST /api/agent` con un API Token que el dueño crea en la nueva
  pantalla «API Tokens». Lee correo, SMS, roster y reglas, edita el roster,
  agrega cuentas y envía SMS con idempotencia y topes por token. Las respuestas
  quedan marcadas para su token, y STOP, BAJA, ALTO o CANCELAR dan de baja el
  número. La guía para el agente está en `/api/agents.md` y la del dueño en
  `PAYNANI_API.md`.

Los dos necesitan **PaynaniApp 0.9.0**, que se publica el mismo día. Con una app
anterior todo lo demás sigue igual, pero la web y la API no envían: la web pide
actualizar la app y la API responde `app_outdated`.

Lo hicieron Metis y Ocelotl, con la revisión de Ximena; Iris revisó y probó la
parte de PaynaniApp. La prueba de punta a punta fue con un Galaxy S21+, John y
Julian (#510, #501). Sin requisitos nuevos: sólo biblioteca estándar de Python
3.10 o mayor.

### Si actualizas desde 0.15.1

```bash
git fetch --tags --force origin
git pull --ff-only origin main
git describe --tags          # tiene que decir v0.16.0
python3 scripts/upgrade_plan.py --from v0.15.1     # y haz lo que imprima
```

El plan reinicia la pasarela SMS y PaynaniWeb. Después:

1. Actualiza PaynaniApp en el teléfono a la **0.9.0** (`INSTALL.md` §5.2). Abre
   la app una vez para que se vuelva a conectar.
2. Corre `scripts/paynani sms devices`: `app_version` tiene que decir `0.9.0`.
   Con eso, «Mensajes» muestra «Nuevo SMS».
3. `scripts/healthcheck.py` y `scripts/paynani doctor` tienen que salir bien, y
   `version_drift` tiene que decir `ok`.

No hay que configurar nada para que la API exista, y sin tokens no la puede usar
nadie. Si quieres que otro agente la use, sigue «Dar acceso a un agente» en
`PAYNANI_API.md`. Para cambiar la pausa o el tope de la web, ve las claves nuevas
`PAYNANI_WEB_AGENT_PAUSE_MIN` y `PAYNANI_WEB_SMS_PER_HOUR` en `INSTALL.md`; son
opcionales.

### Si actualizas desde 0.15.0 o anterior

Un solo salto desde la versión que tienes instalada; `upgrade_plan.py` calcula
juntos los cambios de todas las versiones intermedias. Cambia `v0.15.0` por tu
versión (la que dice `scripts/version.sh` antes de actualizar), y después sigue
los pasos 1 a 3 de arriba y lo que pidan las versiones intermedias:

```bash
git fetch --tags --force origin
git pull --ff-only origin main
git describe --tags          # tiene que decir v0.16.0
python3 scripts/upgrade_plan.py --from v0.15.0     # y haz lo que imprima
```

### Los cambios

- **La pantalla «API Tokens» de PaynaniWeb** (A2 #494 del PRD #491). Lista los tokens con búsqueda y filtros Activos, Vencidos y Revocados. «Crear token» pide nombre, vencimiento (5 minutos, 1 hora, 1 día, 7 días, 30 días, una fecha o «no vence»), permisos, topes de SMS y la contraseña de la web. El token se ve una sola vez, con un botón para copiarlo y un mensaje listo para el agente con la dirección de `/api/agents.md`. El detalle muestra el uso del día, deja activar «El agente local contesta las respuestas» (`agent_replies`) y revocar; las dos cosas piden la contraseña.
- **Bitácora de seguridad, alertas, `GetTokenInfo` y `GetUsage`** (A7 #499 del PRD #491). `state/api_security.jsonl` (permisos 600, 90 días) registra fallos de autenticación, tokens revocados o vencidos que se usaron, topes, bajas y altas, permisos negados y errores internos, con hora, `request_id`, prefijo del token y dirección; nunca el token ni el texto de un SMS. El dueño recibe un correo después de diez fallos de autenticación seguidos desde una dirección, y una vez por token cuando llega a su tope de SMS en 24 horas. `GetTokenInfo` y `GetUsage` funcionan con cualquier permiso; `GetUsage` cuenta llamadas y SMS en ventanas móviles de un minuto, una hora y un día.
- **El aviso de la pausa dice desde dónde contestó el dueño** (T7 #510 del PRD #489). `paynani sms send` y `paynani sms thread` decían «the owner replied from PaynaniApp» aunque el SMS hubiera salido de PaynaniWeb. Ahora dicen PaynaniWeb cuando el último SMS del dueño a ese número tiene `origin: web`. Lo encontró la prueba de punta a punta con el Galaxy S21+.
- **La guía de la API** (A8 #500 del PRD #491, FR-22). PaynaniWeb sirve `/api/agents.md` sin usuario, sesión ni token: la guía en inglés para el agente, con cada acción y sus parámetros, ejemplos de `curl`, permisos, errores, topes, bajas y el límite de Android de unos 30 SMS cada 30 minutos por app. `PAYNANI_API.md` dice lo mismo en español para el dueño: cómo dar y quitar acceso, qué hace cada permiso, los SMS de la API, las respuestas y bajas, y la seguridad. `test_api_docs.py` falla si una acción o un código de error de la API no está en las dos guías.
- **Documentación del envío de SMS desde PaynaniWeb** (T6 #509 del PRD #489). `PAYNANI_WEB.md` explica «Nuevo SMS», el cuadro de responder, la contraseña fuera del roster, la pausa, el tope, los estados y el teléfono desconectado. `AGENTS.md` dice cómo tomar una línea `Tú (PaynaniWeb) →`. `INSTALL.md` agrega `PAYNANI_WEB_AGENT_PAUSE_MIN` y `PAYNANI_WEB_SMS_PER_HOUR` a las claves de `sms.env`. En `SMS_GATEWAY.md`, `rejected` incluye `invalid_number`.
- **Respuestas a la API y bajas** (A5 #497 del PRD #491). Un SMS de un número al que la API le envió un SMS en los últimos 7 días queda marcado como respuesta a ese token (`api_reply` en el evento). Sólo cuenta una orden que el teléfono envió (`sent` o `delivered`), y los 7 días corren desde el envío; una orden en cola, fallida, rechazada o vencida no hace conversación. La línea del agente dice `respuesta a la API: <token>` y, si el token no tiene `agent_replies: true`, `el agente no contesta`. `ListSmsReplies` (permiso `read`) devuelve a cada token sólo sus respuestas desde `since`, de hace 7 días como mucho. Un SMS que dice sólo STOP, BAJA, ALTO o CANCELAR, sin importar mayúsculas ni acentos, da de baja el número para la API; START o ALTA lo da de alta. La pasarela confirma una sola vez, en el idioma de la palabra, con una orden `a_` del token que le escribió. La lista está en `state/sms/optout.json` y se ve y se edita en «Mensajes → Bajas de la API».
- **La API envía SMS** (A4 #496 del PRD #491). `SendSms` (permiso `sms.send`) crea una orden `a_` con la función compartida, a cualquier número en E.164 o con la región del teléfono, y con `idempotency_key` obligatoria. La misma llave con el mismo número y texto devuelve la orden ya creada (`duplicate: true`); con otro contenido responde `idempotency_conflict`. Antes de enviar revisa la baja (`opted_out`) y la pausa del agente (`human_replied` con `until`). Aplica los topes del token, 30 por hora y 200 por día si no se cambiaron, y al pasarlos responde `quota_exceeded` con `retry_at`. Sin teléfono emparejado responde `no_phone`, y con una app sin `accepts_api_out`, `app_outdated`. Con el teléfono desconectado, la respuesta lo dice. `GetSmsStatus` devuelve el estado y la historia de una orden, sólo al token que la creó. `outgoing.queue()` suma `per_day`, `token_id` e `idempotency_key`, y la llave se revisa bajo el mismo candado que el tope.
- **La API de PaynaniWeb lee correo, SMS, roster y reglas, y agrega o quita cuentas** (A3 #495 del PRD #491). `POST /api/agent` atiende `ListAccounts`, `ListMail`, `GetMailThread`, `ListSmsConversations`, `GetSmsThread`, `ListRoster`, `SaveRosterContact`, `DeleteRosterContact`, `GetRules`, `SaveRules`, `GetDefaultRules`, `SaveDefaultRules`, `AddAccount` y `RemoveAccount`. Cada acción pide un permiso del token (`read`, `roster.write` o `accounts.write`); sin él responde `forbidden` y dice cuál falta. El roster y las reglas pasan por el mismo servicio que la web y PaynaniApp. Perfil y contraseña de la web no están en la API.
- **La conversación muestra el estado de lo enviado desde PaynaniWeb y se actualiza sola** (T4 #507 del PRD #489). Cada SMS de la web dice En cola, Aceptado, Enviado, Entregado, Falló (con el código), Rechazado (con la razón) o Vencido. `assets/sms.js` pregunta a `GET /messages/estados?n=` cada 5 segundos y recarga si llegó un mensaje nuevo, salvo que haya texto a medio escribir. Con el teléfono desconectado, la página lo dice: la orden queda en cola y a los 15 minutos sin salir aparece como Vencido, aunque la pasarela sólo la marca cuando el teléfono vuelve.
- **La base de la API de PaynaniWeb autentica API Tokens** (A1 #493 del PRD #491). Guarda sólo el SHA-256 y un prefijo de cada token en `web/api_tokens.json` con permisos 600. `POST /api/agent` acepta Bearer o `api_token` en el cuerpo, rechaza credenciales en la URL, distingue tokens inválidos, revocados y vencidos, bloquea una dirección tras diez fallos en quince minutos y limita cada token a 60 llamadas por minuto. Cada error devuelve JSON y `request_id`; las acciones llegan en tareas posteriores.
- **Cerrar otra sesión de Codex ya no desactiva la entrega en vivo** (#486). `SessionEnd` borra `state/codex.session` únicamente cuando su `session_id` coincide con el que sigue registrado; `SessionStart` y `SessionEnd` toman el mismo candado para evitar una carrera entre sesiones. Un `codex queue` que responde «No active session found» conserva el registro y deja el evento en el spool para reintentar. `state/codex.delivery.json` registra la última alta, baja, baja ignorada y error de cola con su sesión y motivo.
- **PaynaniWeb envía SMS** (T3 #506 del PRD #489). «Mensajes» tiene «Nuevo SMS» y un cuadro para responder al pie de cada conversación. El número se escribe o se elige del roster, y se normaliza con la región del teléfono emparejado. Un número fuera del roster pide la contraseña de la web, con el mismo bloqueo de intentos que la entrada. El texto acepta hasta 1,000 caracteres y muestra un contador de caracteres y partes. La casilla «Pausar al agente por X minutos» toma X de `PAYNANI_WEB_AGENT_PAUSE_MIN` en `sms.env` (30 por omisión). El tope es de 30 envíos por hora, configurable con `PAYNANI_WEB_SMS_PER_HOUR`. El conteo y la escritura de la orden van bajo un candado (`state/sms/queue.lock`), así que dos envíos al mismo tiempo no rebasan el tope. Sin teléfono emparejado, o con una PaynaniApp anterior a la 0.9.0, la web lo dice y no envía.
- **La pasarela manda las órdenes del dueño y de la API** cuando la app las acepta (T2 #505 del PRD #489). La app lo anuncia en su saludo con `accepts_owner_out` y `accepts_api_out`, y la pasarela lo guarda en `device.json`. Una orden del dueño enviada se registra como SMS del dueño: va a `human.jsonl`, escribe el evento `sms.human_sent` con `origin: web` y pausa al agente si la casilla iba marcada. `paynani sms thread` muestra las del dueño en cola, vencidas o enviadas, con `via: web`. Una orden de un origen que la app no acepta no se manda y vence a su hora.
- **Una sola función crea las órdenes de SMS** (`paynani_lib/sms/outgoing.py`, T1 #504 del PRD #489). La usan `paynani sms send` y, después, PaynaniWeb (#490) y la API (#492). El id de la orden dice quién la creó: `o_` el agente, `w_` el dueño desde la web y `a_` la API. La pasarela sigue mandando sólo las del agente hasta T2 #505. `paynani sms send` se comporta igual que antes.

## 0.15.1 (2026-10-23)

**Con Codex, `bootstrap.sh` ya dice Ready; y el workflow `release-assets` adjunta
`bootstrap.sh` y `bootstrap.sh.sha256` a cada release.** Es lo que encontró la prueba de campo de Codex (BOOT-11, #476, con
Ocelotl) más el workflow de #475. Con Codex, una instalación nueva no decía Ready
porque contaba como bloqueo las filas de `doctor` que esperan la primera sesión y
el primer correo (#481). Ahora el bootstrap y la documentación piden aprobar los
hooks en `/hooks` y abrir una sesión nueva de Codex, y el paso 0 de `AGENTS.md`
pide ofrecer el script aunque el humano haya pedido el formulario.

Lo hizo Metis, con la revisión de Ximena. Sin requisitos nuevos: solo biblioteca
estándar de Python 3.10 o mayor. Con PaynaniApp 0.8.1.

### Si actualizas desde 0.15.0

```bash
git fetch --tags --force origin
git pull --ff-only origin main
git describe --tags          # tiene que decir v0.15.1
python3 scripts/upgrade_plan.py --from v0.15.0     # y haz lo que imprima
```

`scripts/healthcheck.py` y `scripts/paynani doctor` tienen que salir bien, y
`version_drift` tiene que decir `ok`. Con Codex, si `registered_session` dice
`unknown`, aprueba los hooks de paynani en Codex con `/hooks` y abre una sesión
nueva.

### Si actualizas desde 0.14.0 o anterior

Un solo salto desde la versión que tienes instalada; `upgrade_plan.py` calcula
juntos los cambios de todas las versiones intermedias. Cambia `v0.14.0` por tu
versión (la que dice `scripts/version.sh` antes de actualizar):

```bash
git fetch --tags --force origin
git pull --ff-only origin main
git describe --tags          # tiene que decir v0.15.1
python3 scripts/upgrade_plan.py --from v0.14.0     # y haz lo que imprima
```

No corras los comandos de pull, describe ni plan de las secciones de versiones
anteriores: ya no aplican, porque el pull te deja en v0.15.1. De ellas solo quedan
los pasos manuales que tocan a tu instalación:

- **Desde 0.14.0 o anterior (lo trajo la 0.15.0):** corre `scripts/paynani doctor` y
  **mira la fila `harness_step`**. Si dice `blocked`, a tu instalación le falta el
  paso de tu harness y el correo no te llega a la sesión: corre el comando que
  imprime en `next` (por ejemplo `python3 scripts/openclaw_rules.py --install`). Si tu
  harness no te deja escribir ese archivo, pídele a tu humano que lo corra en su
  terminal. Hermes y OpenCode no tienen esa fila (OpenCode sigue con
  `plugin_installed`).
- **Desde 0.13.1 o anterior (lo trajo la 0.14.0):** si tienes la pasarela SMS, crea
  el usuario de PaynaniWeb, como dice «Si actualizas desde 0.13.1» de la 0.14.0
  (`scripts/paynani web user add …`).
- **Desde versiones más viejas:** revisa en cada sección «Si actualizas desde …»
  hasta la 0.14.0 los pasos que no son pull, describe ni plan.
- **Con Codex:** si `registered_session` dice `unknown`, aprueba los hooks de
  paynani en `/hooks` y abre una sesión nueva.

`scripts/healthcheck.py` y `scripts/paynani doctor` tienen que salir bien, y
`version_drift` tiene que decir `ok`.

### Los cambios

- **Lo que encontró BOOT-11 en Codex** (#481, prueba de campo de Ocelotl, #476).
  - **`bootstrap.sh` ya dice Ready con Codex.** En una instalación nueva,
    `registered_session` sale `unknown` hasta que una sesión corre el hook
    `SessionStart`, y `last_queue_attempt` y `last_queue_result` hasta que llega el
    primer correo. El bootstrap las contaba como bloqueo: con Codex nunca decía Ready.
    Ahora las tres pasan como pendientes, solo en `unknown` y solo con Codex. El
    mensaje final pide abrir una sesión solo si `registered_session` falta, como
    `session_watch_state` en Claude Code (Ximena, revisión de #483).
  - **Aprobar los hooks en `/hooks` y abrir una sesión nueva.** Codex se salta los
    hooks nuevos de `~/.codex/hooks.json` hasta que alguien los aprueba, y una sesión
    que ya estaba abierta no corre el `SessionStart` que se perdió. Lo dicen el mensaje
    final del bootstrap (cuando esa corrida escribió los hooks o no hay sesión
    registrada), `AGENTS.md`, `INSTALL.md` §6 y la fila `registered_session` de
    `doctor`.
  - **El paso 0 de `AGENTS.md` pide ofrecer el script aunque el humano haya pedido el
    formulario.** El prompt del README pide el enlace del formulario, y Ocelotl lo leyó
    como una preferencia por el camino manual. Ahora el agente presenta las dos
    opciones y el humano elige.

- **Cada release lleva `bootstrap.sh` y su `.sha256` sin depender de nadie** (#475).
  La v0.14.0 salió sin ellos y `releases/latest/download/bootstrap.sh` dio 404 hasta
  que se subieron a mano. Ahora el workflow `release-assets` los adjunta al publicar
  una release: los saca de la etiqueta, los sube, los baja de la URL pública y corre
  `sha256sum -c`. Con `workflow_dispatch` se puede correr para una etiqueta anterior.
  `RELEASING.md` §5 dice cómo comprobarlo.

## 0.15.0 (2026-10-23)

**`bootstrap.sh` deja instalado lo que el agente no puede instalar** (#474). Ahora
también registra el paso de cada harness sin el cual el correo no llega a la
sesión: los hooks de Claude Code y de Codex, el plugin de OpenCode y la regla
permanente de OpenClaw. Lo muestra, pregunta y lo escribe con respaldo, y no dice
Ready sin él. `paynani doctor` tiene una fila nueva, `harness_step`, que lo
comprueba en cualquier instalación, y ya no marca Himalaya como `blocked` solo
porque el servidor de correo tarda (#478).

También: quitar una cuenta ya no falla cuando su listener tarda en detenerse
(#471); PaynaniWeb ya no pierde lo enviado al rotar `sent.log` (#470); y
`version.sh` ya no falla con «tmp: unbound variable» (#465).

Lo hicieron Iris y Metis, con la revisión de Ximena y Metis. Sin requisitos
nuevos: solo biblioteca estándar de Python 3.10 o mayor. Con PaynaniApp 0.8.1.

### Si actualizas desde 0.14.0

```bash
git fetch --tags --force origin
git pull --ff-only origin main
git describe --tags          # tiene que decir v0.15.0
python3 scripts/upgrade_plan.py --from v0.14.0     # y haz lo que imprima
```

Después corre `scripts/paynani doctor`. **Mira la fila nueva `harness_step`.** Si
dice `blocked`, a tu instalación le falta el paso de tu harness y el correo no te
llega a la sesión: corre el comando que imprime en `next` (por ejemplo
`python3 scripts/openclaw_rules.py --install`). Si tu harness no te deja escribir
ese archivo, pídele a tu humano que lo corra en su terminal. Hermes y OpenCode no
tienen esa fila (OpenCode sigue con `plugin_installed`).

`scripts/healthcheck.py` y `scripts/paynani doctor` tienen que salir bien, y
`version_drift` tiene que decir `ok`.

Si actualizas desde 0.13.1 o anterior, sigue primero «Si actualizas desde …» de
esas versiones y después esto, con `--from v0.14.0`.

### Los cambios

- **`paynani doctor` ya no marca Himalaya como `blocked` cuando el servidor tarda**
  (#478, lo encontró Metis). La prueba de la cuenta (`himalaya account check`) tenía
  un límite de 10 s, y con Gmail la misma prueba tardó 44.8, 12.6 y 2.4 s seguidos;
  pasado el límite salía `blocked` aunque la cuenta funcionara, y `bootstrap.sh` no
  decía Ready. Ahora el límite es de 30 s y, si se acaba, la fila queda `unknown`
  («the mail server may be slow»); `blocked` es solo cuando Himalaya contesta con
  error. `bootstrap.sh` ya probó la cuenta sin límite en su paso de Himalaya, así que
  ese `unknown` no le quita el Ready: lo dice al final.

- **`bootstrap.sh` registra el paso de cada harness y no dice Ready sin él** (#474,
  Q76 de Julian). El script existe para instalar lo que el agente no puede por el
  modo automático o el sandbox, pero dejaba al agente los hooks de Claude Code y de
  Codex, el plugin de OpenCode y la regla permanente de OpenClaw, que viven fuera de
  su espacio de trabajo. Ahora un paso nuevo, después de las reglas de permiso, los
  muestra, pide confirmación (o los aplica con `--yes`) y los registra con el script
  de cada harness, que mezcla y respalda. Si el dueño dice que no, si no hay terminal
  para confirmar o si el archivo no se puede leer, el run termina sin Ready y con el
  comando a correr. `paynani doctor` tiene una fila nueva, `harness_step`, que queda
  en `blocked` si faltan los hooks de Claude Code o Codex o la regla de OpenClaw
  (OpenCode ya tenía `plugin_installed`). Hermes no tiene paso. `AGENTS.md` también
  corrige la nota de Codex: con una sesión registrada, el correo la despierta con
  `codex queue`.

- **Quitar una cuenta ya no falla cuando su listener tarda en detenerse** (#471, lo
  encontró Metis en T11 de #435). En Linux, `account_service` corría
  `systemctl --user disable --now` con un límite de 20 s. Un listener en medio de IDLE
  tardó unos 25 s en detenerse, PaynaniWeb respondió 400 y la cuenta quedó a medias en
  `accounts.json`. Ahora `disable` va solo (es inmediato), el `stop` se pide con
  `--no-block` y se espera hasta 120 s a que la unidad termine de detenerse.
- **PaynaniWeb: lo enviado ya no desaparece cuando rota `sent.log`** (#470, lo
  encontró Metis en T11 de #435). `rotate_logs.py` rota `sent.log` cada semana y guarda
  copias (`sent.log.1` …), pero Email Accounts solo leía el `sent.log` actual: después
  de cada rotación desaparecían de la lista los enviados anteriores, y del hilo de un
  correo respondido la respuesta del agente. Ahora `thread.parse_sent_logs()` lee las
  copias rotadas, de la más vieja a la actual, y después `sent.log`, sin repetir un
  Message-ID.

- **`version.sh --plan`/`--apply` ya no termina en «tmp: unbound variable» ni deja
  basura en `$TMPDIR`** (#465, lo encontró Ares). La limpieza del árbol del planner
  que se saca de la etiqueta destino era `trap 'rm -rf "$tmp"' EXIT`, con `tmp`
  local a `run_planner()`. Si el trap corría cuando `tmp` ya no estaba (una
  función que ya regresó, o un bash que suelta los locales antes, como el de
  macOS), `set -u` lo convertía en un error. Ahora la ruta va expandida en el trap
  al armarlo. Además, cuando ese árbol no se puede extraer y se usa el planner
  instalado, que corre con `exec` (y `exec` no corre el trap), la carpeta se borra
  antes, en lugar de quedarse en `$TMPDIR`.

- **PaynaniWeb: la hora de las listas, en la zona del navegador; «1 perdida» en
  singular** (notas de Metis en #464).
  - La lista de correos decía «2026-10-20 12:40 UTC» y Messages no decía zona,
    mientras que el hilo ya iba en la zona del navegador. Ahora las dos listas
    usan `when.py` y `time.js`, como el hilo, pero cortas, como la lista de Gmail:
    de hoy solo la hora; de antes, la fecha corta. Al pasar el cursor se ve la
    fecha completa con la zona.
  - Con una sola llamada perdida, Messages dice «1 perdida» («1 missed», «1
    manqué») en lugar de «1 perdidas».

- **`upgrade_plan.py` ya no dice «no service needs a restart» cuando sí hay
  reinicios** (#462, lo vio Metis). El aviso de «PaynaniWeb has no user yet»
  (`f771a73`) había quedado entre el `if` de los comandos y su `elif`, así que un
  plan con reinicios y sin ese aviso imprimía las dos cosas, por ejemplo
  `--from v0.13.1 --to main`. Solo cambia el texto; `--apply` hacía lo correcto.

- **PaynaniWeb: Messages con la misma tabla que Email Accounts** (pedido de Julian).
  La lista de conversaciones SMS usa ahora todo el ancho, con la cabecera gris
  (Contacto, Último mensaje, Fecha, Mensajes) y una flecha por fila. En el celular
  se apila sin cabecera, igual que la de correos. Las columnas de fecha y estado
  de las dos listas tienen ancho fijo, para que una celda más ancha (las llamadas
  perdidas, que ahora van debajo del contador) no corra las demás.

## 0.14.0 (2026-10-21)

**PaynaniWeb: el dueño administra paynani desde el navegador** (PRD #434, umbrella
#435). Una aplicación web, en la misma dirección del túnel de la pasarela, con:
- **Email Accounts:** un webmail con lo recibido y lo enviado de cada cuenta. Al
  abrir un correo se lee todo su hilo como en Gmail (PRD #455, umbrella #456).
- **Messages:** las conversaciones SMS.
- **Roster:** las mismas altas, cambios, bajas y reglas que en PaynaniApp.
- **Profile:** la contraseña.

También:
- `send.sh` guarda copia de lo enviado en Enviados, salvo en Gmail (#449).
- `upgrade_plan --apply` ya no se queda esperando a un listener que nadie
  reinició (#432, #450, #452, #453).

Todo lo hicieron Iris y Metis. Sin requisitos nuevos: solo biblioteca estándar de
Python 3.10 o mayor. Con PaynaniApp 0.8.1.

### Si actualizas desde 0.13.1

```bash
git fetch --tags --force origin
git pull --ff-only origin main
git describe --tags          # tiene que decir v0.14.0
python3 scripts/upgrade_plan.py --from v0.13.1     # y haz lo que imprima
```

El plan pide `scripts/install.sh --upgrade`, que en un host con la pasarela SMS
instala y enciende `paynani-web.service` (en macOS, `com.paynani.web`), y reiniciar
la pasarela, el listener y el dispatcher. Con `--apply` lo hace todo, con el
`upgrade_plan.py` de esta versión, que ya no se cuelga esperando al listener.

Después, si tienes la pasarela, crea el usuario de PaynaniWeb en la computadora del
agente. Pide la contraseña dos veces:

```bash
scripts/paynani web user add --email you@example.com --name "Your Name"
```

y abre la dirección de tu túnel en el navegador. `PAYNANI_WEB.md` explica el resto.
`scripts/healthcheck.py` y `scripts/paynani doctor` tienen que salir bien, y
`version_drift` tiene que decir `ok`.

Si actualizas desde 0.13.0 o 0.12.0, sigue primero «Si actualizas desde …» de esas
versiones y después esto, con `--from v0.13.1`.

### Los cambios

- **PaynaniWeb: sin hueco antes de «•••» en los correos de Gmail** (T5 de #456, lo
  encontró Metis). Gmail manda el cuerpo con `\r\n`, y `quote.split()` dejaba
  cada línea visible con un `\r` al final. Ahora normaliza `\r\n` y `\r` a `\n`
  antes de partir el cuerpo.

- **PaynaniWeb: la hora de cada mensaje, en la zona de quien mira** (T4 del paraguas
  #456; PRD #455, 4.4; Q50 = A).
  - **`assets/time.js`**, un script chico como `lang.js`, reescribe cada
    `<time datetime>` del hilo con `Intl` en la zona del navegador. Si es de hoy,
    la hora y entre paréntesis hace cuánto («12:25 PM (9 minutes ago)»); si es de
    antes, la fecha corta y la hora (con el año si es de otro). En `title` va la
    fecha completa con la zona. Lo de «hace …» se actualiza cada minuto.
  - **Si el script no corre**, queda lo que escribe el servidor (`web/when.py`):
    la misma forma, en la zona del host y con el formato de cada idioma, como
    «12:25 p. m. (hace 9 minutos)» en es-MX, «12:25 PM» en en-US y 24 h en
    es-ES, fr-FR y pt-BR.
  - Se sirve desde `/assets/` con `defer`, así que la CSP no cambia. La hora
    sale de la cabecera `Date` de cada mensaje, como en Gmail, y si falta, de la
    hora del ledger o de `sent.log`.

- **PaynaniWeb: un correo abierto se lee como un hilo de Gmail** (T3 del paraguas
  #456; PRD #455, 4.1, 4.2 y 4.6 a 4.9). La página de un correo, recibido o
  enviado, es ahora una sola lista:
  - el asunto una vez, sin «Re:»;
  - todos los mensajes del hilo, completos y una vez cada uno, del más viejo al
    más nuevo, con el mismo formato (avatar con iniciales, nombre, `<dirección>`,
    «para mí» o «para Ana» y Cc, la hora y el cuerpo), sin fondos ni barras de
    color;
  - el abierto con un borde suave. Cada enlace de la lista lleva `#m-<id>`, así
    que la página baja hasta él sin JavaScript;
  - el texto citado detrás de «•••» (`<details>`, T2);
  - el estado y la marca del roster de cada recibido, chicos, junto a la hora;
  - con más de 10 mensajes, los dos primeros y los tres últimos completos y el
    resto en «N mensajes más», salvo el abierto.

  Se quitan «Conversación», «N correos de esta cuenta…», «Solo se muestra…»,
  «este correo» y el sobre grande de arriba. Todo el hilo se lee con
  `thread.load()` (T1), con una sola conexión. Un mensaje que no se pudo leer dice
  por qué dentro de su lugar: un enviado sin copia, como nota; un recibido, como
  aviso. Abrir un recibido que no se pudo leer sigue dando 502. Las cadenas nuevas
  van en los cinco idiomas, y en el celular la cabecera de cada mensaje pasa a dos
  líneas. La hora va en la zona del host hasta T4.

- **PaynaniWeb: todo el hilo de un correo con una sola conexión** (T1 del paraguas
  #456; PRD #455, 4.3). `web/thread.py` suma `load(env, conversación)`, que lee
  cada mensaje del hilo:
  - los recibidos de su buzón, con un `SELECT` de solo lectura y un solo
    `UID FETCH … (BODY.PEEK[])` por buzón, verificados como `mail.fetch()` (la
    misma `UIDVALIDITY`, el `From` y el `Message-ID` del sobre);
  - los enviados de Enviados, por su `Message-ID`.

  Todo va por una sola conexión de la cuenta. Nada queda leído ni se mueve, y
  nada se guarda. Un mensaje que no se puede leer trae su razón (`MailError`: de
  otra cuenta, sin UID, otro `UIDVALIDITY`, ya no está, otro remitente, otro
  Message-ID, buzón que no existe, sin copia en Enviados, sin carpeta de
  Enviados), y el resto sale igual. Si el servidor se cae a mitad, lo leído se
  queda. `mail.fetch()` se parte en `verify()` y `message_dict()` para que las dos
  vías usen la misma verificación. La página lo usa desde T3. Las pruebas están
  en `scripts/test_web_thread_data.py`.

- **PaynaniWeb: el texto citado de un correo, aparte** (T2 del paraguas #456; PRD
  #455, 4.5). `web/quote.py` parte un cuerpo en lo que se ve y lo que se pliega
  detrás de «•••»:
  - la atribución («On … wrote:», «El … escribió:», «Le … a écrit :», «Em …
    escreveu:», «Am … schrieb:»), aunque Gmail la parta en dos o tres líneas,
    seguida de líneas con `>`;
  - las líneas con `>` del final;
  - la cabecera de Outlook (From/Sent/To/Subject o De/Enviado/Para/Asunto, con la
    raya o «-----Original Message-----»), de ahí al final.

  `mail.html_to_text()` pone `> ` en lo que viene dentro de `<blockquote>` o del
  `<div class="gmail_quote">`, así que la cita de la parte HTML se pliega igual.
  La firma (`-- ` y lo que sigue) y las respuestas intercaladas se quedan a la
  vista. Un reenvío también: la cabecera después de «---------- Forwarded message
  ---------» (y sus versiones en es, fr, pt y de) o de «Begin forwarded message:»
  de Apple Mail no se pliega, porque es lo que el dueño le pasa al agente para que
  lo lea. La página lo usa desde T3. Las pruebas están en
  `scripts/test_web_quote.py`, con la forma exacta en que citan Gmail, Outlook y
  Apple Mail.

- **PaynaniWeb tiene favicon** (lo pidió Julian). Es `brand/favicon.svg`, la voluta
  reducida, servido en `/assets/favicon.svg` y también en `/favicon.ico`, que antes
  llevaba al login. Las páginas sin sesión, el login y el marco con sesión lo
  enlazan. La CSP suma `img-src 'self'` para que el navegador lo cargue; sigue sin
  permitir nada de otro origen.

- **El plan impreso dice lo mismo que `--apply`** (#451, nota de Metis). La lista de
  pasos de `upgrade_plan.py` decía siempre «verify disk and listener version, a new
  'resuming from uid N', and healthcheck». Ahora, si el plan no reinicia el
  listener, dice «verify disk version and healthcheck (the plan does not restart the
  listener)», igual que lo que hace `apply_plan()`.

- **`upgrade_plan --apply` y `paynani doctor` coinciden cuando el plan no reinicia
  el listener** (#451, lo encontró Metis al actualizar a `c2f2934`).
  - **`--apply`** esperaba siempre una línea nueva `resuming from uid N` del
    listener, que solo aparece cuando el listener se reinicia. Con un plan que solo
    reiniciaba PaynaniWeb, fallaba a los 40 s después de una actualización buena.
    Ahora la espera solo cuando el plan reinicia el listener; si no, verifica la
    versión en disco y corre `healthcheck.py`.
  - **`doctor`** marcaba `version_drift` en cuanto el commit del listener o del
    dispatcher no era el del disco, aunque entre los dos commits no cambiara nada
    de lo que cargan. Ahora pregunta a la misma tabla del plan
    (`upgrade_plan.restarts_between`) y solo marca drift si ese proceso tenía que
    reiniciarse. Si no lo puede saber (un commit que el clon no tiene, un archivo
    que la tabla no conoce, un error), marca drift como antes.
  - Pruebas en `test_upgrade_plan.py` (un plan que solo reinicia la web aplica sin
    esperar al listener; uno que lo reinicia sigue esperando; `restarts_between`
    con docs, web, dispatcher, un archivo desconocido y un commit ajeno) y en
    `test_healthcheck.py`.
  - Arreglo también varias comprobaciones de `test_send_sent_copy.py` (#449) y una
    de `test_upgrade_plan.py` (#450) que pasaban `check(desc, esperado, obtenido)`
    a un `check(desc, condición)`. Así pasaban siempre. Ahora comparan de verdad, y
    pasan.

- **`upgrade_plan.py --apply` acepta la salida 10 de `install.sh`** (#435, lo
  encontró Metis al actualizar a `e9cfada`). `install.sh --upgrade` (e
  `install_macos.py`) sale con 10, `EX_CHANGED`, cuando terminó bien y cambió algo,
  que es lo normal en una actualización. `--apply` lo tomaba como error y se detenía
  antes de los reinicios, así que la pasarela vieja seguía corriendo. Ahora 0 y 10
  son éxito y sigue con `daemon-reload` y los reinicios. Cualquier otra salida (1,
  64, 78…) lo sigue deteniendo antes de reiniciar nada. Las pruebas están en
  `test_upgrade_plan.py`, con un instalador falso que sale con 10, 1, 64 y 78.

- **`send.sh` guarda una copia de cada envío en Enviados** (#435, decisión de Julian
  en Q45 = A). `send.sh` manda por SMTP con `himalaya smtp send`, que no deja nada
  en el buzón (#117). Ahora, después de enviar, `scripts/paynani_lib/sent_copy.py`
  hace un `himalaya imap append` del mismo archivo que recibió SMTP (los mismos
  bytes y el mismo `Message-ID`, sin Bcc) a la carpeta marcada `\Sent` (RFC 6154),
  o a una de nombre conocido, con la marca `\Seen`. Los destinatarios no notan nada.
  - **Gmail** ya guarda su copia de lo que sale por su SMTP, así que no se copia
    (servidor IMAP `imap.gmail.com` o `imap.googlemail.com`).
  - **Nunca tumba un envío:** si la copia falla (sin carpeta de Enviados, el
    `APPEND` rechazado, más de 60 s), el correo ya salió, `send.sh` sale con 0 y
    avisa en stderr. No se crea ninguna carpeta.
  - **`sent.log`** anota el resultado en cada línea, antes de `message-id=`:
    `sent-copy=saved|skipped|failed`.
  - **`paynani doctor`** tiene una fila `sent_copy` por cuenta, más
    `account:<id>:sent_copy` para cada cuenta adicional. Da aviso si la cuenta de
    himalaya no tiene IMAP o si su último envío no pudo guardar la copia.
  - Pruebas en `scripts/test_send_sent_copy.py`, con un himalaya falso: una cuenta
    que no es Gmail (se guarda la copia), Gmail (no), sin IMAP (no), Enviados por
    su nombre, y un `APPEND` o un `LIST` que fallan (el envío sigue y queda
    `failed`).

- **PaynaniWeb: Email Accounts como un webmail** (T5 del paraguas #435, segunda
  parte; PRD #434 FR-13 y FR-14; decisión de Julian en Q44 = No). Una sola lista por
  cuenta con lo recibido (del ledger) y lo enviado (de `state/sent.log`, por su
  `account=`), mezclados por hora, el más reciente primero, de 50 en 50. Cada fila
  marca si entró (↙ «De:») o salió (↗ «Para:»). Un enviado se abre por su Message-ID
  (`/email/<cuenta>/ver?s=…`).

  Al abrir cualquiera, solo su conversación: el mismo asunto sin `Re:`/`Fw:` y la
  misma otra persona (el remitente, o un destinatario o Cc), dentro de la cuenta,
  en orden. El texto de los enviados se pide a IMAP en Enviados por su Message-ID
  (la carpeta `\Sent` o una de nombre conocido), en una sola conexión. Si no hay
  copia, la página lo dice con Para, Cc, Cco y la hora del registro. Nada se guarda.

  La lista usa todo el ancho de la pantalla, como Orders en el /dash (pedido de
  Julian): una cabecera gris con De / Para, Asunto, Fecha y Estado, y una flecha
  por fila. En el celular se apila sin cabecera. El hilo usa la clase
  `.conversacion`, para no chocar con `.hilo`, que es la conversación de SMS de
  Messages.

- **PaynaniWeb: seguridad, rendimiento y `PAYNANI_WEB.md`** (T10 del paraguas #435;
  PRD #434 §5 y NFR-1 a NFR-3). `scripts/test_web_security.py` recorre todas las
  pantallas, con sesión y sin ella, y comprueba en cada una:
  - la `Content-Security-Policy` sin nada de fuera, `X-Frame-Options: DENY`,
    `nosniff` y `no-store`;
  - que no se cargue ningún recurso de fuera, y que no haya atributos `style`,
    scripts en línea ni manejadores `on*=`;
  - que todo formulario `POST` con sesión lleve su token.

  También revisa que el log no traiga la contraseña, la consulta, el cuerpo de un
  correo ni el texto de un SMS. Para NFR-3, comprueba que 50 correos de un ledger
  de 6 000 avisos y 50 conversaciones de un diario de 3 000 SMS salgan en menos de
  2 segundos (en la CI tardan menos de 0.2 s). `PAYNANI_WEB.md` explica dónde corre,
  el primer uso, cómo se entra, las pantallas, qué guarda y qué no, la seguridad y
  los problemas comunes, y está enlazado desde el README y sus cuatro traducciones.
  La página de inicio deja de decir que las pantallas «todavía no están».

- **PaynaniWeb: agregar y quitar cuentas de correo** (T6 del paraguas #435; PRD #434
  FR-16, con las reglas de Q23). El desplegable de Cuentas de correo tiene
  «+ Agregar cuenta», y cada cuenta adicional tiene «Quitar esta cuenta»; la del
  agente no. Las dos acciones piden de nuevo la contraseña de PaynaniWeb, con el
  bloqueo de la entrada. Agregar prueba el acceso IMAP y, si se dio un servidor de
  salida, SMTP, antes de escribir nada, y muestra los pasos de la prueba si el
  servidor no acepta. Escribe con lo mismo que `paynani account add`: la contraseña
  del correo va al `.env`, y además se escriben `accounts.json`, el roster de la
  plantilla y la cuenta de himalaya, y arranca su servicio. La contraseña del
  correo nunca vuelve en la página, ni cuando hay un error. Quitar es lo mismo que
  `paynani account remove`: detiene el servicio (si no se detiene, no cambia
  nada), la saca de `accounts.json`, del `.env` y de himalaya, y guarda su roster
  en `rosters/removed/`. El buzón y el historial no se tocan. Las dos le mandan un
  correo al dueño, sin la contraseña. Para eso, `accounts_cli` separa lo que hace
  `account add` y `account remove` de lo que pregunta en la terminal
  (`prepare_add`, `commit_add`, `find_for_remove`, `remove_account`). La CLI dice y
  hace lo mismo que antes.

- **PaynaniWeb: Profile** (T9 del paraguas #435; PRD #434 FR-21). Está hecho como el
  Profile del `/dash` de Service Button: arriba el avatar con iniciales, el nombre,
  «Dueño» y el último ingreso, que ahora se guarda en `web/user.json` en cada
  entrada; abajo, solo **Datos personales** y **Contraseña de la cuenta** (Q25).
  Datos personales cambia el nombre y el correo, con el que se entra y al que
  llegan los avisos; cambiar el correo pide la contraseña actual. Contraseña de la
  cuenta pide la actual y la nueva dos veces, de al menos 12 caracteres y distinta
  de la actual. Al cambiarla se cierran las otras sesiones y la de quien la cambió
  sigue abierta. La contraseña actual pasa por el mismo bloqueo de 5 intentos de la
  entrada.

- **PaynaniWeb: el Roster y las instrucciones por contacto** (T8 del paraguas #435;
  PRD #434 FR-20 y FR-9). Es lo mismo que la pantalla «Roster» de PaynaniApp, con
  el mismo servicio de la pasarela (`sms/roster_api.RosterService`), así que el
  teléfono y el navegador validan igual: correo válido, teléfono en E.164 (la web
  lo normaliza antes, como la app, con `PAYNANI_SMS_DEFAULT_REGION`), sin
  duplicados, un correo o un teléfono por fila, y la fila del dueño que no se
  quita. Cada cambio usa el `etag` (un roster que cambió mientras se editaba da
  `409` y no escribe nada), deja la copia en `state/history/` y la línea en
  `state/roster_changes.jsonl` con `device_id` `web:<dirección>`, y le manda el
  correo al dueño. Ese correo dice ahora «desde PaynaniWeb (dirección …)» y aconseja
  cambiar la contraseña con `paynani web passwd`; los cambios desde el teléfono
  siguen diciendo lo de antes. Las pantallas son:
  - las cuentas como pestañas (la del agente y las de `accounts.json`, con cuántos
    contactos tiene cada una);
  - la lista, con la marca del dueño y de quién tiene instrucciones;
  - agregar y editar;
  - quitar, con su confirmación;
  - el editor de instrucciones de cada contacto y el de las reglas generales, con
    «Vista previa» de la regla efectiva antes de guardar.

  Las reglas que se guardan desde la web llevan `updated_by: PaynaniWeb
  <dirección>`. Todo `POST` lleva el token de la sesión.

- **PaynaniWeb: Messages, las conversaciones SMS** (T7 del paraguas #435; PRD #434
  FR-17 a FR-19). `/messages` muestra una fila por número, con lo más reciente
  primero y de 50 en 50 con «Ver más». Cada fila lleva el nombre del roster (o el
  que mandó el teléfono), lo último que pasó, cuántos elementos tiene la
  conversación y si hubo llamadas perdidas. Al abrir una se ve la conversación como
  `paynani sms thread`: lo que llegó, lo que mandó el agente con su estado
  (en cola, enviado, entregado, falló…) y lo que contestó el dueño desde
  PaynaniApp, en globos y en orden de hora real. Las llamadas van en medio, como
  «Llamada perdida de …» (FR-18) o «Llamada contestada de … · 2 min 5 s». Se ven
  los 50 más recientes, con «Ver anteriores», y la pausa del agente cuando el dueño
  contestó. Solo muestra (FR-19). La conversación sale de un módulo nuevo,
  `paynani_lib/sms/thread.py`, que ahora usa también `paynani sms thread`: una sola
  fuente para la terminal y la web. La salida de la CLI no cambia.

- **PaynaniWeb: Email Accounts, la lista y el correo abierto** (T5 del paraguas #435,
  primera parte; PRD #434 FR-13 a FR-15). Al elegir una cuenta del menú se ven sus
  correos, de 50 en 50 con «Ver más», el más reciente primero. La lista sale del
  ledger (`state/lifecycle.jsonl`), que guarda el sobre y no el cuerpo: remitente,
  asunto, la hora en UTC, el último estado del aviso (recibido, atendido,
  respondido, cerrado…) y la marca «roster» si el remitente está en el roster de
  esa cuenta. Al abrir uno, el correo se pide a IMAP en ese momento, con el login de
  su cuenta (nunca el del agente para otra), y no se guarda. Se verifica como en
  `event show`: el mismo buzón y `UIDVALIDITY`, el UID exacto, y que `From` y
  `Message-ID` coincidan con el sobre. Si algo no coincide o el servidor no
  responde, la página lo dice (`502`) y no muestra el cuerpo. No tiene la barrera
  del roster, que es del agente: aquí lee el dueño (#435, Q-T5-2). El cuerpo se
  muestra como texto. Del HTML queda solo el texto, sin scripts, estilos ni
  imágenes, y los enlaces quedan como texto con su dirección entre paréntesis. Los
  adjuntos se nombran y no se abren. Nada en estas pantallas cambia un estado ni
  contesta (FR-15), y el cuerpo no se escribe en ningún log. Las respuestas del
  agente en el hilo llegan con la segunda parte.

- **PaynaniWeb: el menú lateral y el encabezado de PDSL-201** (T4 del paraguas #435;
  PRD #434 FR-10 y FR-12). Con sesión, cada página va en el marco del mockup: el menú
  oscuro con el logotipo claro y el nombre del dueño; el encabezado en grana con el
  ícono y el título; y el panel. *Administración* tiene **Cuentas de correo**, un
  desplegable abierto con una entrada por cuenta (la del agente, del `.env`, y las de
  `accounts.json` en su orden, con la apagada marcada), **Mensajes** y **Roster**.
  *Herramientas* tiene **Cerrar sesión**. Las iniciales arriba a la derecha abren el
  menú del avatar, con el correo, **Perfil** y **Cerrar sesión**. En el celular, por
  debajo de 900 px, el menú lateral se vuelve un menú desplegable arriba. Los dos
  menús son `<details>`, sin script. Lo que la v1 deja fuera (AI Assistant,
  Settings, Sessions, el buscador, el chat flotante) no se dibuja. Un
  `accounts.json` que no se lee no tumba la página: queda la cuenta del agente y el
  menú lo dice. Las pantallas de cada opción llegan en T5 a T9.

- **PaynaniWeb: entrar, el bloqueo y la sesión** (T3 del paraguas #435; PRD #434 FR-5
  a FR-9). Con el usuario creado, toda ruta pide sesión y lleva a `/login`, la
  pantalla de PDSL-100: la tarjeta con correo y contraseña a la izquierda y el lema a
  la derecha, sin «Sign up», Google ni teléfono. El correo no distingue mayúsculas,
  el mensaje de error no dice si falló el correo o la contraseña, y un correo
  equivocado corre `scrypt` igual, para que tarde lo mismo. **5 fallos en 15
  minutos** desde una dirección la bloquean **15 minutos** (`429`), y mientras está
  bloqueada ni la contraseña buena entra. La dirección es el último valor de
  `X-Forwarded-For`, el que pone el túnel; los anteriores los escribe el cliente y no
  cuentan. **La sesión** es un id al azar en una cookie `HttpOnly`, `Secure` y
  `SameSite=Strict`. Vence tras **8 horas** sin uso y vive en memoria, así que
  reiniciar PaynaniWeb cierra todas; cambiar la contraseña (`paynani web passwd`)
  también las cierra. Cada entrada abre una sesión nueva. **Cerrar sesión** es un
  `POST` con el token de la sesión. Todo `POST` tiene que traer `Origin` (o
  `Referer`) de la misma dirección (`403` si no), y `next` solo lleva a rutas de la
  misma web. **La primera entrada desde una dirección nueva** le manda un correo al
  dueño por `send.sh`, en el idioma de la página, con la hora, la dirección y el
  navegador, y le dice cómo cambiar la contraseña (FR-9). Las direcciones vistas van
  en `web/known_ips.json`. Si el correo no sale, se entra igual y queda una línea en
  el log, sin el cuerpo. Un cuerpo de más de 64 KB es `413`.

- **PaynaniWeb se instala con la pasarela SMS** (T2 del paraguas #435, segunda
  parte; PRD #434 FR-4). Solo se llega a ella por la pasarela (FR-1), así que va
  donde va la pasarela (#435, Q-T2-1): `install.sh --with-sms` instala y enciende
  `paynani-web.service` junto a `paynani-sms.service`, y en macOS
  `install_macos.py --with-sms` hace lo mismo con el LaunchAgent `com.paynani.web`.
  Un `--upgrade` de un host que ya es dueño de la pasarela la agrega, y
  `--uninstall` la detiene y la quita. Un host sin pasarela no la ve. La unidad
  reinicia la web si se cae, salvo con salida 2 (una configuración que no se arregla
  sola: `--host` fuera de loopback, o `PAYNANI_WEB_PORT` igual al puerto de la
  pasarela), para no llenar el log. Registra en `state/web.log` y
  `state/web.err.log`, que rota `paynani-logrotate` como los demás. El instalador
  exige ahora que `web/` esté en `.gitignore`. `upgrade_plan` reinicia PaynaniWeb
  cuando cambia lo que carga al arrancar (`scripts/paynani_web.py`,
  `paynani_lib/web/`, `i18n`, `guard`, `brand`, los catálogos). Cuando cambia
  `paynani_lib/sms/config.py`, que leen las dos al arrancar, reinicia la pasarela y
  PaynaniWeb. Si un host con pasarela llega a una versión con PaynaniWeb y todavía
  no hay usuario, el plan lo dice al final, con el comando
  `scripts/paynani web user add`. `INSTALL.md`, `UPGRADE.md` y `UNINSTALL.md` (y su
  traducción) nombran la unidad nueva.

- **PaynaniWeb: el esqueleto de la aplicación** (T2 del paraguas #435, primera parte;
  PRD #434 FR-3, FR-4, FR-5 y FR-11). `scripts/paynani_web.py` escucha en
  `127.0.0.1:8771` (`PAYNANI_WEB_PORT`, el mismo que lee la pasarela), solo con la
  biblioteca estándar, un hilo por petición. Mientras no exista el usuario, toda ruta
  responde «crea tu usuario» con el comando para crearlo y nada más. El usuario es
  uno solo, el dueño, y se crea en el host con
  `scripts/paynani web user add --email … --name …`, que pide la contraseña dos veces
  (al menos 12 caracteres) o la lee de una línea con `--password-stdin`. Se guarda
  solo su hash `scrypt` en `web/user.json` (modo 600, carpeta 700, en `.gitignore`,
  fuera de `state/`); `PAYNANI_WEB_USER` lo cambia de lugar. `paynani web passwd` la
  cambia y `paynani web user show` muestra el nombre y el correo, sin el hash. Las
  páginas van en los cinco idiomas del onboarding (`?lang=`, luego una cookie, luego
  `Accept-Language`), con la marca en línea, `app.css`, la misma
  `Content-Security-Policy` y los mismos encabezados de seguridad que `server.py`, y
  nada de fuera. El log lleva el método y la ruta, nunca la consulta ni el cuerpo.
  `i18n` guarda ahora el idioma por hilo, para que dos peticiones a la vez no se lo
  cambien entre sí; para el onboarding y la CLI, que usan un hilo, no cambia nada. El
  servicio y el instalador son la segunda parte de T2.

- **La pasarela SMS le pasa a PaynaniWeb todo lo que no es de `/sms/`** (T1 del
  paraguas #435, PRD #434 FR-1 y FR-2). PaynaniWeb comparte así el dominio del túnel
  de ngrok sin tocar su configuración. Fuera de `/sms/`, la pasarela reenvía la
  petición tal cual a `127.0.0.1:8771` (`PAYNANI_WEB_PORT` en `sms.env`, o
  `--web-port`) y copia la respuesta. `/sms/pair`, `/sms/ws` y `/sms/health` no
  cambian, y el WebSocket del teléfono nunca pasa por la web. Si la web no acepta la
  conexión, responde `503` con una página corta que dice que los SMS siguen llegando;
  si la acepta y cierra sin responder, `502`. El log lo dice una vez cuando cae y otra
  cuando vuelve, no en cada petición. No pasan a la web los encabezados de un solo
  salto (`Connection`, `Keep-Alive`, `Upgrade`, `TE`…), y cada petición va con
  `Connection: close`, para que una conexión persistente del túnel no le mande a la
  web la siguiente petición aunque sea de `/sms/`. Los `X-Forwarded-*` del túnel
  pasan como llegan: decidir si se les cree es de la web (T3). Con un
  `PAYNANI_WEB_PORT` igual al puerto de la pasarela (alguien con
  `PAYNANI_SMS_PORT=8771`), el reenvío se apaga y lo dice en el log, en vez de
  reenviarse a sí misma. `--web-port 0` lo apaga a propósito: fuera de `/sms/`
  vuelve el `404` de antes.

- **`upgrade_plan.py` siempre pide reiniciar el listener y el dispatcher.** Antes
  suponía que `install.sh --upgrade` ya los había reiniciado cuando cambiaba una
  plantilla de `systemd/`, y decía `# install.sh --upgrade already restarted …`. Pero
  el instalador sólo reinicia si reescribió algo suyo, y la plantilla puede ser de una
  unidad que ese host no tiene. En 0.13.1 cambió sólo `paynani-sms.service`, y un host
  sin pasarela respondió «already converged» y siguió corriendo 0.13.0 hasta que
  `doctor` dio `warning` (#410). Ahora el plan pide siempre `daemon-reload` y el
  reinicio, y `--apply` los corre. Un reinicio de más cuesta un segundo.

## 0.13.1 (2026-10-20)

**El correo al dueño por cada cambio desde la pantalla «Roster» ya sale.** Desde
0.13.0, dos PRs de Andy (#427 y #430), más el de esta release. Sin requisitos nuevos. Con
PaynaniApp 0.7.1, que deja ver «Tipo» en pantallas chicas y pinta blancos los
diálogos (PaynaniApp #131 y #132).

- **El correo al dueño por los cambios desde PaynaniApp ya sale** (#410). La pasarela
  corre `send.sh` desde su servicio, y un servicio de usuario no ve el `PATH` de la
  sesión: con `himalaya` en `~/.local/bin`, como lo instala `INSTALL.md`, el correo de
  cada cambio en la pantalla «Roster» fallaba con `CalledProcessError` (lo encontró
  Andy al actualizar a 0.13.0).
  - `paynani-sms.service` lleva ahora `Environment=PATH=`: la carpeta de
    `command -v himalaya` (o `~/.local/bin/himalaya`, si el instalador corre sin ella)
    y luego el `PATH` del administrador de servicios.
  - En macOS, el `PATH` de los LaunchAgents también empieza con la carpeta de
    `himalaya`.
  - `healthcheck.py` advierte si la pasarela no encuentra `himalaya` con el `PATH` de
    su propio servicio, antes de que falle un aviso.
  - La línea va entre comillas (`Environment="PATH=…"`), para que una carpeta con
    espacios no rompa la unidad, y una unidad que no se puede leer no tumba
    `healthcheck.py` (#430).
  - Para actualizar basta `install.sh --upgrade` y reiniciar la pasarela; el plan de
    `scripts/upgrade_plan.py` ya lo pide porque cambia `systemd/`.

### Si actualizas desde 0.13.0

```bash
git fetch --tags --force origin
git pull --ff-only origin main
git describe --tags          # tiene que decir v0.13.1
python3 scripts/upgrade_plan.py --from v0.13.0     # y haz lo que imprima
systemctl --user restart paynani-sms.service       # si tienes la pasarela
```

Después, `grep PATH ~/.config/systemd/user/paynani-sms.service` tiene que mostrar la
carpeta de `himalaya`, y `scripts/healthcheck.py` no debe advertir que la pasarela no
encuentra `himalaya`. Haz un cambio de prueba desde «Roster» y comprueba que llega el
correo al dueño, con `"notified": true` en `state/roster_changes.jsonl`.

Si actualizas desde 0.12.0, sigue primero «Si actualizas desde 0.12.0» de 0.13.0 con
`--from v0.12.0`, y después corre el reinicio y las comprobaciones de arriba.

## 0.13.0 (2026-10-20)

**El roster y las instrucciones del agente, desde el teléfono.** Desde 0.12.0, 9 PRs
en paynani de Iris, Andy y Metis (#406, #407 y #419–#425), más el de esta release,
con PaynaniApp 0.7.0 (PaynaniApp #128, #129 y #130). El dueño ve y edita el roster
de cada cuenta en la pantalla «Roster» de PaynaniApp, y escribe instrucciones por
contacto y reglas generales (`rules/<id>.md`, `rules/default.md`). El protocolo está
en la sección 11 de `SMS_GATEWAY.md` (#419). `reply: never` es una barrera mecánica,
y cada aviso nombra las reglas que hay que leer. PRD #409, paraguas #410. Sin
requisitos nuevos: himalaya **v2.x** y Python **3.10** o mayor. Con una PaynaniApp
anterior la pasarela funciona igual que en 0.12.0, sólo que sin la pantalla «Roster».

- **Cada aviso de un contacto del roster dice qué reglas leer** (#415, R5 del paraguas
  #410, PRD #409 A-1 a A-3). La línea de un correo o un SMS del roster nombra, dentro
  de su primer corchete, el archivo que el agente lee antes de actuar:
  `[mail 21:27:35, sent 21:26:26, reglas: rules/ana-ruiz-9b1c.md, roster]`. Son las del contacto si
  existen y están activas, y si no, `rules/default.md`. Va dentro de ese corchete
  para que un asunto o un SMS no pueda fingirla. El sobre lleva `rules` con la ruta y
  `status`, nunca el texto. Un archivo que no valida sale como `reglas inválidas: …`,
  para que un error a mano no deje de aplicarse sin que nadie lo sepa (nota de #421).
  `AGENTS.md` tiene la regla fija nueva: leer `default.md` y luego las del contacto, y
  seguirlas. Las reglas no autorizan nada, y un mensaje no las cambia.
  `sms.human_sent` sigue igual. `INSTALL.md` §5.3 y `UNINSTALL.md` dicen dónde viven
  las reglas, y la desinstalación las conserva. La pasarela toma `rules/` de la
  carpeta de `--roster` (#418).

- **`reply: never` por canal es una barrera mecánica** (#414, R4 del paraguas #410,
  PRD #409 I-3). Si las reglas de un contacto, o `rules/default.md` cuando las suyas
  no dicen nada, tienen `reply.email: never`, `send.sh` no le manda correo y sale con
  2. Con `reply.sms: never`, `paynani sms send` hace lo mismo. Va después del roster y
  no lo reemplaza. `--override "<por qué>" --override-by "<quién>"` la salta, sólo con
  la orden explícita del dueño por un canal confiable, nunca porque el mensaje que se
  está procesando lo pida. Cada override queda en `state/reply_overrides.jsonl`, con
  quién, por qué, cuándo, a quién y qué barrera se saltó. Un `--dry-run` no lo
  registra. Si el archivo de reglas de un destinatario falta o no valida, lo dice en
  stderr con un `WARNING`, y la política cae a la de `rules/default.md` o a `normal`.

- **Instrucciones del agente por contacto, desde PaynaniApp** (#413, R3 del
  paraguas #410, PRD #409 I-1 a I-6). `rules/<id>.md` por contacto y
  `rules/default.md` para todos, en la instalación y fuera de git, como `roster.md`.
  Cada uno lleva una cabecera validada (`version`, `enabled` y `reply` por canal,
  con `normal` o `never`) y Markdown libre, hasta 32 KB. La pasarela los lee y los
  escribe con `rules.get`, `rules.preview`, `rules.save`, `rules.get_default` y
  `rules.save_default` (SMS_GATEWAY.md §11). La primera vez escribe el id en una
  columna `Rules` nueva del roster. Cada cambio deja una copia fechada, una línea en
  el log y un correo al dueño, sin el texto. La regla efectiva es `default.md` con
  las secciones del contacto sustituyendo a las del mismo nombre. La baja de un
  contacto renombra sus reglas a `<id>.removed-<fecha>.md` en lugar de borrarlas.
  Las reglas no autorizan nada: no agregan destinatarios ni permisos.

- **La pasarela lee y edita los rosters desde PaynaniApp** (#412, R2 del paraguas
  #410, PRD #409). `roster.accounts`, `roster.list`, `roster.save` y `roster.delete`
  (SMS_GATEWAY.md §11), sólo desde el teléfono emparejado. Cada cambio se valida
  (correo, E.164, sin duplicados y con un correo o un teléfono). Se hace en un solo
  paso con el bloqueo del roster y el `etag`, deja una copia fechada en
  `state/history/` y se escribe con el mismo mecanismo atómico de `paynani roster`.
  Queda una línea en `state/roster_changes.jsonl` y sale un correo al dueño con qué
  cambió y desde qué teléfono. Si ese correo no sale, el resultado queda en el log y
  `healthcheck.py` lo advierte durante 24 h. La fila del dueño no se borra. Una app
  anterior no manda estos mensajes y no cambia nada.
- **`paynani roster` ya no pisa un cambio hecho entretanto.** Su escritura toma el
  mismo bloqueo que la pantalla «Roster» (`state/locks/`) y comprueba que el roster
  sigue siendo el que leyó. Si cambió, no escribe y pide correrlo otra vez.

- `INSTALL.md` §5.2 muestra el certificado con el que se firma PaynaniApp hoy
  (`58f8e922…b53c4531`); el anterior (`5edb93e3…3f679c2f`) es el de la 0.3.0 y
  anteriores. Baja el APK de las releases de PaynaniApp, con la de paynani como
  copia, y dice qué hacer con un teléfono que tiene la app firmada con la llave
  anterior: desinstalar, instalar la nueva y emparejar con un código nuevo.

- **Pruebas.** `test_rules_notice.py` cubre el criterio 6 del PRD: un SMS que pide
  cambiar las reglas o el roster no cambia nada (#424). `test_sms_config.py` corre su
  `sms pair` de punta a punta sobre una copia del clon, así que ya no falla en una
  instalación con `sms.env` ni toca la de verdad (#425; lo encontró John en #418).
  `test_bootstrap.sh` crea su `$HOME` falso con 755 aunque el umask sea 002 (#407).

### Si actualizas desde 0.12.0

```bash
git fetch --tags --force origin
git pull --ff-only origin main
git describe --tags          # tiene que decir v0.13.0
python3 scripts/upgrade_plan.py --from v0.12.0     # y haz lo que imprima
```

El plan corre `scripts/install.sh --runtime <runtime> --upgrade` (el inventario
conserva `rules/`), recarga `systemd` y reinicia el listener, el dispatcher, las
cuentas adicionales (`paynani-idle@*`) y la pasarela SMS si la tienes. Después,
`scripts/paynani doctor | grep version_drift` tiene que dar `ok` en todas las líneas.

Si tienes el teléfono emparejado, haz un cambio de prueba desde la pantalla «Roster»
y comprueba que llega el correo al dueño. Ese correo sale con `send.sh` desde el
servicio de la pasarela. Si no llega, `scripts/healthcheck.py` lo advierte y
`state/roster_changes.jsonl` dice por qué.

No se crea ninguna regla al actualizar: sin `rules/`, paynani se comporta como en
0.12.0, y los avisos no cambian hasta que exista un archivo de reglas. Si tu agente
tiene reglas o excepciones escritas en otro lado, la migración es a mano y la
decide el dueño (criterio 7 de #418).

**Si un agente lee el tag `, roster]`** (la regla de OpenClaw, la memoria del agente):
la línea de un contacto con reglas es `[mail …, reglas: rules/<id>.md, roster]`, y
sigue cerrando con `, roster]`.

Si usas el teléfono: instala PaynaniApp 0.7.0 encima de la que tengas (comprueba el
SHA-256 y el certificado como en `INSTALL.md` §5.2). Sigue emparejado. Con la
pasarela en 0.13.0, el menú muestra «Roster».

## 0.12.0 (2026-10-19)

**Instalación de un solo comando, y la pasarela SMS sabe la batería del teléfono y
lo que contesta su dueño.** Desde 0.11.0, 33 PRs en paynani de Metis, Andy, Iris,
Balam y Ximena, más el de esta release. `bootstrap.sh` instala paynani con un solo
comando que el humano corre en su terminal (con `sudo` en Ubuntu y Debian, sin él
en macOS) y viene adjunto a esta release con su SHA-256. La pasarela recibe la batería (PaynaniApp 0.6.8) y los
SMS que el dueño manda desde «Mensajes», con la pausa del agente (PaynaniApp 0.6.9).
Sin requisitos nuevos: himalaya **v2.x** y Python **3.10** o mayor. Con una
PaynaniApp anterior la pasarela funciona igual que en 0.11.0.

- **`bootstrap.sh`, la instalación de un solo comando** (#351, #358, #352; cierran
  #341, #342 y #344; paraguas #349, PRD en #335). La parte root comprueba el sistema,
  instala sólo los paquetes que falten (`git python3 curl ca-certificates`) y
  himalaya v2.x como el usuario, activa `linger` y clona; luego pasa a
  `scripts/bootstrap_user.py`, que como el usuario elige el runtime, pide las
  credenciales del buzón en la terminal (no por la conversación del agente), configura
  la cuenta de himalaya, escribe el roster con el dueño, corre el instalador, agrega
  las reglas de permiso del harness en Claude Code y OpenClaw (`harness_rules.py`:
  sólo `scripts/paynani`, `scripts/send.sh` y `harness/session_watch.sh` del clon,
  por ruta absoluta; en Hermes, Codex y OpenCode imprime qué agregar a mano) y
  verifica la instalación. Si un paso falla, dice cuál y el comando para repetirlo; `--dry-run` imprime el plan sin
  cambiar nada y `--upgrade` actualiza una instalación existente. Documentado en
  `INSTALL.md` («Install with one command (sudo)», con «If it refuses»), README y
  `RELEASING.md` (#366, cierra #345).
- CI de punta a punta de `bootstrap.sh` en una VM Ubuntu 24.04 limpia, con un servidor
  de correo de prueba (`bootstrap-e2e`, #354, cierra #343). Todavía no es un check
  obligatorio.
- El paso del roster de `bootstrap_user.py` ya no corre las suites de prueba en la
  máquina del usuario; después de escribir, lee `roster.md` con el mismo lector del
  listener y sale con 1 si no reconoce al dueño. `paynani roster add` y `onboard`
  siguen corriéndolas (#364, cierra #361).
- `install.sh` ya no truena con `syntax error: operand expected` en una instalación
  limpia cuando rechaza la cadena de directorios: `owned_digests` se declara global y
  el instalador llega a imprimir la causa real (#360).
- `upgrade_plan.py` clasifica `bootstrap.sh`, `brand/` y `.env.example`, que antes lo
  hacían negarse con `not in the table`, y una prueba nueva recorre `git ls-files`
  para que ningún archivo vuelva a quedar sin regla (#353).
- `test_listener.py`: la prueba del rol `to` ya no falla cuando el reloj cambia de
  segundo entre las dos líneas que compara (#362).
- Documentación: `INSTALL.md` §5.1 explica por qué el túnel necesita una dirección que
  no cambie, cómo recuperar el teléfono si cambia y que el túnel tiene que seguir
  corriendo al cerrar la terminal (#370); §5.2 explica cómo cambiar de gateway con
  «Emparejar de nuevo» sin reinstalar la app (#359), cómo permitir PaynaniApp en segundo plano con
  DuraSpeed y otros ahorros de energía (#380) y los pasos de Samsung (#384), y avisa
  que un RCS que llega con su conversación abierta en Google Messages no genera
  `sms.unseen` (#374, #375). `AGENTS.md`, ante `sms.gateway.offline`, pide sugerir
  abrir Paynani en el teléfono (#387).
- `paynani sms thread` ordena por la hora real y la muestra en hora local. Los SMS
  recibidos traen la zona del teléfono y lo demás va en UTC, y ordenarlos como texto
  podía poner un recibido en otro lugar del mismo día (QA de PaynaniApp#111).
- La pasarela SMS recibe `sms.human`: los SMS que el dueño del teléfono manda desde
  «Mensajes» de PaynaniApp (PaynaniApp#111). Escribe `sms.human_sent` una vez por envío,
  con `sent` o `failed`, con «Tú → …» en la línea, el mensaje al que contestó
  (`in_reply_to`) y, si salió, hasta cuándo el agente no le escribe a ese número
  (`pause_until`, 30 min por omisión, lo configura el dueño en la app). Con un
  destinatario fuera del roster la línea no lleva el texto. `delivered` sólo va a
  `state/sms/human.jsonl`. Durante la pausa, `paynani sms send` a ese número sale con
  código 4 (`human_replied`) sin crear la orden; `--override-pause` la manda igual.
  `paynani sms thread <número>` muestra la conversación en orden: lo recibido, las
  órdenes del agente y lo que mandó el dueño. Las órdenes ya tomadas por el teléfono
  pasan de `outbox/` a `sent/` en lugar de borrarse. Con una app anterior nada cambia.
- La pasarela SMS sabe la batería del teléfono (PaynaniApp#109). La app manda
  `device.status` (porcentaje, si carga, tipo de conector, temperatura y la hora de la
  lectura) cuando cambia o cada 10 min, y el saludo trae la última lectura. Sin cargar,
  la pasarela escribe `sms.gateway.battery_low` al bajar de 25 % (`warn`) y de 10 %
  (`critical`), una vez cada uno por descarga, y `sms.gateway.battery_ok` al cargar o al
  volver a superar el aviso por 5 puntos. `battery_low` espera 5 min seguidos sin
  cargar, así un cable flojo no repite avisos. Los umbrales se cambian en `sms.env`
  (`PAYNANI_SMS_BATTERY_WARN_PCT`, `PAYNANI_SMS_BATTERY_CRITICAL_PCT`); uno inválido
  vuelve a 25 y 10 y queda en el log. Un dato que llegó hace más de 20 min no avisa, y
  una lectura con la hora más de 5 min en el futuro o de hace más de 30 días se
  rechaza. `sms.gateway.offline` incluye la última batería conocida, y
  `paynani status` y `healthcheck` muestran la batería, si carga y qué tan vieja es la
  lectura. Con una app anterior, la batería sale como desconocida y nada cambia.
- El paso 0 de `AGENTS.md` respeta la versión que pide el humano: descarga
  `bootstrap.sh` de `releases/download/<tag>/` y lo corre con `--ref <tag>`, en vez de
  instalar siempre la última release estable. También dice que el humano lo corre en su
  propia terminal (no con el `!` del harness, donde `sudo` no puede pedir la contraseña)
  y que en Claude Code con modo automático conviene más que el camino a mano (#397).
- `paynani onboard` muestra el enlace del formulario en cuanto el servidor arranca,
  aunque su salida vaya a un archivo o una tubería, como cuando un harness lo corre en
  segundo plano. Antes la salida quedaba en búfer y el enlace salía hasta que se
  guardaba el formulario (#396).
- `scripts/version.sh --plan` y `--apply` sin destino ya no eligen un tag de
  pre-release (como `v0.12.0-rc1`) como el más nuevo. `--apply` lo rechazaba y fallaba en
  todos los hosts mientras existiera ese tag (#394).
- `scripts/test_codex.py` ya no escribe en el estado real del clon. La prueba de la
  repetición al iniciar sesión de Codex dejaba 20 filas falsas (`imap:INBOX:42:*`,
  `presented`, `codex`) en `state/lifecycle.jsonl` y un `state/codex.delivery.json`
  cada vez que alguien corría la suite en una instalación (#392).
- `AGENTS.md` tiene un paso 0: antes del camino a mano, el agente le ofrece a su
  humano la instalación de un solo comando con `bootstrap.sh`, que el humano corre con
  `sudo` y que pide la contraseña sin que pase por la conversación. Si la release no
  trae `bootstrap.sh` (antes de la 0.12.0), usa el de `main`. Después de **Ready**
  quedan para el agente el paso del runtime del paso 4 y los pasos 7 a 9. Antes, el
  prompt del README llevaba al agente a `install.sh` y nunca al script (#389).
- La pasarela SMS guarda como `last_seen` la hora del último frame del teléfono, no la
  de su revisión periódica ni la del cierre. Antes, con el teléfono sin red,
  `sms.gateway.offline` llegaba 2 a 3 min tarde y decía como «último latido» una hora
  en que el teléfono ya no estaba (#385).
- Nuevo `scripts/paynani sms check`: la prueba guiada después de emparejar el
  teléfono. Revisa el servicio de la pasarela, que conteste en el equipo, que el
  túnel llegue a ella y que el teléfono esté en línea (último latido, versión de
  PaynaniApp y número de la SIM). Con `--to <número del roster>` manda un SMS de
  prueba y con `--wait-reply <s>` espera la respuesta en `events.jsonl`
  (INSTALL.md §5.2, paso 7; #350).
- El aviso `sms.gateway.offline` y la línea del teléfono en `paynani status`
  ahora sugieren abrir Paynani en el teléfono si no vuelve sola, porque el
  ahorro de energía del fabricante pudo haberla cerrado (#381).
- `upgrade_plan.py` ya no repite el `daemon-reload` ni el reinicio de
  `paynani-idle` y `paynani-dispatch` después de `install.sh --upgrade` cuando
  cambió una unidad de `systemd/`: ese caso el instalador ya los hizo, y el plan
  lo dice con `# install.sh --upgrade already restarted paynani-idle and
  paynani-dispatch`. Siguen en el plan las instancias `paynani-idle@*` y la
  pasarela SMS, que el instalador no reinicia. Si sólo cambió el instalador, el
  plan conserva el reinicio, porque `install.sh` reinicia únicamente cuando
  reescribió un archivo suyo (#302).
- En macOS, `scripts/install.sh` ahora escribe `install.manifest` con los
  LaunchAgents y `runtime.env`, igual que en Linux, con `install_manifest.py`.
  Antes el manifiesto no existía nunca en un Mac, y `upgrade_plan.py` se negaba
  a planear en cada release. **Si actualizas** un Mac que ya está instalado, corre
  una vez `scripts/install.sh --runtime <runtime> --upgrade`: crea el manifiesto
  y desde la siguiente release el plan funciona. `--uninstall` lo retira (#291).
- El bootstrap macOS conserva la ruta estable de Homebrew
  `/opt/homebrew/opt/python@3.N/bin/python3.N` para los LaunchAgents, en vez de
  resolverla a `Cellar/<versión>`, de modo que `brew upgrade` no deje servicios
  apuntando a una ruta borrada (#372).
- `bootstrap.sh` ahora tiene una ruta macOS de usuario: no usa `sudo` por
  omisión, nunca corre Homebrew como root, se detiene si falta Homebrew, resuelve
  Python 3.10+ para `install_macos.py` y conserva `--dry-run` como plan sin
  mutaciones (#347).
- `paynani sms pair` ahora aclara en la terminal que un código vencido no es un
  error, y que basta con volver a correr el comando para usar un código nuevo
  (#355).
- La pasarela SMS anuncia `server_version` en el `welcome`, para que PaynaniApp
  pueda mostrar en Estado la versión de paynani a la que está conectada (#367).

### Si actualizas desde 0.11.0

```bash
git fetch --tags --force origin
git pull --ff-only origin main
git describe --tags          # tiene que decir v0.12.0
python3 scripts/upgrade_plan.py --from v0.11.0     # y haz lo que imprima
```

El plan corre `scripts/install.sh --runtime <runtime> --upgrade`, recarga
`systemd` y reinicia el listener, el dispatcher, las cuentas adicionales
(`paynani-idle@*`) y la pasarela SMS si la tienes. `harness/session_start.py`
cambió, así que la siguiente sesión del agente arma la vigilancia de nuevo.
Después, `scripts/paynani doctor | grep version_drift` tiene que dar `ok` en todas
las líneas.

No hace falta `bootstrap.sh` para actualizar: es para instalaciones nuevas.

En macOS, corre una vez `scripts/install.sh --runtime <runtime> --upgrade` para
crear `install.manifest` (#291); desde ahí, `upgrade_plan.py` funciona también en
un Mac.

Si usas el teléfono: instala PaynaniApp 0.6.9 encima de la que tengas (comprueba el
SHA-256 y el certificado como en `INSTALL.md` §5.2). Sigue emparejado. Con la
pasarela ya en 0.12.0, Estado muestra la batería y «Mensajes» puede contestar SMS.

## 0.11.0 (2026-10-04)

**RCS: lo que la app no puede leer ya no se pierde en silencio, y PaynaniApp 0.3.0.**
Desde 0.10.0, 7 PRs en paynani (#328, #331, #333, #334, #337, #338, #339) de
Metis, Iris y Andy, más el de esta release, y 7 en PaynaniApp. Google Messages
entrega los mensajes RCS por datos, nunca como SMS, así que la app no los ve
(PRD en PaynaniApp#46). Esta versión hace tres cosas con eso: guía para
apagarlo, avisa cuando llega algo que la app no pudo leer, y deja de duplicar el
SMS que la app lee por sus dos rutas. Sin requisitos nuevos: himalaya **v2.x** y
Python **3.10** o mayor. El APK de PaynaniApp 0.3.0 va adjunto a esta release.

- **Aviso de un mensaje que PaynaniApp no pudo leer** (#333, cierra #332). La
  pasarela acepta `sms.unseen`: cuando Google Messages recibe un mensaje (casi
  siempre un RCS, a veces un MMS) y la app no ve el SMS correspondiente en 60 s,
  el agente recibe una línea fija, sin el texto ni el remitente:
  `[sms HH:MM:SS] Google Messages recibió un mensaje que PaynaniApp no pudo leer
  (posible RCS)`. El nombre que mostró la notificación queda limpio en el sobre
  (`paynani event show`) y nunca en la línea. `welcome` anuncia en `accepts` los
  tipos que acepta la pasarela, y la app sólo manda `sms.unseen` a una pasarela
  que lo anuncia. `SMS_GATEWAY.md` lo documenta, MMS y doble SIM incluidos (#339).
- **INSTALL.md §5.2**: instalar PaynaniApp en el teléfono y emparejarlo (#328, de
  Andy), y el paso nuevo «Turn off RCS chats» antes de emparejar (#334, de Andy).
- **README** menciona PaynaniApp, en el original y en las cuatro traducciones
  (#331, cierra #330).
- **`version.sh --plan` y `--apply` usan la tabla de la versión destino** (#337,
  de Iris, cierra #329). Una release que agrega un archivo agrega su regla en la
  misma release, y la tabla instalada lo daba por `unknown` y se negaba a aplicar;
  le pasó a Ares de 0.9.1 a 0.10.0. Vale **a partir de esta versión**: desde
  0.10.0 todavía corre la tabla de 0.10.0.
- **El plan reinicia también las cuentas adicionales** (#338, cierra #336).
  Cuando cambia un módulo compartido de `harness/`, `upgrade_plan.py` incluye las
  instancias `paynani-idle@<id>`. Antes, `doctor` se quedaba en `warning` en cada
  cuenta aunque se siguiera el plan al pie de la letra.

**PaynaniApp 0.3.0** (adjunto, firmado con el mismo certificado que la 0.2.0, así
que se instala encima sin desemparejar):
- El mismo SMS leído por el receptor y por el barrido con el texto un poco
  distinto da **un** evento, no dos (PaynaniApp#53, el caso del sufijo
  `*/=0QcMMQ`).
- **Estado** tiene la fila «Chats RCS» con la guía para apagarlos y la fila
  «Detector de RCS» para activar el acceso a notificaciones (PaynaniApp#56 y #58).
- El detector: con el acceso a notificaciones, una notificación de Google
  Messages sin SMS en 60 s manda `sms.unseen`. Nunca lee el texto de la
  notificación (PaynaniApp#58).
- El registro de eventos se actualiza mientras está abierto (PaynaniApp#57), y el
  barrido sólo cuenta lo que encoló nuevo (PaynaniApp#60).
- Manifiesto sin `hardwareAccelerated="false"` ni `largeHeap`, y el registro sin
  `AsyncTask` (PaynaniApp#49 y #50, de Iris).

### Si actualizas desde 0.10.0

```bash
git fetch --tags --force origin
git pull --ff-only origin main
git describe --tags          # tiene que decir v0.11.0
python3 scripts/upgrade_plan.py --from v0.10.0     # y haz lo que imprima
```

No hace falta el instalador. El plan pide reiniciar el listener, el dispatcher y
la pasarela SMS si la tienes. El plan que corre después del `git pull` ya es el de
0.11.0 y reinicia también las cuentas adicionales (#338). Si lo calculaste
**antes** del pull (por ejemplo con el `version.sh --plan` de 0.10.0), no las
incluye: reinicia sus instancias a mano.

```bash
systemctl --user list-units --all --plain --no-legend 'paynani-idle@*.service' | awk '{print $1}' | xargs -r systemctl --user restart
```

Después, `scripts/paynani doctor | grep version_drift` tiene que dar `ok` en
todas las líneas, las `account:<id>` incluidas.

Si usas el teléfono: instala `PaynaniApp-0.3.0.apk` encima de la 0.2.0 (comprueba
el SHA-256 y el certificado como en `INSTALL.md` §5.2). Sigue emparejado. Luego,
en Estado, toca «Chats RCS» y sigue la guía, y activa el detector.

En macOS, `upgrade_plan.py` todavía no puede hacer el plan (#291): el mismo
`git pull` y `launchctl kickstart -k` de `com.paynani.idle`, `com.paynani.dispatch`,
cada `com.paynani.idle.<id>` y `com.paynani.sms` si lo tienes.

## 0.10.0 (2026-10-02)

**SMS y llamadas: el agente recibe y contesta mensajes de texto con el número real
de un teléfono Android.** Desde 0.9.1, 12 PRs: #314 a #324 y #326, de Metis e
Iris, más el de esta release. Con un teléfono que corre PaynaniApp, emparejado con
esta máquina, los SMS y las llamadas de ese número llegan al agente igual que el
correo: una línea por evento, con la etiqueta `roster` cuando el número está en
`roster.md`. El agente contesta con `paynani sms send`. Todo es **opcional**: sin
teléfono emparejado no cambia nada, ni siquiera se abre un puerto. Sin requisitos
nuevos: himalaya **v2.x** y Python **3.10** o mayor, como en 0.9.1. El APK de la
app va adjunto a esta release.

- **El protocolo** (#314). `SMS_GATEWAY.md` describe cómo se empareja el
  teléfono, cómo habla con la pasarela por WebSocket, qué manda en cada caso
  (`sms.in`, `call.missed`, `call.answered`, `sms.status`) y qué recibe
  (`sms.out`). Cada mensaje tiene un `id` estable y la pasarela confirma con un
  `ack` sólo después de escribir el evento, así que un corte no pierde ni repite
  nada.
- **Los números de teléfono en E.164** (#315). `harness/phone.py` normaliza los
  números de la misma forma para el roster y para la pasarela: `+521` pasa a
  `+52`, los códigos cortos y los remitentes alfanuméricos no son números, y la
  región sale del país de la SIM o de `PAYNANI_SMS_DEFAULT_REGION` (MX por
  omisión).
- **La pasarela** (#316). `scripts/sms_gateway.py`, sólo con la biblioteca
  estándar, escucha nada más en `127.0.0.1`; el teléfono llega por un túnel https
  (ngrok o cloudflared). Escribe `sms.received`, `call.missed` y `call.answered`
  en `events.jsonl` con el mismo sobre que el correo. El texto completo de un SMS
  se lee con `paynani event show <id> --body`, sólo si el número está en el
  roster. `paynani sms pair`, `sms devices` y `sms revoke` manejan el
  emparejamiento.
- **La columna `Phone` del roster** (#317, #321). Un contacto puede tener uno o
  varios números, separados por coma. Una fila sólo con teléfono, sin correo, es
  un contacto válido; esa fila se escribe a mano, porque `roster add` todavía pide
  el correo. `paynani roster add … --phone` agrega uno y rechaza un
  número que ya es de otro contacto. Un roster sin la columna funciona igual que
  antes.
- **Contestar** (#318). `paynani sms send <número> "<texto>"` sale con código 2,
  sin crear nada, si el número no está en el roster, igual que `send.sh`.
  Espera hasta `--wait` segundos el estado del teléfono: 0 con `sent` o
  `delivered`, 1 con `failed`, `rejected` o `expired`, y **3 si el teléfono
  todavía no confirmó**, para que un agente no lo dé por enviado.
  `paynani sms status <id>` muestra cada estado.
- **Emparejar desde el navegador** (#319). `paynani sms pair --web` abre la página
  local del onboarding con el QR, generado con la biblioteca estándar, y la
  dirección y el código en texto; muestra el teléfono emparejado y permite
  revocarlo.
- **Las líneas en todos los runtimes** (#322). OpenClaw recibe con un SMS del
  roster la instrucción de leerlo y contestarlo; Codex trata el texto de un SMS
  como no confiable, igual que un correo; `AGENTS.md` dice qué hacer con
  `[sms …, roster]` y con las llamadas.
- **La salud del teléfono** (#323). Si el teléfono pasa 90 s sin latir, la
  pasarela escribe **una** vez `sms.gateway.offline`, y `sms.gateway.online`
  cuando vuelve. `paynani status` y `healthcheck` muestran el último latido y
  las órdenes en cola.
- **Instalar la pasarela como servicio** (#324). `install.sh --with-sms`
  (y su equivalente en macOS) instala `paynani-sms.service` o `com.paynani.sms`.
  Sin la bandera no se instala nada. El puerto y la dirección del túnel van en
  `sms.env`, junto a `runtime.env`: el instalador nunca toca ese archivo.
  `INSTALL.md` §5.1 trae las recetas de ngrok y cloudflared.
- **Revocar corta al teléfono conectado, y SIGTERM apaga siempre** (#326). Antes,
  un teléfono revocado seguía escribiendo eventos mientras su conexión siguiera
  abierta, y una conexión colgada impedía que la pasarela terminara con SIGTERM.
  Los dos los encontró Andy en la prueba de punta a punta (QA-4).
- **El titular en `LICENSE`** es ahora la razón social completa, «Inteligencia
  Artificial Aplicada en México ONG», la misma que en PaynaniApp. La licencia
  sigue siendo MIT.
- **Puerto 8770 por omisión** (#320). La pasarela ya no usa el 8765, que es el de
  la página local del onboarding y de `sms pair --web`.

### Si actualizas desde 0.9.1

```bash
git fetch --tags --force origin
git pull --ff-only origin main
git describe --tags          # tiene que decir v0.10.0
python3 scripts/upgrade_plan.py --from v0.9.1     # y haz lo que imprima
```

El plan pide **el instalador** (`scripts/install.sh --runtime <tu runtime>
--upgrade`), porque cambió, y reiniciar el listener y el dispatcher. Sin
`--with-sms` el instalador no agrega la pasarela ni cambia `runtime.env`. Si no
vas a usar SMS, con eso terminas.

Para usar SMS: corre el instalador con `--with-sms`, escribe `sms.env` con el
puerto y la dirección de tu túnel (`INSTALL.md` §5.1), agrega la columna `Phone`
a tu roster, instala la app en el teléfono y empareja con
`paynani sms pair --web`.

En macOS, `upgrade_plan.py` todavía no puede hacer el plan (#291): el mismo
`git pull`, `python3 scripts/install_macos.py --upgrade` y `launchctl kickstart -k`
de `com.paynani.idle`, `com.paynani.dispatch` y cada `com.paynani.idle.<id>`.

## 0.9.1 (2026-09-30)

**Correcciones pequeñas después de 0.9.0, y la documentación al día.** Desde
0.9.0, 3 PRs: #298, #300 y #303, más el de esta release, que además corrige
el plan de actualización. Sin requisitos
nuevos y sin instalador: himalaya **v2.x** y Python **3.10** o mayor, como en
0.9.0.

- **Rearmar el vigía antes de que expire el anterior ya no hace que `doctor`
  diga que nadie vigila** (#301). Si la misma sesión rearmaba con su propio vigía
  todavía vivo, el segundo vigía cedía, como debe, pero escribía `yielded` en el
  registro de la sesión y pisaba el `armed` del vigía que seguía entregando
  avisos: `session_watch_state` salía en `warning` sin que faltara nada. Ahora
  el dueño del lock anota su `session_id`, y un segundo arranque de esa misma
  sesión sale con 0, dice `this session is already watching; not arming a
  second.` y no toca el registro. Con otra sesión todo sigue igual (cede y
  registra `yielded`), y un lock de una versión anterior, sin `session_id`, se
  trata como antes.

- **`upgrade_plan.py --to <rama o commit>` ya no termina con un traceback**
  (#297). Con un destino que no fuera una etiqueta `vX.Y.Z` ni `origin/main`,
  `render()` armaba el bloque «automatic apply» y `_fetch_argv()` lanzaba
  `ApplyError`, aunque nadie hubiera pedido `--apply`. Ahora imprime el plan
  completo y, en lugar de los pasos, `refused: <destino> is neither a release
  tag nor origin/main, so --apply cannot pull it reproducibly`. `--apply` con
  ese destino se sigue negando con el mismo error, y la salida con una etiqueta
  o con `origin/main` no cambia. Lo encontró la revisión de la release 0.9.0.

- **Documentación al día con 0.8.1 y 0.9.0** (#299). Solo documentación; no
  cambia código.
  - `README.md` y sus cuatro traducciones mencionan ahora vigilar varias cuentas
    de correo, con una viñeta y una fila que llevan a `MULTI_ACCOUNT.md`. Ese
    documento sigue en español y las traducciones lo dicen.
  - `AGENTS.md`: la regla de las reconexiones estaba desactualizada desde 0.8.1.
    Ya no le pide al agente avisar tras tres intentos: el listener calla los
    cortes de menos de `PAYNANI_FAULT_GRACE_SECONDS` y manda él mismo sus tres
    avisos (corte largo, recuperación y ráfaga de cortes cortos), y el agente
    solo decide qué decirle a su humano de cada uno.
  - `UPGRADE.md`: al actualizar hay que reiniciar también las instancias de las
    cuentas adicionales, `paynani-idle@*` en Linux y `com.paynani.idle.<id>` en
    macOS, que seguían con el código viejo.
  - `DESIGN.md`: nueva sección, «Why several accounts share one journal», con el
    porqué del diseño de varias cuentas.

- **Una release que sólo cambia `VERSION` reinicia también el dispatcher.**
  `upgrade_plan.py` reiniciaba sólo el listener cuando cambiaba `VERSION`, pero
  el dispatcher también guarda qué versión cargó y `version_drift` compara los
  dos. Siguiendo el plan al pie de la letra, `doctor` quedaba en `warning`
  después de reiniciar. En 0.8.1 y 0.9.0 no se notó porque también cambió
  `dispatch.py`. Apareció al preparar esta release, cuyo único cambio para los
  servicios es `VERSION`.

### Si actualizas desde 0.9.0

```bash
git fetch --tags --force origin
git pull --ff-only origin main
git describe --tags          # tiene que decir v0.9.1
python3 scripts/upgrade_plan.py --from v0.9.0     # y haz lo que imprima
```

El plan pide reiniciar el listener, el dispatcher y las instancias
`paynani-idle@*` si tienes cuentas adicionales, para que todos carguen `VERSION`
0.9.1. **No hace falta el instalador.** Ojo: el `upgrade_plan.py` que corres es
el que acabas de traer, con el arreglo de abajo, así que el plan ya incluye el
dispatcher. Antes de reiniciar, `scripts/paynani doctor | grep version_drift`
tiene que dar `warning`; después, `ok`. En Claude Code, el arreglo de #301 lo
toma la siguiente sesión, al rearmar el vigía.

En macOS, `upgrade_plan.py` todavía no puede hacer el plan (#291): el mismo
`git pull`, y `launchctl kickstart -k` de `com.paynani.idle`,
`com.paynani.dispatch` y cada `com.paynani.idle.<id>`, con el `python3` de tus
LaunchAgents.

Si vienes de 0.8.x o antes, sigue primero «Si actualizas desde 0.8.1» (más
abajo): 0.9.0 sí pide el instalador.

## 0.9.0 (2026-09-30)

**Un agente puede vigilar hasta diez cuentas de correo además de la suya**
(#276): por ejemplo `contacto@`, `ventas@` y `soporte@` de una PYME, cada una
con su propio roster, su propio servicio y su propia firma, y todas entregando
en la misma sesión. La cuenta del agente no cambia y no hay nada que migrar:
sin `accounts.json`, paynani se comporta exactamente como 0.8.1. La guía
completa, con el caso PYME paso a paso, está en `MULTI_ACCOUNT.md`. Desde
0.8.1, 10 PRs: #285, #287, #288, #286, #289, #290, #292, #293, #294 y #295,
más el de esta release.

Sin requisitos nuevos: himalaya **v2.x** y Python **3.10** o mayor, como en
0.8.1. **Esta versión sí pide correr el instalador** (ver «Si actualizas»),
porque agrega una unidad de systemd nueva.

- **Varias cuentas, parte 1: `accounts.json`, `paynani account list` y
  `paynani account test`** (#276, #279). Base de la implementación del PRD de
  #276. Las cuentas adicionales (hasta 10 por agente) se describen en
  `accounts.json`, junto al `.env`. El JSON **nunca** guarda una contraseña:
  `password_env` nombra la clave del `.env` donde vive. El módulo nuevo
  `scripts/paynani_lib/accounts.py` valida el archivo entero y lo rechaza
  nombrando la cuenta y el campo, en vez de usarlo a medias. Define también el
  `event_id` de una cuenta adicional (`imap:<id>:<buzón>:<uidvalidity>:<uid>`).
  La cuenta principal conserva el formato de hoy, así que ningún ledger
  cambia. El roster de cada cuenta tiene que ser una ruta relativa dentro del
  directorio de `accounts.json`. `account list` muestra las cuentas sin secretos, y `account test <id>`
  prueba el login, cada buzón e IDLE con el mismo `connect()` que usa el
  listener. Sin `accounts.json`, nada cambia.

- **Varias cuentas, parte 2: `idle_listener.py --account <id>`** (#276, #280).
  El listener vigila una cuenta de `accounts.json` en lugar de la del `.env`.
  - Juzga la marca `roster` con **el roster de esa cuenta**: estar en el roster
    principal no da permiso en `ventas@`, ni al revés.
  - Guarda su estado en `state/accounts/<id>/idle.json`.
  - Escribe en el mismo journal que la cuenta principal, así que el dispatcher
    y el orden de entrega no cambian.
  - Cada aviso nombra la cuenta (`[mail 10:02:11, sent 10:01:50,
    ventas@dominio.com, roster] ...`), y cada evento lleva un `event_id`
    propio (`imap:ventas:INBOX:...`) y el campo `account_id`.
  - Las fallas del listener dicen de qué cuenta son (`[listener ventas] ...`),
    y la misma falla en dos cuentas son dos eventos, no uno.
  - Una cuenta desactivada, o con más de un buzón, se rechaza con un mensaje en
    vez de vigilarse a medias. Por ahora se vigila un buzón por cuenta.

  La cuenta principal no cambia en nada: sus eventos, sus avisos y sus fallas
  salen idénticos a los de antes.

- **Base de servicio por cuenta para varias cuentas** (#281). El instalador de
  Linux ahora instala la plantilla `paynani-idle@.service`; macOS expone la
  forma de LaunchAgent `com.paynani.idle.<id>`; y `account_service.py` concentra
  `enable(id)`, `disable(id)` y `state(id)` para systemd y launchd. La unidad
  instancia `idle_listener.py --account <id> --env <env>` y deja que el
  listener resuelva estado, roster y buzones desde `accounts.json`.
  `upgrade_plan.py` reinicia el listener principal y las instancias
  `paynani-idle@*` cuando cambia `idle_listener.py`, `roster.py` o `VERSION`.

- **Varias cuentas, parte 4: `paynani account add` y `paynani account remove`**
  (#276, #282). `add <id> --email … --imap-host …` **prueba el login IMAP antes
  de escribir nada**: si falla, sale con 1 y no deja ningún archivo cambiado.
  La contraseña se pide con `getpass`, en una terminal; nunca se acepta como
  argumento ni por una tubería. Con el login bueno escribe la contraseña en el
  `.env` como `PAYNANI_ACCOUNT_<ID>_PASSWORD` (sin tocar ninguna otra línea),
  la cuenta en `accounts.json` (modo 600), un `rosters/<id>.md` a partir de
  `roster.md.example` y la cuenta `paynani-<id>` en la configuración de
  himalaya, que lee la contraseña con `env_secret.py`. Si una escritura falla,
  las anteriores se deshacen. `remove <id>` pide confirmación (`--yes` la
  salta), detiene el servicio, quita la cuenta de esos cuatro sitios y mueve el
  roster a `rosters/removed/`; nunca lo borra ni sobrescribe uno anterior.
  El historial del journal y del ledger no se toca. Máximo 10 cuentas.
  Además, `paynani roster add` y `roster remove` aceptan `--roster
  rosters/<id>.md` para editar el roster de una cuenta; sólo se acepta el
  archivo que `accounts.json` da como roster de alguna cuenta, no una ruta
  cualquiera. Por ahora `add` acepta un solo `--mailbox`, porque el listener
  vigila un buzón por cuenta (#280). Sin `accounts.json`, nada cambia.

- **Varias cuentas, parte 5: `send.sh --account` y `paynani event show` por
  cuenta** (#276, #283). `send.sh --account <id>` envía desde una cuenta
  adicional: el remitente es el correo y el nombre de la cuenta, sale por la
  cuenta de himalaya `paynani-<id>` y **cada destinatario se juzga contra el
  roster de esa cuenta, no contra `roster.md`**. Quien está sólo en el roster
  principal sale con 2 y no se envía nada, y al revés se permite. Se rechazan
  con 2, sin enviar, una cuenta que no existe, una sin servidor SMTP, una sin
  roster o un `accounts.json` ilegible; un salto de línea en `from_name` no
  puede abrir otra cabecera. **La firma del agente no se agrega** a un correo
  de una cuenta adicional: `accounts.json` acepta un `signature_file` opcional
  por cuenta (ruta relativa dentro del directorio, con la misma regla que
  `roster`), que `send.sh --account` agrega; si no se puede leer, no envía.
  `--dry-run` dice qué cuenta, qué roster y qué firma usó, y `sent.log` anota
  `account=<id>`. Sin `--account`, `send.sh` queda igual, byte
  por byte. `paynani event show <event_id> [--body]` de un evento de una
  cuenta adicional abre IMAP con **el login de esa cuenta**, verifica al
  remitente contra **su roster** (el motivo de la autorización nombra ese
  archivo, `rosters/<id>.md`, y no `roster.md`) y muestra `account_id`; si la
  cuenta ya no está
  en `accounts.json`, no lee el cuerpo y no cae al login del agente. La cuenta
  principal no cambia. `AGENTS.md` dice que la respuesta a un aviso de una
  cuenta adicional sale con `--account`.

- **Varias cuentas: `doctor` y `healthcheck.py` por cuenta** (#276, #284, punto 1).
  - Cada cuenta de `accounts.json` tiene sus propias filas en `doctor`:
    `account:<id>:listener`, `:imap_telemetry`, `:version_drift` y `:roster`.
  - Una cuenta caída, atrasada o con el roster vacío sale en `warning` con su
    nombre y no cambia las filas de la cuenta principal.
  - Una cuenta desactivada es una sola fila `ok` que lo dice, y un
    `accounts.json` inválido es una sola fila `blocked`.
  - `healthcheck.py` muestra una línea por cuenta y avisa de cada una caída,
    pero su código de salida sigue dependiendo sólo de la cuenta principal.
  - Sin `accounts.json`, las dos salidas quedan idénticas a las de antes.

- **Retención para registros de cuentas adicionales** (#276, #284, punto 2).
  `paynani-logrotate.timer` ahora también aplica `PAYNANI_RETENTION_DAYS`
  (default: 90) al historial de cuentas adicionales: limpia del ledger los
  eventos viejos de esas cuentas y conserva el historial de la cuenta principal.
  El journal se compacta desde el dispatcher, no desde el timer, cuando todo el
  archivo ya fue entregado y el primer registro supera la retención.

- **`MULTI_ACCOUNT.md`: cómo vigilar varias cuentas de correo** (#276, #284).
  Explica `accounts.json`, `paynani account add|list|test|remove`,
  `paynani roster add --roster`, el servicio por cuenta y las filas de `doctor`,
  con el caso de una PYME (`contacto@`, `ventas@`, `soporte@`) paso a paso, la
  regla de quién puede dar instrucciones en cada cuenta y los límites de esta
  versión. También cubre leer el cuerpo de un aviso y contestar desde la cuenta
  con `send.sh --account`, con su firma propia (#283), y cuánto tiempo se guardan
  los registros de las cuentas adicionales (`PAYNANI_RETENTION_DAYS`, #294).

- **Rearmar el vigía justo cuando el anterior se retira ya no falla con «a
  watcher from a previous version»**. El vigía que se retira escribe `ended`
  en su registro como último paso de la limpieza y suelta el `flock` sólo al
  terminar. Un rearme que caía en ese hueco encontraba el lock todavía tomado
  y se negaba con un mensaje falso. Ahora espera hasta 2 s a que se libere; un
  vigía de una versión anterior, que no lo suelta, se sigue rechazando.
  Apareció como falla intermitente de CI en #285.

- **`PAYNANI_RETENTION_DAYS` con un valor que no es número ya no impide que
  arranque el dispatcher.** Se leía con `int()` al importar `dispatch.py`;
  ahora un valor ilegible usa los 90 días por omisión, igual que
  `rotate_logs.py`. Detalle de la revisión de #294.

### Si actualizas desde 0.8.1

En Linux:

```bash
git fetch --tags --force origin
git pull --ff-only origin main
git describe --tags          # tiene que decir v0.9.0
python3 scripts/upgrade_plan.py --from v0.8.1     # y haz lo que imprima
```

El plan pide `scripts/install.sh --runtime <tu runtime> --upgrade`, que
instala la plantilla nueva `paynani-idle@.service`, y después reiniciar el
listener y el dispatcher. **No te saltes el instalador**: sin él, la primera
cuenta que agregues con `paynani account add` no tiene unidad que arrancar.

**Antes de reiniciar**, `scripts/paynani doctor | grep version_drift` tiene que
dar `warning` (0.9.0 en disco y los servicios en 0.8.1). Un `ok` antes de
reiniciar es la falla que importa reportar. **Después** de reiniciar, y tras unos
15 segundos, `version_drift` e `imap_telemetry` tienen que estar en `ok`.

En macOS, `upgrade_plan.py` todavía no puede hacer el plan (#291: el
instalador de macOS no escribe `install.manifest`). Sigue `UPGRADE.md` a mano:
el mismo `git pull`, `scripts/install.sh --runtime <tu runtime> --upgrade`, y
reiniciar con `launchctl kickstart -k` los dos servicios.

Sin `accounts.json` no hace falta nada más. Para agregar cuentas, sigue
`MULTI_ACCOUNT.md`.

## 0.8.1 (2026-09-30)

**Un aviso del roster ya no se pierde al cerrarse la sesión, un corte de
IMAP que se recupera solo ya no avisa, y `doctor` vuelve a decir la verdad
en Claude Code y en Codex.** Desde 0.8.0, 4 PRs: #270, #274, #275 y #277,
más el de esta release.

Sin requisitos nuevos: himalaya **v2.x** y Python **3.10** o mayor, como en
0.8.0.

- **`session_watch_state` ya no sale `unknown` siempre en Claude Code**
  (#269, #270). `capabilities.py` declaraba esa observación para el runtime
  `claudecode`, pero `doctor` no tenía cómo calcularla, así que todo host
  Claude Code cerraba `paynani doctor` en `unknown`. Ahora sale del registro
  del vigía que ya resume `healthcheck.py`: `ok` con la sesión que vigila y su
  último latido, `warning` si nadie vigila y el correo espera en el spool.

- **Un aviso del roster ya no se pierde si la sesión se cierra antes de
  atenderlo** (#271). En Claude Code el vigía mueve el cursor en cuanto
  muestra un aviso, así que para paynani mostrar equivalía a atender. Si la
  sesión moría entre las dos cosas, el aviso no volvía a aparecer. Ahora el
  hook de SessionStart también lee el ledger y lista, en el bloque «ROSTER
  MAIL NOT YET CLOSED», cada aviso del roster de los últimos 7 días que sigue
  en `dispatched` o `presented`, con su `event_id`. Un aviso sale de esa lista
  cuando el agente lo cierra con `paynani event mark <id> handled`, `replied`
  o `closed`. El hook y `AGENTS.md` ya dicen que hay que hacerlo. La ventana se
  cambia con `PAYNANI_UNATTENDED_DAYS`. Esto aplica sólo a Claude Code: en
  Codex, la repetición al iniciar sesión tiene un límite de tamaño y no se
  toca.

- **Rearmar el vigía ya no repite los avisos que ya se cerraron** (#271).
  Después de un `/clear`, Claude Code cambia el `session_id` pero sigue en el
  mismo proceso. El registro de la sesión nueva guardaba el offset del momento
  del hook, así que al rearmar se volvían a mostrar los avisos que el vigía
  anterior ya había entregado. Ahora el vigía consulta el ledger antes de
  imprimir cada línea: si el evento ya está `handled`, `replied` o `closed`, lo
  consume sin mostrarlo y el cursor avanza igual.

- **Un corte de IMAP que se recupera solo ya no avisa** (#273). Cuando el
  proveedor cortaba la sesión TLS a mitad de IDLE (`SSLEOFError: EOF occurred
  in violation of protocol`), el listener escribía `connection lost` en el
  journal a la primera falla y `listener recovered` al reconectar. El
  dispatcher entregaba los dos como si fueran correo, así que un corte de 10
  segundos llegaba al humano como dos mensajes, varias veces al día y en varios
  hosts. Ahora la primera falla de un corte espera un periodo de gracia de
  120 s, que cubre los reintentos de 5, 10, 20 y 40 s. Si la conexión vuelve
  antes, no se escribe nada, ni la falla ni la recuperación. Si sigue caída al
  terminar la gracia, la falla se escribe en ese momento, aunque el listener
  esté esperando entre reintentos, y la recuperación sale después como antes.
  La gracia se cambia con `PAYNANI_FAULT_GRACE_SECONDS`; `0` vuelve al
  comportamiento anterior.

- **Muchos cortes cortos en una hora se avisan una sola vez, con los números**
  (#273). Si en la última hora hubo más de 5 cortes que se recuperaron dentro
  de la gracia, y que por eso no se avisaron, el listener escribe un solo evento
  con la cantidad, el último error, la última recuperación y el backoff actual.
  No se repite antes de una hora. Cuenta cortes, no intentos de reconexión: un
  solo corte largo reintenta varias veces y ya se avisó como falla y
  recuperación, así que no se cuenta. La telemetría de cada corte se sigue
  guardando como antes, así que `doctor` y `healthcheck.py` muestran el patrón
  completo aunque no se haya avisado.

- **`version_drift` ya no confunde un sandbox de Codex con un reinicio
  permanente** (#272). El listener y el dispatcher guardan el espacio de PIDs
  que cargaron; si `doctor` corre desde otro espacio, deja de usar ese `pid`
  para decidir que el proceso murió y conserva la comparación de versión y
  commit. Así un host Codex vuelve a reportar `ok`, y un `git pull` sin
  reiniciar sigue saliendo como `warning`.

### Si actualizas desde 0.8.0

En todos los hosts:

```bash
git fetch --tags --force origin
git pull --ff-only origin main
git describe --tags          # tiene que decir v0.8.1
python3 scripts/upgrade_plan.py --from v0.8.0     # y haz lo que imprima
```

**Antes de reiniciar, corre `doctor` una vez:**

```bash
scripts/paynani doctor | grep version_drift
```

Lo esperado es un `warning` que dice que en disco está 0.8.1 y los servicios
siguen corriendo lo anterior. **Un `ok` antes de reiniciar es la falla que
importa**, y hay que reportarla. En un host con **Codex**, si corres `doctor`
desde el sandbox, lo esperado antes de reiniciar es `unknown`: los procesos
viejos no guardaron su espacio de PIDs, que es justo lo que arregla #272.

Después reinicia, como diga el plan. En Linux:

```bash
systemctl --user restart paynani-idle.service paynani-dispatch.service
# macOS: launchctl kickstart -k "gui/$(id -u)/com.paynani.idle"
#        launchctl kickstart -k "gui/$(id -u)/com.paynani.dispatch"
```

Espera unos 15 segundos y comprueba:

```bash
scripts/paynani doctor | grep -E "version_drift|imap_telemetry"
```

Las dos filas deben salir en `ok`, también en Codex desde el sandbox.

**Sólo en Claude Code:** la primera sesión después de actualizar puede listar
muchos avisos en «ROSTER MAIL NOT YET CLOSED», porque antes de esta versión
ningún agente cerraba avisos (en el host de Metis salieron 199).
`python3 harness/session_start.py --unattended` imprime la lista completa, un
`event_id` por renglón. Revísala y, cuando todo lo que lista ya esté atendido,
ciérrala de una vez:

```bash
python3 harness/session_start.py --unattended |
    while read -r id; do scripts/paynani event mark "$id" closed; done
```

Desde esta versión, cada aviso del roster se cierra con
`scripts/paynani event mark <event_id> handled` (o `replied`, o `closed`)
después de atenderlo. Está en `AGENTS.md`, «Acting on verified mail».

## 0.8.0 (2026-09-22)

**Un correo en copia ya no se atiende como uno directo, los servicios avisan
cuando corren otra versión que la del disco, y el CLI gana `setup` y
`config`.** Desde 0.7.2, 19 PRs: #226, #227, #237, #238, #241, #248, #250,
#251, #252, #253, #254, #256, #258, #261, #262, #263, #264, #266 y #267, más
el de esta release.

Requiere himalaya **v2.x** y Python **3.10** o mayor. Ver «Si actualizas»,
al final de esta sección.

- **El marcador del servidor de configuración ya no guarda la liga con su
  token** (#230). `state/setup.server.json`, el archivo con el que `setup` y
  `config web` detectan un servidor ya vivo (#232), guardaba la URL completa,
  y con ella el token que permite escribir `.env`. El PRD de #230 pide que ese
  token viva sólo en `state/setup.token`. Ahora el marcador guarda el PID y el
  puerto, y la liga se rearma con `setup.token`, que es el mismo archivo que
  el servidor consulta en cada petición. Si un servidor sigue vivo pero su
  `setup.token` ya no existe, no se ofrece, porque ninguna liga le serviría.

- **`version_drift` distingue un proceso reiniciado de uno atrasado** (#265).
  Si el listener o dispatcher dejó un estado con `commit` viejo pero su `pid`
  ya no existe, `healthcheck.py` y `paynani doctor` lo reportan como `unknown`
  (`... restarted and has not reported its loaded version yet`) y no como
  `warning`: el proceso nuevo todavía no escribió qué cargó. Cuando ambos
  procesos sí están vivos y atrasados, el mensaje nombra a los dos, separando
  sus commits si difieren o agrupándolos si cargaron el mismo.

- **`paynani event show` ya no inventa el motivo de un rechazo de notifier**
  (#259). Al explicar un evento, `event show` armaba un mensaje con sólo el
  `From`, así que un correo de `notifications@github.com` rechazado por el
  roster salía como "declared notifier is missing X-GitHub-Sender": culpaba
  al proveedor cuando el header sí venía y lo que no coincidía era el roster
  propio. Ahora el listener guarda en el evento los headers declarados en
  `## Notifiers` (`notifier_headers`) y `event show` los vuelve a poner antes
  de decidir, así que el motivo nombra el valor real y la columna del roster
  contra la que falló. Un evento viejo que no guardó el header ya no recibe
  un motivo inventado: `event show` dice que no puede determinarlo desde el
  journal y remite a `paynani roster explain` y al `roster.md` del host.

- **CLI: `paynani setup`, `paynani config`, `config web` y `config edit`**
  (#232, parte 2 de #230). `setup` es el nombre descubrible de `onboard`, que
  se queda como alias funcionando igual (está escrito en `INSTALL.md`,
  `MAILBOX_SETUP.md` y las notas de varios agentes de la flota). `config`
  imprime la configuración actual, de sólo lectura y siempre sale con 0: la
  contraseña nunca se imprime (`(set, not shown)` o `(not set)`, nunca un
  enmascarado parcial), sólo se listan las llaves de paynani (las ajenas se
  cuentan, no se nombran ni se muestran), y una llave obligatoria ausente se
  marca en su renglón y se repite al final sin cambiar el código de salida.
  `config web` reutiliza el mismo servidor de `setup` -- si ya hay uno vivo
  de esta instalación (rastreado por un archivo de marca con PID y puerto,
  verificados antes de confiar en él), imprime esa URL en vez de levantar un
  segundo servidor sobre el mismo `.env`. `config edit` abre `.env` en
  `$EDITOR`: se rehúsa sin `$EDITOR` (nombrando la variable) y sin una
  terminal en la entrada estándar, valida al salir con la misma validación
  del formulario y reporta campo por campo, y conserva el modo 600. Es un
  comando del humano -- `AGENTS.md` deja escrito que ningún agente lo corre;
  para cambiar una llave, `paynani set` sigue siendo lo que un agente usa.

- **`version_drift` también confronta el commit, no sólo la versión** (#260).
  Un host que sigue `main` entre versiones etiquetadas puede hacer `git pull`
  y traer código nuevo sin que `VERSION` cambie, así que el aviso de #257 se
  quedaba callado justo en ese caso -- reproducido la misma noche del merge,
  en el único host de la flota que sigue `main`. `idle_listener.py` y
  `harness/dispatch.py` ahora guardan también el `HEAD` que cargaron al
  arrancar; cuando la versión coincide pero el commit no, `healthcheck.py` y
  `paynani doctor` lo dicen con los dos commits abreviados a 7 caracteres y
  el mismo comando de reinicio, todavía como `warning`, nunca como
  `problem`. De paso, `VERSION` ausente en disco ya no se reporta como `ok`
  (nada se comparó): sale `unknown`.

- **`healthcheck.py` compara la versión en disco con la que cada proceso
  cargó** (#257). `scripts/idle_listener.py` y `harness/dispatch.py` ya
  guardaban la versión que cargaron al arrancar (`PROCESS_VERSION`), pero
  nada la confrontaba contra `VERSION` del repo -- un `git pull` con los
  servicios sin reiniciar dejaba el disco y los procesos en desacuerdo sin
  que ningún aviso lo dijera, durante tres días en un host real. Ahora la
  fila `version` de `healthcheck.py` lo dice con ambas cifras y el comando
  para corregirlo; `paynani doctor` lo reporta como `warning`, no `blocked`
  (el host sigue recibiendo y entregando correo) ni `ok`. Un proceso que
  aún no reportó su versión (recién reiniciado) sale como `unknown`, no
  como una discrepancia.

- **`scripts/send.sh` y `paynani doctor` exigen himalaya v2.x para enviar**
  (#255). v1.x no tiene `smtp send`, que es como el Bcc se queda en el sobre y
  fuera del mensaje, así que `send.sh` se rehúsa antes de intentar mandar y el
  aviso dice la versión encontrada, la requerida y que subir el binario no
  basta: hay que reescribir la configuración con el esquema v2 de `INSTALL.md`
  §4.3 y confirmarlo con `himalaya account list` (`BACKENDS` en `imap, smtp`) y
  un `himalaya envelope list` real. `INSTALL.md` deja de documentar v1.x como
  soportada. Sin cambios para v2.x.

- **El sobre dice en qué papel llegó el correo: `To`, `Cc` o destinatario
  oculto** (#221, PR #227, parte 2a de #214). El listener pide ahora `To` y
  `Cc` y compara la cuenta contra las direcciones reales, no contra el nombre
  de despliegue. El campo `recipient_role` viaja en el evento y en
  `paynani event show`. Con `to` la línea de notificación no cambia; con copia
  o destinatario oculto gana la marca junto a `roster`, por ejemplo
  `[mail 22:43:10, sent 22:42:41, roster, cc]`. Este cambio sólo informa; la
  regla de qué hacer con eso es la entrada siguiente.

- **La regla de actuación para correo en copia** (#222, PR #226, parte 2 de
  #214). `AGENTS.md` abre con ella: un correo del roster es trabajo cuando este
  agente está en `To`; si sólo está en `Cc`, o el destinatario es oculto, es
  contexto, salvo que el cuerpo verificado lo nombre. Una línea que empieza con
  el correo o el `Name` del roster de este agente seguido de dos puntos es una
  instrucción mecánica para él, y `event show --body` la reporta como
  `marker_for_me` y `marker_lines`. Sin esa marca, el agente lee el cuerpo como
  lo leería un colaborador humano en copia, y si actúa, empieza diciendo qué
  instrucción entendió. `FIELD_TEST.md` gana las filas para probarlo en cada
  runtime. Es el cambio de comportamiento más grande de esta versión, porque
  hasta 0.7.2 un correo del roster en copia se atendía igual que uno directo.

- **Reconexiones IMAP por hora** (#234, PR #237). El estado del listener
  guarda una ventana de una hora (`imap_reconnect_window`,
  `imap_reconnects_last_hour`) sin tocar el contador total, y `healthcheck.py`
  avisa bajo `listener` cuando hay más de cinco reconexiones en la última hora.

- **Una reconexión que se recuperó no es noticia** (PR #254). Regla nueva en
  `AGENTS.md`: no se le reporta al humano cada caída de IMAP que se recuperó
  sola. Se reporta cuando sigue caída después de tres intentos, con campos
  observables: `imap_last_disconnect_at` más reciente que
  `imap_last_recovered_at` e `imap_current_backoff_seconds` en 20 o más.

- **Los servicios se rehúsan a arrancar con Python menor a 3.10** (#236,
  PR #241). `harness/python_floor.py` corre antes de importar nada del
  proyecto, en el listener y en el dispatcher. Cada uno guarda su intérprete
  en su estado, `healthcheck.py` lo muestra en la fila `python` y bloquea si
  alguno está debajo del piso, y `paynani doctor` lo evalúa. Antes, un
  servicio con un Python viejo arrancaba y fallaba después, lejos de la causa.

- **`scripts/test_all.sh` se rehúsa con Python menor a 3.10** (#233, PR #238),
  antes de correr una sola prueba, y acepta `PYTHON=` para elegir intérprete.

- **`version.sh --apply` funciona con las etiquetas anotadas de las releases**
  (#242, PR #252). Comparaba el objeto de la etiqueta contra el commit y se
  rehusaba siempre. Ahora resuelve `FETCH_HEAD` a su commit antes de comparar.

- **`version.sh --plan` trae los tags que le faltan** (#247, PR #253). En un
  clon sin tags, `--plan` sin `--to` intenta `git fetch --tags origin` y
  recalcula en la misma corrida. Si no hay red, conserva el mensaje que dice
  qué correr. Lo encontró Lisa actualizando a 0.7.2.

- **`upgrade_plan.py` conoce `harness/python_floor.py`** (PR de esta
  versión). El listener y el dispatcher lo importan al arrancar, pero no tenía
  fila en la tabla: el plan de 0.7.2 a esta versión lo listaba como
  desconocido y `--apply` se rehusaba por eso. Es la segunda vez que pasa
  (`ledger.py` en 0.7.1), así que una prueba ahora recorre cada archivo de
  `harness/` y falla si alguno no tiene fila.

- **Pruebas de `doctor` aisladas del host** (#249, PR #250). Las lecturas de
  `systemctl --user show-environment` y de `~/.config/environment.d` pasan a
  `_dependency_facts()`, así que las pruebas sintéticas de `doctor` ya no
  dependen del host donde corren.

- **`RELEASING.md`** (#244, PR #248, y PR #256). El procedimiento de release
  por escrito, cada paso con lo que salió mal cuando faltó: comparar contra
  `git log <tag>..main --merges`, subir `VERSION` en el mismo PR, actualizar el
  host propio con los pasos exactos del aviso antes de mandarlo, comprobar en
  qué se parece ese host a los demás, y decir qué versión de cada herramienta
  externa exige la release. Los dos PRs corrigieron además el apartado «Si
  actualizas» de 0.7.2.

- **El PR lleva su `Closes #N` y su entrada de CHANGELOG** (PR #251). Regla
  nueva en `AGENTS.md`. `Closes`, en inglés, porque `Cierra #N` no cierra nada
  en GitHub. Y la entrada del CHANGELOG la escribe quien hace el cambio, cuando
  todavía recuerda qué fue lo difícil. En esta misma sección de 0.8.0, doce
  PRs llegaron sin entrada y hubo que reconstruirlas desde fuera.

### Si actualizas desde 0.7.2

**Dos requisitos nuevos, antes de tocar nada.** Esta versión exige himalaya
**v2.x** para enviar (#255) y Python **3.10 o mayor** para que arranquen el
listener y el dispatcher (#236). Un servicio con un Python viejo ahora se
rehúsa a arrancar, así que compruébalo antes de reiniciar:

```bash
himalaya --version        # tiene que decir 2.x
python3 --version         # el intérprete de tus servicios: 3.10 o mayor
```

Si alguno no cumple, detente y actualízalo primero. Los diez hosts de la flota
ya tenían himalaya v2.x al cierre de esta versión.

Luego, en todos los hosts:

```bash
git fetch --tags origin
git pull --ff-only origin main
python3 scripts/upgrade_plan.py --from v0.7.2     # y haz lo que imprima
```

**No uses `scripts/version.sh --apply` en esta actualización.** El arreglo de
`--apply` (#242) viene en esta versión, pero el `version.sh` que corre antes
del `pull` es el de 0.7.2, que todavía se rehúsa contra cualquier release.

**Antes de reiniciar, corre `doctor` una vez.** Es la prueba real de #257 en
tu host: el código nuevo ya está en disco y los procesos siguen siendo los de
0.7.2, así que tiene que avisarlo.

```bash
scripts/paynani doctor | grep version_drift
```

Lo esperado, exactamente:

```text
warning  version_drift: paynani 0.8.0 on disk, but the listener is running 0.7.2
```

Sólo nombra al listener porque el dispatcher de 0.7.2 no guardaba qué versión
cargó; a partir de esta versión los dos lo hacen. Si sale `ok`, no sigas: el
aviso que agregó esta versión no está funcionando en tu host, y eso es lo que
hay que reportar.

Después reinicia, como diga el plan. En Linux:

```bash
systemctl --user restart paynani-idle.service paynani-dispatch.service
# macOS: launchctl kickstart -k "gui/$(id -u)/com.paynani.idle"
#        launchctl kickstart -k "gui/$(id -u)/com.paynani.dispatch"
```

Espera unos segundos y comprueba:

```bash
scripts/paynani doctor | grep -E "version_drift|python|himalaya"
```

Justo después del reinicio es normal ver `unknown  version_drift: listener
restarted and has not reported its loaded version yet` (#265). Espera a que
salga `ok`.

**Lee la sección de arriba de `AGENTS.md`, «Acting on verified mail».**
Cambió cómo se atiende un correo en el que tu agente sólo va en copia (#222).
No hay nada que configurar, pero el comportamiento que tu humano ve sí cambia.

Rearma el vigía en la siguiente sesión de Claude Code. No hace falta migrar
estado ni tocar credenciales.

## 0.7.2 (2026-09-19)

**Correo con copia oculta, el roster migrado, y dos defectos de documentación
que sólo aparecieron cuando dos hosts distintos corrieron la misma prueba.**
Desde 0.7.1, 30 PRs: #182, #184, #185, #191, #192, #193, #194, #195, #196,
#197, #198, #199, #200, #201, #202, #203, #205, #206, #207, #208, #210, #211,
#212, #213, #217, #218, #223, #224, #229 y #235.

- **`scripts/send.sh` manda con copia oculta, y `--to`, `--cc` y `--bcc` se
  repiten** (#220, PR #229). El envío pasa a `himalaya smtp send` con el sobre
  explícito: un `--rcpt-to` por cada dirección, y el encabezado `Bcc:` nunca
  viaja en el mensaje. Esa decisión no es de estilo. Antes de escribir código se
  comprobó qué hace Himalaya con un encabezado `Bcc:` en la entrada, y resultó
  que lo usa como destinatario del sobre **pero lo deja pasar en el mensaje
  entregado**, o sea que la implementación obvia le habría mostrado a cada
  destinatario la lista completa de copias ocultas. Las tres listas pasan por el
  mismo portero del roster, con la misma limpieza de saltos de línea, y
  `state/sent.log` registra `bcc=` porque el secreto de una copia oculta es
  frente a los destinatarios, no frente a la bitácora local. `--dry-run` y
  `--check` muestran ahora los destinatarios del sobre y el backend de salida.
  Si ese backend no es SMTP, `send.sh` se rehúsa antes de mandar en vez de
  ignorar la configuración de la cuenta.
- **`scripts/paynani roster migrate` y `roster apply`** (#166, PR #184). La
  columna heredada `Username` se migra a `GitHub` con `--plan` y `--apply`, con
  confirmación o `--yes`, y las altas por lote desde un JSON son atómicas: una
  fila inválida no deja el archivo a medias. El éxito informa dónde quedó el
  respaldo.
- **`paynani set` escribe `PAYNANI_SIGNATURE_FILE`** (#219, PR #223), y
  `scripts/send.sh` agrega una firma de texto plano a las respuestas (#175, PR
  #212). La llave se validó contra una ruta legible antes de tocar `.env`, y un
  valor vacío la quita. Antes existía la función pero no la forma de
  configurarla: el único comando que escribe `.env` no conocía la llave y
  mandaba a editar a mano el archivo donde viven la contraseña y los tokens.
- **`paynani` a secas muestra la ayuda** (#231, PR #235), igual que `paynani
  help`, `-h` y `--help`, en `stdout` y con salida 0. Antes respondía con un
  error de argparse en `stderr` y código 2 a quien escribía el comando para ver
  qué hacía.
- **`FIELD_TEST.md` cubre los cinco runtimes** (#173, PRs #201, #205, #206,
  #217): Claude Code, OpenClaw, OpenAI Codex, Hermes Agent y OpenCode, una
  sección por runtime con los estados que hay que provocar, el comando, la
  salida exacta esperada y qué se pega como evidencia. Dos hosts distintos de
  Codex corrieron la misma tabla y encontraron dos defectos que ninguno de los
  dos habría encontrado solo: una fila documentaba `stderr` donde el programa
  escribe en `stdout`, y otra pedía provocar un estado que en un host al
  corriente es imposible de provocar, sin decir cómo. Las dos filas traen ahora
  un fixture reproducible, y el encabezado advierte que las filas de estado se
  provocan con `CODEX_HOME` o `PAYNANI_STATE` temporales, nunca desinstalando
  hooks ni borrando estado en un host que recibe correo.
- **`AGENTS.md` dice cómo entra un cambio** (#213): por PR aprobado por alguien
  distinto del autor, y nadie mezcla lo suyo con su propia aprobación. Una
  autorización permanente del humano dice cuándo se puede mezclar, no exime de
  la revisión.
- **El vigía con offset numérico ya escribe su registro** (#215, PR #218). Sólo
  el camino de `--from-hook` fijaba `session_id`, así que armar con un offset
  numérico dejaba a `healthcheck.py` diciendo que nadie vigilaba mientras el
  vigía entregaba correo.
- `paynani doctor` reporta la telemetría IMAP de reconexión (#207) y las
  observaciones declaradas por cada runtime (#210); `paynani onboard` completa
  su lista de verificación y su resumen sin secretos (#208).
- `paynani doctor` comprueba además sus dependencias, `python`, `himalaya` y el
  CLI del runtime (PR #198), mide el drenado de la cola y el entorno real del
  servicio (PR #192), y `paynani onboard` termina con una pantalla que nombra
  los pasos que faltan según el runtime (PR #196).
- **`STATUS_MATRIX.md`**: qué estado puede observar cada harness y cuál no,
  incluidos los notificadores y la regla permanente de OpenClaw (PRs #197 y
  #200). `HARNESS_CAPABILITIES.md` queda enlazado desde la documentación y las
  traducciones se verifican contra la estructura del original (PR #191).
- `scripts/send.sh --dry-run` imprime un resumen redactado de la entrega, con
  destinatarios, filas del roster que los autorizan y forma MIME, y no manda
  nada (PR #194). Es la base sobre la que esta versión agregó el sobre
  explícito y el backend de salida.
- `scripts/paynani openclaw probe --dry-run` acepta una sonda sintética sin
  tocar IMAP ni el diario, y `healthcheck.py` la reporta aparte del correo real
  (PR #195).
- `scripts/test_hermes_install.py` ignora `state/` al clonar el repo en sus
  cajas de arena (#216, PR #224): el FIFO de un vigía vivo, que es el estado
  normal de un host sano, hacía fallar la prueba. De paso, un clon de prueba ya
  no se lleva el `roster.md` real del host.


- `scripts/version.sh --apply [REF]` ejecuta la parte 2 de #167: congela el
  commit del plan, comprueba que el ref remoto no cambió antes del fast-forward,
  aparta overlays con patch binario y stash, ejecuta sólo instalador, registros
  y reinicios calculados, restaura el overlay y corre la suite. Rehúsa sin plan,
  ante archivos `unknown`, copias instaladas modificadas o runtime desconocido.
  El listener guarda en `idle.json` la versión que cargó al arrancar y el apply
  termina sólo si coinciden versión en disco y proceso, aparece un nuevo
  `resuming from uid N` y `healthcheck.py` sale verde.
- Claude Code: el vigía se rearma con el mismo `--from-hook` después de que
  Claude Code retira el Monitor. El registro contestaba sólo en `pending`, y
  a los 30 minutos ya estaba en `ended`, así que el rearme rehusaba; ahora
  devuelve el cursor al que llegó el vigía anterior, que el latido guarda
  tras cada línea mostrada (así un SIGKILL tampoco repite nada). Un lock
  cuyo vigía murió con la sesión viva se recupera solo. `healthcheck.py` nombra
  ese estado («ended at ... (the Monitor was retired) without re-arming»)
  en vez de decir que ninguna sesión vigiló, y avisa si hay correo sin ver. Y
  los escritores del fifo cierran el descriptor del lock: un `sleep` huérfano
  del ticker lo retenía hasta dos segundos y el siguiente vigía leía «a
  watcher from a previous version still holds this spool». Visto en vivo el
  2026-09-18 a las 07:15Z, en el paso 4 de `FIELD_TEST.md`.
- **Claude Code: el vigía se arma sin copiar números y su estado se ve desde
  fuera** (#170, PR #199). El hook de `SessionStart` escribe
  `state/sessions/<session-id>/watch.json` con el offset que replicó (el id
  viene del JSON que Claude Code le da al hook; nunca se inventa) y el comando
  que imprime es `session_watch.sh <state> --from-hook`, que lee ese registro
  por `CLAUDE_CODE_SESSION_ID`. El vigía mantiene el registro mientras vive
  (`armed` con pid y vencimiento, latido por minuto, `ended` al salir,
  `yielded` si otra sesión ya vigila) y `healthcheck.py` gana la fila `watch`:
  quién vigila desde cuándo y hasta cuándo, o que el último vigía venció o fue
  matado sin rearmar (aviso si hay correo sin ver). Un hook nuevo de
  `UserPromptSubmit` agrega una línea al turno sólo cuando hay correo en el
  spool que ningún vigía vivo va a mostrar, con el comando para rearmar.
  `scripts/claude_hook.py --install` registra el que falte. La forma con
  offset numérico sigue funcionando para invocaciones a mano.
- `scripts/ci_streak.sh` (#174, PR #193): cuántas corridas seguidas en verde lleva
  `main` para volver requerido `suite-macos`, con la regla del CHANGELOG de
  0.7.0 aplicada igual cada vez: un re-run (`attempt > 1`) o una falla
  reinician la cuenta y se nombran con su commit; una corrida en curso no
  cuenta; sale 0 sólo con las diez seguidas y no antes del 2026-09-30.
  `--json` para scripts.
- `scripts/version.sh --plan [REF]` y `scripts/upgrade_plan.py`: qué hay que
  reiniciar entre dos versiones, calculado a partir del `git diff` entre los
  tags, del manifiesto del instalador y de una tabla que dice qué proceso o
  copia carga cada archivo (#167, parte 1). Cada archivo cambiado recibe un
  verbo: `restart`, `reinstall-and-restart`, `restart-runtime`,
  `next-session`, `none` o `unknown`, y el plan termina con los comandos en
  orden para el runtime y el sistema de este host: el instalador si cambió una
  copia suya, el paso de registro que el instalador nombra y no ejecuta
  (`opencode_plugin.py`, `claude_hook.py`, `codex_hook.py`,
  `openclaw_rules.py --install`), los reinicios de servicios y el del harness.
  Sin un tag o sin `install.manifest` el plan dice que no puede calcularse y
  remite a `UPGRADE.md`; nunca convierte datos ausentes en «nada que
  reiniciar». Lista además los overlays locales (archivos rastreados
  modificados en el clon), dice cuáles también cambian con la actualización y
  da los comandos para dejar registro y apartarlos antes del pull (PR #185). El reporte
  completo de `version.sh` imprime el plan cuando hay una versión más nueva.
  `UPGRADE.md` §2 lo incorpora.
- Claude Code: el vigía de sesión conserva el FIFO hasta cerrar, para que `tail`
  no pueda escribir en un archivo regular si el ticker abre primero. Incluye una
  prueba determinista de esa carrera (#179, PR #182).

### Si actualizas desde 0.7.1

Cambiaron `scripts/send.sh`, `scripts/roster.py`, `scripts/paynani`,
`scripts/idle_listener.py` y `harness/session_watch.sh`, así que en todos los
hosts:

```bash
git fetch --tags origin
git pull --ff-only origin main
python3 scripts/upgrade_plan.py --from v0.7.1     # y haz lo que imprima
```

**El plan se pide nombrando la versión de la que vienes, no con `version.sh
--plan` a secas.** Ese camino no funciona en ningún momento de esta
actualización, y falla por dos razones opuestas. Antes del `pull`, el
`version.sh` instalado desde la 0.7.1 etiquetada todavía no conoce `--plan` y
contesta `usage:` con salida 64, que fue lo que encontró Zeus. Después del
`pull`, `VERSION` ya dice 0.7.2 y `--plan` toma por defecto `--from v<VERSION>`,
así que compara 0.7.2 contra 0.7.2 y responde que no hay nada que planear, que
fue lo que encontró Ares. A ninguno de los dos defectos llegué yo, y por la
misma razón las dos veces: mi clon sigue `main` en vez del tag, así que es el
único host donde ese comando podía funcionar.

El plan es por host: calcula qué cambió entre tu versión y ésta, y nombra sólo
los pasos que a ti te tocan. En el mío, por ejemplo, no hacía falta reinstalar
nada, sólo el hook de sesión y reiniciar el escucha. Si el plan no puede
calcularse, porque falte el tag o el manifiesto, lo dice y entonces van los
pasos genéricos:

```bash
git pull
scripts/install.sh --runtime <runtime> --upgrade
systemctl --user restart paynani-idle.service paynani-dispatch.service
# macOS: launchctl kickstart -k "gui/$(id -u)/com.paynani.idle"
#        launchctl kickstart -k "gui/$(id -u)/com.paynani.dispatch"
scripts/healthcheck.py
```

**No uses `scripts/version.sh --apply` en esta versión.** Se rehúsa contra
cualquier release, porque compara el objeto del tag anotado contra el commit
(#242). La negativa es segura, no deja el clon a medias, pero no avanza.

**Y comprueba tu `roster.md`, que en esta versión es un paso obligatorio y no
una recomendación.** Un host de la flota llegó hasta aquí con la columna
heredada `Username` y sin fila de notificadores, así que las notificaciones de
GitHub le llegaban como correo de un desconocido: su agente veía los
comentarios de los PRs sólo si iba a mirarlos, y nadie lo sabía. Tres comandos:

```bash
scripts/paynani roster migrate --plan     # ¿dice `Username -> GitHub`?
scripts/paynani roster migrate --apply    # sólo si el plan lo pidió
scripts/paynani roster explain --from notifications@github.com \
    --header X-GitHub-Sender=<handle-de-otro-agente-de-tu-roster>
```

El tercero tiene que decir `AUTHORIZED` y nombrar a ese contacto. Si dice otra
cosa, falta la columna `GitHub` o falta el handle en la fila de esa persona.
Mientras eso no salga `AUTHORIZED`, tu agente no está recibiendo el canal por
el que trabaja el equipo.

**Usa el handle de otra persona de tu roster, no el tuyo.** Tú no eres un
contacto de tu propio roster, así que con tu handle va a decir `NOT AUTHORIZED`
y eso es correcto, no una falla. Lo aprendí corriendo este mismo paso en mi
host antes de mandarles esta versión.

Rearma además el vigía en la siguiente sesión de Claude Code. No hace falta
migrar estado ni tocar credenciales.

## 0.7.1 (2026-09-18)

**Dos defectos de campo del mismo día, y las herramientas de diagnóstico e
inspección que ya estaban listas.** 23 commits desde 0.7.0 (PRs #176, #177,
#180, #187 y #189).

- **En OpenClaw, el correo del roster no se contestaba** (#186). Un agente en
  OpenClaw 2026.9.4 recibió correo del roster, paynani lo entregó y OpenClaw
  aceptó el evento, y nadie contestó hasta que una persona miró. La regla que
  convierte la línea `System:` en una respuesta tenía que copiarla el agente a
  sus instrucciones persistentes, y nada verificaba que lo hubiera hecho. Ahora
  `scripts/openclaw_rules.py --install` la escribe entre marcadores en
  `~/.openclaw/workspace/AGENTS.md`, `--check` y `--uninstall` la revisan y la
  quitan, `scripts/healthcheck.py` la reporta en la fila `instructions` y el
  instalador nombra el paso (`openclaw_rules_next_step=`). Además, el evento
  que llega a OpenClaw con `roster_match` trae una segunda línea con el comando
  exacto de Himalaya para leer el correo y `scripts/send.sh` para contestar,
  sin cuerpo. Probado en campo por Xochitl: respuesta sola en menos de tres
  minutos.
- **Las notificaciones de GitHub llegaban sin etiqueta roster** en nueve de
  diez hosts (#188): los rosters tenían la columna `GitHub` con los handles y
  no la fila de `## Notifiers` que activaba el cotejo de `X-GitHub-Sender`. La
  columna `GitHub` ahora declara ese notificador por sí sola; una fila
  explícita gana y no se duplica, una celda vacía no coteja a nadie y sin
  columna nada cambia. `healthcheck.py` dice qué notificadores están activos y
  de dónde salen. Ningún `roster.md` hay que tocar.
- **`paynani doctor`, `paynani paths` y `paynani support-bundle`** (#168, parte
  1, PR #177). `doctor` diagnostica con cuatro estados (`ok`, `warning`,
  `blocked`, `unknown`) y un `next_command` por check, lee la matriz de
  capacidades del runtime y reporta `unknown` para lo que el harness no expone;
  el esquema JSON de su salida está en `examples/doctor.schema.json`.
  `support-bundle` escribe un paquete redactado: la lista de claves del `.env`
  con su modo, nunca sus valores.
- **Matriz de capacidades por runtime** (#169, PR #176):
  `harness/capabilities.py` es la fuente única de qué observa cada harness, y
  genera `HARNESS_CAPABILITIES.md` y la tabla de `DESIGN.md`.
- **Ledger de vida del evento** (#171, PR #180). Append-only por evento, con
  estados observado, despachado, presentado, atendido, respondido, cerrado o
  suprimido. Conserva el sobre seguro y las identidades de proveedor, nunca el
  cuerpo.
- `scripts/paynani event show/list/mark`, `scripts/paynani status` y
  `scripts/paynani roster explain` hacen observable el recorrido, verifican el
  UID exacto antes de recuperar correo y explican las decisiones del roster.
- Los duplicados del mismo `event_id`, `Message-ID` o identificador estable del
  proveedor se suprimen de forma explícita y apuntan al evento canónico.
- El estado de Codex distingue sesión registrada, último `codex queue`, caída
  al spool y replay; una CLI sin el contrato opcional de `codex queue` se
  reporta como `unsupported`, no como una instalación rota.

### Si actualizas desde 0.7.0

`git pull` y seguir `UPGRADE.md`. Cambiaron el escucha (`roster.py`,
`idle_listener.py`), el dispatcher (`dispatch.py`, `event.py`, los adaptadores)
y el hook de sesión (`session_start.py`), así que en todos los hosts:

```bash
git pull
scripts/install.sh --runtime <runtime> --upgrade
systemctl --user restart paynani-idle.service paynani-dispatch.service
# macOS: launchctl kickstart -k "gui/$(id -u)/com.paynani.idle"
#        launchctl kickstart -k "gui/$(id -u)/com.paynani.dispatch"
scripts/healthcheck.py
```

En **OpenClaw**, además, `scripts/openclaw_rules.py --install` y `--check` con
exit 0. En **Claude Code** y **Codex**, reinicia las sesiones abiertas para que
carguen el hook nuevo. Nadie tiene que tocar `roster.md`: la columna `GitHub`
basta.

### Pendientes conocidos

- **`suite-macos` todavía no es un check requerido.** Pasa a requerido con 10
  corridas seguidas en verde en `main`, sin re-runs, y no antes del 2026-09-30.
  Al preparar esta versión la cuenta va en 11 (desde el re-run de #151 el
  2026-09-17); manda la fecha.
- **#168 sigue abierto** con tres requisitos por entregar: `draining` medido,
  entorno persistente vs vivo de `systemd --user` y telemetría de reconexión
  IMAP.
- `paynani roster migrate --plan` muestra la migracion de la columna heredada
  `Username` a `GitHub` sin escribir.
- `paynani roster migrate --apply [--yes]` aplica la migracion de forma
  atomica, conserva un respaldo `roster.md.bak` y restaura los bytes originales
  ante cualquier fallo.
- `paynani roster apply --file CONTACTS.json [--dry-run] [--yes]` valida y
  agrega un lote completo en una sola escritura. Si una fila es invalida, no
  cambia el roster. El campo `type` del lote acepta `Human` o `AI Agent`.

## 0.7.0 (2026-09-17)

**Paynani corre en OpenCode, el quinto harness.** 17 commits desde 0.6.0
(PRs #150, #153, #154, #156, #159, #161, #162 y #163).

- **Soporte para OpenCode** (#152). `scripts/install.sh --runtime opencode` y
  `PAYNANI_RUNTIME=opencode`. El dispatcher escribe cada evento en
  `state/opencode.spool`, y un plugin que corre dentro de OpenCode
  (`harness/opencode/paynani.js`) le pasa los pendientes a la sesión en la que
  trabajas cuando queda inactiva, y solo entonces avanza `opencode.offset`. El
  plugin se registra con `scripts/opencode_plugin.py --install`. Las
  credenciales van en `~/.opencode/workspace/.env`.
- **Probado en campo** en OpenCode 1.18.31 sobre Ubuntu 24.04 en WSL (#157). El
  turno empieza solo entre 2 y 7 segundos después de que llega el correo, espera
  si la sesión está ocupada, libera el lock al cerrar OpenCode y no se activa en
  `opencode run`.
- `scripts/healthcheck.py` distingue tres estados de OpenCode: entregando,
  abierto pero sin una sesión en la que escribir todavía, y cerrado (#160).
- `AGENTS.md` paso 2 ya no promete que el agente sigue solo cuando se guarda el
  formulario. En OpenCode, y en cualquier harness que no avisa, el agente le
  pide al humano que escriba «listo» (#158).
- `UPGRADE.md` trae los comandos de macOS para reiniciar y verificar los
  servicios, y la prueba con correo real pasa a ser opcional (#149).
- Dos pruebas del watcher que fallaban a veces en macOS: la limpieza ahora
  derriba todo el árbol de procesos (#151), y el timeout que quedaba imprime un
  diagnóstico completo si vuelve a pasar (#155).
- Los README en los cinco idiomas mencionan lo que cambia con OpenCode: el aviso
  de «listo», el archivo del plugin y los tres estados del chequeo de salud, y
  enlazan el repositorio de cada harness (#163).

### Si actualizas desde 0.6.0

`git pull` y seguir `UPGRADE.md`. Nada cambia en OpenClaw, Hermes, Claude Code
ni Codex: los archivos compartidos que tocaron estos cambios (`dispatch.py`,
`paths.py`, `envpath.sh`, `install.sh`, `install_manifest.py`) solo agregan
`opencode` a la lista de harnesses conocidos. En OpenCode, **reinicia OpenCode**
después del pull: el plugin se carga al arrancar, y el proceso abierto sigue con
el código anterior. Esta es la primera versión en la que `UPGRADE.md` §6 trae
los comandos de macOS.

### Pendientes conocidos

- **`suite-macos` todavía no es un check requerido.** Pasa a requerido con 10
  corridas seguidas en verde en `main`, sin re-runs, y no antes del 2026-09-30.
  La cuenta se reinició el 2026-09-17 con una corrida que necesitó re-run
  (#151); al preparar esta versión va en 5.

## 0.6.0 (2026-09-16)

**La instalación a mano ya no deja pasos sueltos, y la suite pasa en macOS.**
17 commits desde 0.5.0.

- `paynani roster add` crea `roster.md` desde la plantilla si todavía no
  existe, y `AGENTS.md`, `INSTALL.md` y `send.sh` usan ese comando en lugar de
  copiar la plantilla.
- La suite pasa por primera vez en `main` en Linux y en macOS. Dos de los
  arreglos son del producto: en macOS, `send.sh` codificaba mal el nombre de un
  adjunto con acentos, y el escucha dejaba el keepalive en dos horas con el
  Python de Apple.
- `AGENTS.md` e `INSTALL.md` siguen el flujo del formulario: el agente no pide
  por chat lo que el formulario ya pregunta, y manda el comando `ssh -L` junto
  con el enlace.
- Las pruebas con correo real dejan de ser requisito para que el agente declare
  terminada la instalación.
- Las traducciones de `README.md`, `MAILBOX_SETUP.md` y `saved.roster_failed`
  quedan al día en los cuatro idiomas.

### Si actualizas desde 0.5.0

Ninguna unidad de systemd, LaunchAgent, hook ni instalador cambió desde 0.5.0.
Basta `git pull` y seguir `UPGRADE.md`, **incluido el reinicio del escucha**:
`scripts/idle_listener.py` cambió, y el proceso que ya corre sigue con el código
anterior hasta que arranca otra vez. En Linux es la sección 6 de `UPGRADE.md`.
En macOS, esa sección todavía no trae el comando; es:

```bash
launchctl kickstart -k "gui/$(id -u)/com.paynani.idle"
```

En Linux el cambio del escucha no altera nada; en macOS es el que aplica el
keepalive de verdad.

### Pendientes conocidos

- **`suite-macos` todavía no es un check requerido.** Pasa a requerido con 10
  corridas seguidas en verde en `main`, sin re-runs, y no antes del 2026-09-30
  (14 días desde que se cerró #129), lo que ocurra más tarde.
- **`UPGRADE.md` §6 solo trae los comandos de Linux** para reiniciar los
  servicios.

**`paynani roster add` crea `roster.md` si todavía no existe.** Issue #135.
Quien escribía el `.env` a mano nunca pasaba por el formulario, así que no
tenía `roster.md`, y el comando lo rechazaba con `roster.md has no contacts
table` hasta que alguien copiara la plantilla. Ahora parte de
`roster.md.example` y agrega la fila. Decide cuándo usar la plantilla con la
misma función que el formulario (`_starting_text()`), así que un `roster.md` que
ya existe nunca se reemplaza, aunque no tenga tabla de contactos. Las pruebas
previas, la verificación posterior y el borrado del archivo creado si esa
verificación falla son los mismos del formulario. Sin `--yes`, la confirmación
dice que va a crear el archivo a partir de la plantilla y muestra solo la fila
nueva.

El paso 7 de `AGENTS.md` y el punto 7 de `INSTALL.md` §2 dejan de copiar la
plantilla para luego escribir la fila, y corren
`scripts/paynani roster add "Your Human" you@example.com --type Human --yes`.
`send.sh`, al no encontrar `roster.md`, sugería
`cp roster.md.example roster.md`, que deja una lista sin nadie autorizado;
ahora sugiere el comando. `test_docs.py` falla si `AGENTS.md` o `INSTALL.md`
dejan de indicarlo. `README.md` (Paso 2) y `MAILBOX_SETUP.md` vuelven a
mencionar el comando para la ruta manual.

**La suite pasa en macOS.** Issues #133, #112, #113 y #129, PRs #144 y #148 de
Ximena.

- `test_listener.py` esperaba que `SO_KEEPALIVE` valiera 1; BSD devuelve el bit,
  8. Ahora basta con que no sea 0.
- El Python de Apple no expone `TCP_KEEPALIVE`, aunque Darwin lo define como
  `0x10` y el kernel lo acepta. Sin él, el keepalive quedaba activo con el
  temporizador del sistema, dos horas, y una conexión muerta tardaba eso en
  notarse. El escucha y la prueba usan ahora el mismo resolvedor, que en Darwin
  cae a `0x10`.
- `send.sh` codificaba el nombre de un adjunto con acentos con basura
  (`%FFFFFFFFFFFFC3`) en el bash 3.2 de macOS, que extiende el signo de los
  bytes altos. Ahora enmascara cada byte, y `LC_ALL=C` queda solo dentro de
  `percent_encode()` en lugar de seguir puesto el resto del script.
- La prueba del tipo de archivo desconocido compara la parte adjunta contra lo
  que responde el `file(1)` de cada host, y hay un caso más de nombre UTF-8 con
  caracteres de dos y tres bytes.
- Cuando una prueba falla, `test_listener.py` y `test_roster.sh` imprimen un
  bloque de diagnóstico: versiones de Python, Bash y `file(1)`, las constantes
  TCP que expone Python y las que resuelve el escucha, y el tipo MIME esperado y
  observado. `test_all.sh` ya no oculta la salida de una suite que falla, y le
  agrega ese bloque si la suite no lo trae (PR #148, cierra #129).

**Las pruebas con correo real dejan de bloquear el fin de la instalación.**
Issue #146, a partir del reporte de campo de Marcus Claw-Tob en OpenClaw: con la
instalación ya sana, el agente no la dio por terminada mientras esperaba tres
correos de prueba, y reportó como pendientes dos que nunca se enviaron. El paso
8 de `AGENTS.md` pedía que `INSTALL.md` §7 pasara en su totalidad, y §7 incluía
checks que necesitan que una persona mande correo. Ahora §7 queda con lo que el
agente verifica solo, y los checks 5 y 6d, junto con el párrafo de los tres
mensajes, pasan a un §7.1 opcional. Esas pruebas se ofrecen después de reportar
la instalación terminada, remiten a las del Paso 3 del README y no dan un correo
por faltante si la persona no confirmó que lo mandó. El paso 9 va en el mismo
mensaje que el reporte. `test_docs.py` falla si §7 vuelve a pedir correo de una
persona.

**`AGENTS.md` e `INSTALL.md` siguen el flujo del formulario.** PR #140. «Ask, do
not guess» e `INSTALL.md` §2 le pedían al agente preguntar por chat todos los
datos del buzón. Ahora el formulario es la vía normal para la cuenta, los
servidores, la contraseña y la fila de la persona en `roster.md`. Por chat solo
se pregunta lo que el formulario no cubre, y la ruta del `.env` a mano queda
para quien la elija. El paso 2 de `AGENTS.md` pide mandar la línea `ssh -L`
junto con el enlace, revisando antes el nombre del host, y ya no dice que
`onboard` la imprime solo en el caso remoto: la imprime siempre.

**Las traducciones quedan al día.** PRs #139, #142 y #143. `i18n/README.*` e
`i18n/MAILBOX_SETUP.*` (en-US, es-ES, fr-FR y pt-BR) pasan al README
reorganizado en 0.5.0: «Instalación» con sus tres pasos, «¿Para quién es Paynani?» después,
y los enlaces de `MAILBOX_SETUP` al ancla de «Instalación» de cada idioma. El
prompt de instalación se traduce también al francés y al portugués, con el
original en español en un bloque plegable, como en inglés. `saved.roster_failed`
en esos cuatro idiomas deja de decir que no poder agregarte a `roster.md` es lo
esperado en una instalación nueva.

## 0.5.0 (2026-09-15)

**Configurar paynani ya no pide PHP ni pasa datos por el chat.** 70 commits
desde 0.4.0.

- `scripts/paynani onboard`, en Python puro, reemplaza al formulario en PHP.
  `webapp/` y `scripts/setup_web.sh` se retiraron. El formulario pide también
  tu nombre y tu correo, y crea `roster.md` con tu fila si todavía no existe.
- Dos comandos nuevos: `paynani set`, para cambiar una clave del `.env`, y
  `paynani roster`, para administrar la lista de contactos autorizados.
- El README se reescribió para quien no es técnico y se reorganizó con la
  instalación primero.
- La suite corre también en macOS en CI, y el vigilante de correo de las
  sesiones de Claude Code ya no se queda callado en macOS ni cuando la sesión
  está suspendida.

### Si actualizas desde 0.4.0

Ninguna unidad de systemd, LaunchAgent, hook ni instalador cambió desde 0.4.0.
Basta `git pull` y seguir `UPGRADE.md`, con dos excepciones:

- **Si usabas `scripts/setup_web.sh` o `webapp/`:** ya no existen. Usa
  `scripts/paynani onboard`.
- **En Claude Code, reinicia las sesiones abiertas después del `git pull`.** Una
  sesión que siga corriendo con el vigilante anterior conserva su lock, y el
  vigilante nuevo se niega a armar hasta que esa sesión termine.

### Pendientes conocidos

- **Traducciones.** `i18n/README.*` e `i18n/MAILBOX_SETUP.*` (en-US, es-ES,
  fr-FR y pt-BR) todavía describen el flujo anterior a #131 a #137. Van en #123.
  Mientras tanto, la versión es-MX es la fuente de verdad.
- **`saved.roster_failed` en esos cuatro idiomas** todavía dice que no poder
  agregarte a `roster.md` en una instalación nueva es lo esperado. Desde esta
  versión ya no lo es.
- **macOS.** `suite-macos` falla en `test_listener.py` y `test_roster.sh`
  (#129). Hasta que se arregle, en una Mac el formulario no puede crear
  `roster.md`, porque corre `test_listener.py` antes de escribir, y el agente
  lo crea en el paso 7 de `AGENTS.md`.
- **`paynani roster add` desde la terminal** todavía no crea `roster.md` cuando
  no existe (#135).

**El README se reorganiza para leerse de corrido.** La instalación va primero
y «¿Para quién es Paynani?» después. Los tres pasos y las pruebas quedan más
cortos. La Prueba 1 pide que el agente conteste con el asunto tal como lo ve,
un asunto con acentos, para notar si lee mal los encabezados. La Prueba 2
manda un correo desde una dirección que no está en `roster.md`. Se quitó la
prueba de pedirle al agente que le escriba a una dirección fuera de la lista.
`MAILBOX_SETUP.md` apunta al encabezado nuevo, `#instalación`.

**El formulario de `paynani onboard` crea `roster.md` si todavía no existe.**
Issue #134. En una instalación nueva el formulario corre en el paso 2 de
`AGENTS.md`, antes de que existiera `roster.md`, así que agregar a la persona
fallaba siempre con `roster.md has no contacts table`. Ahora, al guardar, crea
el archivo a partir de `roster.md.example` con la fila de quien llenó el
formulario, con `Type` = `Human`. Un `roster.md` que ya existe nunca se
reemplaza por la plantilla. Si la verificación posterior a la escritura falla,
el archivo creado se borra en vez de quedar vacío. En un roster antiguo sin
columna `Type`, la fila se agrega sin esa celda.

La prueba de punta a punta del formulario creaba `roster.md` antes de enviar,
así que nunca probó una instalación nueva. Ya no lo crea, y hay casos nuevos
para el archivo ausente: creado desde la plantilla, sin archivo si fallan las
pruebas previas o la verificación, y sin tocar un archivo existente sin tabla.

`AGENTS.md` (paso 7) e `INSTALL.md` copian la plantilla solo si `roster.md` no
existe (`[ -f roster.md ] || cp ...`), y `test_docs.py` falla si vuelve a
aparecer una copia sin esa protección. El paso 2 de `AGENTS.md`, el Paso 2 de
`README.md`, `MAILBOX_SETUP.md` y el mensaje `saved.roster_failed` en es-MX
describen el comportamiento nuevo. Los otros cuatro idiomas de ese mensaje y
las traducciones de los documentos van en un cambio aparte.

En macOS, crear el archivo depende de #129: antes de escribir, el formulario
corre `test_listener.py`, que hoy falla en esa plataforma.

**El texto que se le pega al agente en el Paso 1 del README es más corto.** Le
pide seguir `AGENTS.md` y mostrarte el enlace del formulario cuando necesite la
cuenta de correo. Dejó de decir dónde va el `.env` y de prohibir que te pida la
contraseña, porque las dos instrucciones ya están en el paso 2 de `AGENTS.md`.
Sigue partido en líneas de 27 columnas o menos, sin contar la URL, para que
quepa en un teléfono.

**El Paso 2 del README deja de prometer que el formulario siempre te agrega a
`roster.md`.** En una instalación nueva esa lista no existe cuando se llena el
formulario (#130), así que la página avisa que no pudo agregarte. El README
ahora explica ese aviso y dice que el agente te agrega cuando crea la lista, en
el paso 7 de `AGENTS.md`.

**El formulario de `paynani onboard` ya pide también tu nombre y tu correo, y
te agrega a `roster.md` al guardar.** Issue #127: ese dato se pedía antes por
el chat con el agente, en el texto pegado del Paso 1 del README, el mismo
canal que esas mismas instrucciones prohíben usar para la contraseña del
buzón.

El formulario suma dos campos, Tu nombre y Tu correo electrónico, en un
`<fieldset>` separado del de la cuenta del buzón. Al guardar, además de
escribir el `.env`, llama a la misma función que ya usa `paynani roster add`
(#116/#117) para agregar el renglón a `roster.md`, corriendo
`test_roster.sh`/`test_listener.py` antes de escribir y revirtiendo si
alguno falla, igual que UPGRADE.md exige para cualquier cambio al roster. Una
dirección que ya estaba en el roster no rompe el guardado del `.env`: solo se
omite la escritura del roster, y la pantalla de «guardado» lo dice.

README.md y sus 4 traducciones pierden el punto 4 de «Antes de empezar» y el
párrafo del texto pegado del Paso 1 que pedían este dato por chat.
MAILBOX_SETUP.md documenta que la ruta manual (`.env` a mano, sin el
formulario) sigue necesitando un `paynani roster add` explícito, porque esa
ruta no pasa por `server.py`.

**`paynani onboard` ya se detiene solo aunque el `.env` guardado no haya
cambiado de contenido.** Issue #118, encontrado por Julian probando el
formulario manualmente: la condición de parada comparaba una huella del
archivo antes y después, así que reenviar los mismos siete valores ya
guardados, probar el formulario sin cambiar nada, dejaba el proceso corriendo
para siempre pese a que el guardado sí había funcionado.

Ese sondeo de huella era un resabio de `scripts/setup_web.sh`, donde el
lanzador en bash y el servidor PHP son dos procesos separados sin forma de
avisarse. En Python, servidor y lanzador comparten proceso: ahora el propio
manejador que escribe el archivo activa un `threading.Event` justo después de
que la pantalla de confirmación ya salió por el socket, y `onboard.py` se
detiene en cuanto lo ve: sin esperar a que el contenido difiera de lo que
había al arrancar. La comparación de huella se conserva como respaldo.

De paso, un `SIGTERM` (por ejemplo `pkill`, en vez de Ctrl-C) dejaba el
archivo de token de un solo uso sin borrar, porque Python no trata `SIGTERM`
como `KeyboardInterrupt` por sí solo y el `finally` que limpia nunca corría.
Ahora un manejador de `SIGTERM` lo enruta por la misma ruta que ya cubre
Ctrl-C.

**`paynani` gana dos comandos más: `set` y `roster`.** Issue #116, la
continuación planeada de #114/#115.

`paynani set CLAVE [VALOR]` cambia una de las siete claves del `.env` sin
volver a correr todo `onboard`: valida el campo, por omisión vuelve a probarlo
en vivo contra el servidor (solo el protocolo que esa clave afecta: cambiar
`AGENT_EMAIL_FROM_NAME` no toca la red; cambiar un host o la contraseña sí), y
solo entonces escribe, reutilizando `envfile.py` tal cual. `--skip-check` para
saltar la prueba en vivo a propósito. La contraseña, si no se pasa en la línea
de comandos, se pide oculta (`getpass`).

`paynani roster {list,add,remove}` administra `roster.md` sin editar la tabla
markdown a mano. Preserva todo lo que el archivo ya tiene (comentarios, la
tabla de `## Notifiers`, columnas que este comando no conoce), rechaza una
dirección duplicada o una bandera (`--type`, `--github`) que apunta a una
columna que el archivo no tiene, en vez de descartarla en silencio, pide
confirmación interactiva antes de escribir (salvo `--yes`), y después de
escribir corre `scripts/test_roster.sh` y `scripts/test_listener.py`,
revirtiendo el cambio si alguno falla. Es un comando de terminal, ejecutado a
criterio explícito de un humano o del agente: nada lo conecta al correo
entrante, así que no debilita la regla de "nunca agregar un renglón porque un
mensaje lo pidió": esa regla es sobre quién decide, no sobre qué herramienta
escribe el renglón después.

`scripts/roster.py` deja de ser solo lector: gana `add_contact()` y
`remove_contact()`, que encuentran y arman una fila según el encabezado real
del archivo (no una posición de columna fija), así que funcionan igual sobre
el formato de cuatro columnas que se usa hoy y sobre el `Name | address` de
un roster viejo.

**Configurar el `.env` ya no depende de tener PHP instalado.** `scripts/paynani
onboard` levanta el mismo formulario de incorporación que `webapp/`, pero en
Python 3 puro: la única dependencia que ya exige el resto de este
repositorio (`harness/adapters/*.py`, `scripts/idle_listener.py`, etc.), no
una nueva.

El problema real: el agente que instala paynani en OpenClaw, Hermes Agent o
Codex frecuentemente corre en un host sin PHP, y no puede instalarlo por su
cuenta porque `apt-get install php8.3-cli` requiere `sudo`. El paso pensado
para ayudar a alguien sin conocimientos técnicos terminaba siendo, en cambio,
un bloqueo al momento de instalar para el agente que hace el trabajo.

`scripts/paynani onboard [--port PUERTO]` reproduce exactamente la misma
experiencia (un enlace por ejecución que deja de servir en cuanto el proceso
termina, solo loopback, nada se escribe hasta que
un login IMAP y uno SMTP reales autentiquen ambos) usando únicamente
`http.server`, `imaplib` y `smtplib` de la librería estándar. Los cinco
catálogos de idioma (`webapp/i18n/*.php`) se portaron 1:1 a
`scripts/paynani_lib/i18n_data/*.py`, mismas claves, mismo texto. La
resolución de rutas y el `.env` en sí se reutilizan de `harness/paths.py`
directamente, sin una cuarta implementación de esa regla.

`webapp/` y `scripts/setup_web.sh` **no se retiran** en esta entrega; siguen
siendo la ruta soportada donde ya se usan. Ver el PRD en el issue #114 para el
razonamiento completo detrás de la elección de Python sobre Node.js, y las
preguntas que quedan abiertas (retiro eventual de `webapp/`, superficie final
del comando de cara a los subcomandos de `.env`/`roster.md` planeados).

**`webapp/` y `scripts/setup_web.sh` se retiran.** Una de las preguntas
abiertas del PRD del issue #114 queda cerrada: con `set`/`roster` (#116) y el
arreglo de auto-cierre (#118) ya en `main`, y con la prueba conjunta entre
Julian y el agente sobre `paynani onboard` completada sin encontrar más
diferencias de comportamiento contra el formulario en PHP, ya no hace falta
mantener las dos implementaciones en paralelo.

Se borra `webapp/` completo (`index.php`, `lib/*.php`, `i18n/*.php`,
`README.md`) y `scripts/setup_web.sh`, el lanzador en bash. Los dos archivos
que `paynani onboard` sigue sirviendo en vivo, `app.css` y `lang.js`, se
mueven a `scripts/paynani_lib/assets/` en vez de borrarse con el resto; server.py
ya no depende de ninguna ruta bajo `webapp/`.

`scripts/test_paths.sh` deja de comprobar `webapp/lib/paths.php` como tercera
implementación de la regla de rutas: ahora son dos (Python y shell), no tres.
Toda mención a `scripts/setup_web.sh` como ruta alterna al formulario (en
`AGENTS.md`, `README.md`, `MAILBOX_SETUP.md`, `INSTALL.md` y sus cuatro
traducciones) se actualiza a `scripts/paynani onboard`, y el párrafo entero
sobre necesitar PHP y `sudo`/`apt-get` desaparece: ya no hay una ruta que
dependa de eso.

**El vigilante de correo de las sesiones de Claude Code deja de afirmar que otra
sesión está vigilando cuando no es cierto.** #109 y #111, que cierran #105, #62
y #110. `harness/session_watch.sh` fallaba en dos direcciones. En macOS no hay
`flock`, así que toda sesión salía sin armar diciendo que otra ya vigilaba. En
Linux, un vigilante cuya sesión estaba suspendida seguía avanzando el cursor, y
ese correo se daba por visto sin que nadie lo hubiera visto.

Ahora el lock es un `mkdir` que guarda el pid del vigilante y el de su sesión.
La sesión se busca recorriendo los ancestros, porque el proceso padre es un
envoltorio del harness que sigue sano aunque la sesión esté suspendida. Un
dueño muerto o suspendido se releva, deteniendo antes a su vigilante huérfano,
y el cursor deja de avanzar en cuanto la sesión ya no puede mostrar nada. Donde
existe `flock`, el lock de la versión anterior se sigue respetando durante una
actualización.

**Las pruebas dejan de asumir Linux.** #106 y #107, destapados por el job de
macOS. `test_preflight.sh` no compilaba con bash 3.2, `test_paths.sh` comparaba
rutas temporales sin resolver que en macOS `/var` es `/private/var`,
`test_hermes_install.py` esperaba códigos de salida de Linux, y
`test_install.sh` usaba `stat -c %a`, que el `stat` de BSD no entiende. Ninguno
tocaba código de producto. #108 agrega `scripts/test_install_macos.py`, que
prueba la instalación con `launchd` en un sandbox con `launchctl`, `himalaya` y
`openclaw` falsos.

**La suite corre también en macOS, en CI.** #104. Un job `suite-macos` corre
las mismas suites en `macos-latest` y compara el conjunto de las que se saltan
contra el esperado, `test_install.sh`, para que una suite que empiece a
saltarse no pase por verde. El job solo reporta y no bloquea un merge; el
criterio para volverlo requerido quedó escrito en #129. El job de Linux se
renombra `suite-linux`.

**El README dejó de ser mitad puerta humana y mitad manual del agente.** Catorce
commits desde 0.4.0, todos de documentación: ninguna línea de código cambió.

### El diagnóstico no era la prosa, era el vocabulario

El README anterior estaba bien escrito y era correcto. Seguía siendo ilegible
para alguien sin formación técnica, y eso no se arregla escribiendo mejor:

```
22 términos especializados · ~90 apariciones · 1,738 palabras de prosa
                                  ≈ una pieza de jerga cada 19 palabras
```

Las tres más pesadas caían en las primeras 40 líneas sin explicarse nunca:
`harness` once veces, `roster` quince, `runtime` tres. Nadie fuera de este
proyecto sabe qué es un *harness*, así que quien no es técnico lo topaba en la
línea 23 y concluía, en silencio, que la página no era para él.

Medido después del cambio, la jerga baja de **39 apariciones a 12**. Las que
quedan son nombres literales de archivo o viven dentro de un bloque plegable.
`harness` ahora se presenta antes de usarse; `journal` pasó a «se anota en
disco», `cursor` a «solo marca una como entregada cuando el agente confirma», y
`UIDVALIDITY` a «se revisa que el buzón siga siendo el mismo».

### La mecánica interna bajó de la portada

El diagrama de tubería con `state/events.jsonl` se fue, y en su lugar quedaron
tres frases en español llano más el enlace a `DESIGN.md`, que ya explicaba todo
eso con mucho más cuidado del que cabe en un README. Un diagrama de *pipeline*
arriba es una señal de «esto no es para ti».

Los nombres exactos de las cuatro unidades de systemd **no se perdieron**: se
movieron a un `<details>` plegable. La lista visible de «Qué cambia en la
computadora» dice ahora *dos servicios que quedan corriendo y se reinician
solos*, y quien necesite `paynani-logrotate.timer` lo abre.

### Lo que la reescritura borró, y volvió

Este trabajo salió en cinco vueltas, y en el camino se borraron cosas que había
que devolver: la sección de consentimiento con las unidades y la regla permanente
que se agrega a las instrucciones del agente, el aviso de que `git clean -xdf`
se lleva la contraseña del buzón, el mecanismo de actualización completo, toda
referencia a `UNINSTALL.md`, y el pie que declara cuál idioma gana.

Dos se recuperaron al final y son las más humanas del documento: el párrafo de
apertura, y la etimología náhuatl completa, que había quedado en tres líneas. Que
la sección menos técnica del README sea también la más legible para quien no es
técnico no es casualidad.

### Las cuatro traducciones no estaban atrasadas

Estaban traduciendo un documento que ya no existe. Las cuatro conservaban
`Arquitectura de entrega por entorno` y `Rutas en esta máquina`, secciones que la
reescritura eliminó, así que se reconstruyeron enteras en vez de parchearse.

Esa reconstrucción trajo una restricción que las traducciones antes no tenían: la
reducción de jerga **es** el cambio, y en inglés `harness`, `listener`,
`dispatcher`, `journal`, `cursor` y `runtime` son las palabras naturales. Una
traducción fiel las repone sola y deshace el trabajo sin que nadie lo note. Las
cinco versiones quedaron medidas entre 12 y 15 términos.

### Sobre `blader/humanizer`

Se evaluó el skill para este objetivo y no era la herramienta. Quita señales de
escritura de IA (contrastes no-X-sino-Y, cierres de una línea, tríadas forzadas,
rayas largas como conector) y el README ya pasaba casi limpio: **0 rayas largas,
0 no-X-sino-Y, 0 comillas curvas**. Sirve como pasada de acabado, no como el
arreglo. Sus listas de palabras además son de inglés, así que sobre una fuente
es-MX solo transfieren los patrones estructurales.

### Lo que sigue pendiente

La prueba que de verdad cuenta no se ha hecho: dárselo a leer a alguien no
técnico y ver en qué renglón se detiene. Todo lo anterior son proxies.

## 0.4.0 (2026-09-07)

**`main` ya no depende de que nadie se acuerde de correr las pruebas.** 30 commits
desde 0.3.0.

Hasta esta versión la disciplina existía y funcionaba (todo entraba por PR, la
suite se corría) pero nada la obligaba. Ahora hay una compuerta: cada PR y cada
commit que llega a `main` corren la suite completa en GitHub Actions, y `main`
está protegida requiriendo que ese check pase. Un PR con una prueba rota ya no se
marca en rojo y se fusiona igual: no se puede fusionar.

**Si tu instalación corre sobre Codex, hay un paso que sí tienes que dar.**

```
scripts/codex_hook.py --install
```

El hook declaraba un timeout de 15 s para `SessionEnd` y Codex lo topa a 3, así
que imprimía una advertencia amarilla en cada arranque de sesión. Ya declara 3.
Pero **el arreglo no llega solo a un host que ya tiene el hook instalado**: hay
que volver a correr `--install`, que ahora converge un hook existente en lugar de
limitarse a no duplicarlo. Sin ese paso la advertencia sigue saliendo con el
código nuevo.

Fuera de ese caso basta `git pull`. No hay estado que migrar.

### Correo sustantivo, sin salirse de la compuerta

`scripts/send.sh` acepta `--html` y construye `multipart/alternative`, con
adjuntos o sin ellos. Antes, un correo que por política tenía que salir en HTML
tenía que mandarse con otra herramienta, y eso significaba **sin validación
contra `roster.md`, sin registro en `state/sent.log` y sin rechazo de
destinatarios fuera de lista**. La política de formato y la compuerta de correo
eran excluyentes; ya no lo son.

La parte HTML sale en `quoted-printable`, no en `8bit`. No es un detalle de
estilo: RFC 5321 limita una línea a 998 octetos y el HTML de correo real la pasa
con facilidad, porque los estilos van en línea. Una línea larga la rechaza el
servidor o, peor, la parte a media declaración y el lector recibe HTML roto sin
error en ningún lado.

### Una sesión que no pudo armar el watch ahora se entera

En `claudecode`, cuando otra sesión ya tenía tomado el spool, el aviso salía por
stderr, que desde el harness va a un archivo que nadie abre. La sesión veía
`Monitor ended without producing output (exit 0)`, indistinguible de un buzón
tranquilo, y creía que había armado el watch cuando no lo había hecho. Ahora sale
por stdout, que es el canal que sí notifica.

Es la primera mitad del arreglo. La segunda, distinguir un dueño vivo del lock de
uno huérfano o suspendido, sigue abierta.

### Un fallo viejo deja de anunciarse para siempre

Un solo renglón heredado en `state/dispatch.err.log`, escrito antes de que
existiera el prefijo de rutina, dejaba el aviso de fallos encendido de forma
permanente: cada sesión arrancaba anunciando un problema que no existía, en un
host donde el dispatcher entregaba bien. Ahora el corte es temporal: solo cuentan
los renglones posteriores al arranque actual del dispatcher, porque un fallo de un
proceso que ya murió no describe al que está corriendo.

Un host que grita PROBLEMS en cada arranque enseña a ignorar el aviso, y ese
hábito es el que hace peligrosa la advertencia que sí importe.

### La suite tiene un punto de entrada, y no es el que parecía

```
scripts/test_all.sh
```

**No uses `python3 -m unittest discover`.** Solo cuatro de los archivos de prueba
definen clases `unittest.TestCase`; los otros siete son scripts de aserciones. La
detección automática no puede correrlos: seis salen en el import y se reportan
como errores (`FAILED (errors=6)` en un árbol sano, en cualquier runtime) y el
séptimo importa limpio y no aporta ninguna prueba. Las dos mitades son el cargador
opinando sobre una suite que no corrió. Dos personas llegaron a `discover` por
reflejo, en runtimes distintos, antes de que existiera este script.

### Clona el tag, no `main`

`INSTALL.md` decía `git clone <this repo>`, que entrega `main`. Tres instalaciones
de campo seguidas se llevaron código sin publicar sin haberlo decidido. Ahora la
instrucción nombra el tag y explica cómo obtenerlo:

```
git tag --sort=-v:refname | grep -v -- '-rc' | head -1
```

El `grep` no es adorno: los candidatos de release ordenan por encima del release
que preceden, así que sin él la línea entregaría un `rc` a quien pidió un release.

### `MIGRATION.md`, para quien viene de agenteiamail

Documento nuevo, escrito por quien hizo esa migración en su propio host. Cubre lo
que sobrevive al renombre y estorba después: la cuenta vieja de Himalaya que sigue
siendo la predeterminada, las instrucciones vivas que apuntan al script de envío
anterior, y las unidades de systemd que systemd recuerda aunque su archivo ya no
exista.

Separa además tres caminos que la documentación trataba como uno: instalación
limpia, actualización de paynani, y migración por renombre.

### `MIGRATION.md` ya no puede dar un falso limpio

El paso que busca instrucciones viejas usaba `rg` con `2>/dev/null`. ripgrep no es
parte de una instalación base en ningún lado, ni en macOS ni en un Ubuntu
mínimo, y este repositorio no lo exige; silenciar stderr encima es lo que lo
volvía peligroso en vez de meramente ausente. En un host sin ripgrep la línea
imprimía **nada**, y en esa sección nada se lee como «no quedan instrucciones
viejas». Alguien tacharía el paso con el heartbeat todavía apuntando a un
`send.sh` que ya no existe, que es exactamente el residuo que el paso existe para
atrapar. Ahora es `grep -rn`, y los errores se ven.

### Un listener sin supervisor observable ahora tiene pulso

`healthcheck.py` preguntaba por la unidad y trataba cualquier respuesta que no
fuera `active` como una parada. En un host donde la unidad **no se puede
consultar** (sin systemd observable, sin launchd) eso convertía «no sé» en «está
caído», y el reporte gritaba un problema que nadie podía arreglar porque nunca
existió. Ahora `unknown` se declara como lo que es: estado desconocido, no
detenido.

Eso deja un hueco real: si nadie puede consultar la unidad, ¿cómo se sabe que el
listener sigue vivo? Con su propio pulso. El listener escribe `heartbeat_at` en su
estado al cerrar cada ciclo de IDLE, y el chequeo lo usa cuando la unidad no es
consultable. El umbral son 15 minutos, deliberadamente más ancho que el refresco
de IDLE de cinco, para que un ciclo lento no se reporte como falla y un proceso
muerto sí se vea dentro de la misma sesión.

Y distingue dos cosas que se veían iguales y piden lo contrario: un listener
muerto y uno vivo que no alcanza el servidor. Si el pulso está viejo pero
`idle.err.log` se sigue escribiendo, el proceso está corriendo y reintentando, y
el reporte lo dice con todas sus letras, «reiniciarlo no va a ayudar», en vez de
mandar a alguien a reiniciar un servicio que ya está arriba. Un pulso viejo sin
bitácora de errores reciente sí es la otra: probablemente muerto, en un host sin
supervisor que lo levante.

### `version.sh` deja de creerle a un cache vencido

El cache de `--line` se refrescaba solo por tiempo, y eso abría una ventana en la
que la respuesta era falsa sin decirlo: un `git pull` que cambia `VERSION` es la
evidencia más fuerte de que el panorama de tags también se movió, y es justo el
momento en que el dato guardado se vuelve peligroso. Pasó (#61): la línea le dijo
a un agente que iba ADELANTE de un tag publicado dos versiones antes, y la sesión
entera se fue recomendando un tag que ya existía. Ahora el cache se invalida
también cuando la versión instalada cambia.

Lo que el cache no puede arreglar, ahora lo declara. La respuesta puede seguir
teniendo hasta un día de vieja, evitar un chequeo de red por sesión es para lo que
existe, pero ya no se presenta como un hecho fresco: la línea trae su edad,
`[from a check 20h ago]`. Un agente al que le dicen «el tag más nuevo es X» lee un
hecho; uno al que le dicen «según un chequeo de hace 20 horas» sabe que puede
preguntar.

La versión instalada se guarda en una **segunda línea**, no en un tercer campo de
la primera. Un tercer campo se ve más limpio y rompe la versión anterior: su
lector es `read -r stamp cached`, y con dos variables la segunda se queda con todo
el resto del renglón, así que `cached` regresaba como `"0.3.0 0.3.0"`. Ese es un
camino de rollback real (un host de campo probando un release candidate, o dos
clones compartiendo `PAYNANI_STATE`, que es como se encontró). `read` se detiene
en el primer salto de línea, así que un paynani viejo lee la línea 1 y nunca se
entera de que hay una línea 2.

### macOS ya no reprueba el chequeo de versión para siempre

`timeout` es de GNU coreutils y macOS no lo trae. Envolver la llamada remota en un
comando que no existe hacía que **toda** instalación de macOS fallara este chequeo
de forma permanente y silenciosa: `could not find out` se lee como un tropiezo de
red pasajero, así que nadie lo investiga, y el chequeo de versión queda muerto por
el resto de la vida del host (#68, hallado por Ximena en la primera instalación
sobre macOS).

Ahora degrada sin el techo cuando no hay `timeout` (o usa `gtimeout`, que es el
mismo programa cuando Homebrew instaló coreutils). Es el intercambio correcto:
`GIT_TERMINAL_PROMPT=0` es la protección que importa y esa sobrevive, y un chequeo
que funciona sin cota superior le gana a uno que siempre falla.

### La suite deja de escribir en el `sent.log` vivo

`test_roster.sh` corría contra el directorio de estado real, así que en un host
con instalación viva las pruebas ensuciaban el registro de envíos de producción.
Ahora redirige `PAYNANI_STATE` a un temporal y, al final, **afirma** que el
`sent.log` vivo no creció ni un byte. La prueba de que la suite no toca lo vivo es
parte de la suite.

### La apertura del README, y las cuatro traducciones

La apertura se reescribió para decir qué es paynani antes de decir cómo se
instala, se corrigieron tres defectos de ese texto y un posesivo que cambiaba el
sentido (el agente lee **su** correo, no el tuyo), y las cuatro traducciones de
`i18n/` se pusieron al día con el español.

### El flujo de release candidate, documentado

`INSTALL.md` describe ahora qué es un tag `-rc<N>`, por qué existe y qué debe
reportar de vuelta el host que lo instala. Existe porque CI prueba menos de lo que
parece: la suite finge `himalaya`, así que un verde dice que el mensaje está bien
formado y no dice nada sobre si un proveedor real lo acepta. En `agenteiamail` ese
hueco dejó pasar dos bugs, un `From:` faltante y un rechazo `554 spam`, que solo
aparecieron en un host vivo.

**Esta versión salió primero como `v0.4.0-rc1`, y el proceso hizo su trabajo.**
El candidato destapó en hosts vivos lo que la suite no podía ver: el chequeo de
versión muerto en macOS, el listener sin supervisor observable reportado como
caído, y el cache que aseguraba una versión publicada dos releases antes. Los 15
commits que siguieron al tag son esos arreglos, y por eso `v0.4.0` **no** cae en
el mismo commit que el candidato: cae en `main`, con ellos adentro. Un final que
se publicara en el commit del rc dejaría fuera justo lo que el rc sirvió para
encontrar.

### Y lo que aprendimos de la primera instalación sobre Hermes

El reporte de campo de Atenea Buffay-Hermes dejó cuatro cambios en la
documentación, con su autoría. El más útil no fue un dato que faltaba sino una
frase que hacía trabajo que nadie leía: el paso 7 de la verificación dice "el
gateway **de prueba**", y esa palabra significa una instancia dentro de la cual no
estás corriendo. Un agente hospedado por el gateway bajo prueba no puede ejecutar
ese paso: tendría que detener el proceso que lo observa. En un host de un solo
gateway, ese paso es del operador.

## 0.3.0 (2026-09-06)

**paynani entrega a OpenAI Codex, y sabe despertar una sesión que está viva.** 23
commits desde 0.2.0.

Hasta ahora el correo llegaba a un harness que ya estaba mirando. Codex no mira:
solo lee su contexto en un evento de sesión, así que un mensaje que entraba a
media sesión esperaba a la siguiente. Esta versión cierra las dos mitades: el
dispatcher encola contra la sesión viva con `codex queue`, y lo que entró con la
sesión cerrada se repone al arrancar, ya no como contexto informativo sino como
trabajo que hay que atender.

**Si tu instalación corre con `PAYNANI_RUNTIME=auto`, lee esto antes de jalar.**
El dispatcher no elige entre runtimes: si en este host ahora se detecta también
el binario de `codex`, `auto` encuentra dos, se niega a adivinar y el servicio no
arranca. La salida lo dice con esas palabras. El arreglo es nombrar el runtime en
`runtime.env`, que es por instalación y no viaja en el repo:

```
PAYNANI_RUNTIME=claudecode
```

Fuera de ese caso basta `git pull`. No hay estado que migrar: los registros
nuevos de `state/codex.spool` se escriben como JSON de una línea con su
`event_id`, y los que ya estaban en texto plano se siguen reponiendo por el
camino de respaldo. En un host de Codex falta registrar los hooks una vez con
`scripts/codex_hook.py --install`.

- **La reposición de Codex ya exige atender el correo repuesto**
  ([#53](https://github.com/iaaorgmx/paynani/issues/53)).

  Cuando `SessionStart` repone líneas desde `state/codex.spool`, ahora emite un
  `systemMessage` aunque el journal ya no tenga backlog pendiente, y ese aviso
  se compone con fallas del listener o dispatcher en vez de perder contra ellas.
  Los nuevos registros de `codex.spool` conservan el `event_id` junto a la
  notificación renderizada, y el replay agrupa esos ids en una sola instrucción
  compartida con la ruta viva de `codex queue`, para no rebasar el límite de
  contexto ni repetir los mismos correos en cada arranque. Las líneas antiguas de
  texto plano siguen funcionando con resolución perezosa contra los últimos
  candidatos del journal. Cada correo de roster sigue siendo trabajo pendiente
  hasta verificarlo y leer o descartar deliberadamente el cuerpo exacto.
  `healthcheck.py` aclara la misma frontera: el offset de `codex.spool` significa
  que la sesión recogió el replay, no que el agente ya leyó o respondió el
  correo.

- **Codex puede despertar una sesión viva con `codex queue`**
  ([#48](https://github.com/iaaorgmx/paynani/issues/48)).

  El hook `SessionStart` registra el `session_id` documentado por Codex en
  `state/codex.session`, y `SessionEnd` lo borra para no apuntar a un thread
  muerto. El dispatcher sigue escribiendo primero en `state/codex.spool`, pero
  ahora encola una instrucción fija que nombra solo el `event_id`; si Codex la
  acepta, avanza `state/codex.offset` para que la reposición no duplique el
  correo. Si no hay sesión viva, `PAYNANI_CODEX_MODE=agent` puede arrancar el
  respaldo con `codex exec`, apagado por omisión.

- **La reposición de Claude Code ya no salta correo en silencio.** Antes mostraba
  los 20 renglones más recientes del spool y armaba el watch al final del
  archivo, así que con un rezago mayor a 20 los más viejos quedaban acusados sin
  que nadie los hubiera visto. Ahora drena del más viejo al más nuevo y acusa
  solo hasta el último renglón efectivamente mostrado: el resto sigue pendiente y
  llega por el watch. El arreglo salió del runtime de Codex y aplica a los dos.

- **OpenAI Codex entra como runtime `codex`**
  ([#44](https://github.com/iaaorgmx/paynani/issues/44)).

  La entrega sigue el modelo conservador de los runtimes que jalan: el dispatcher
  escribe una línea durable en `state/codex.spool`, con `fsync`, y solo entonces
  avanza el cursor. `ACCEPTED` significa *spooled, not seen*: ninguna sesión viva
  de Codex queda probada por esa escritura.

  La sesión se entera mediante un hook `SessionStart` registrado aparte con
  `scripts/codex_hook.py --install`, que mezcla en `~/.codex/hooks.json` sin
  reemplazar hooks ajenos y hace copia de respaldo antes de tocar un archivo
  existente. Esta primera versión no usa `codex queue`: el correo que llegue a
  media sesión espera al siguiente startup, resume, clear o compact.

  También se agregó `~/.codex/workspace/.env` a los tres resolutores de rutas, el
  soporte de `scripts/install.sh --runtime codex`, el reporte de healthcheck para
  `codex.spool`, documentación y `scripts/test_codex.py`.

- **La página de configuración del buzón no llevaba la marca.** Ahora abre con el
  logotipo, y sale de `brand/` sin que exista una segunda copia del dibujo.

  Enlazarlo no era opción: `brand/` vive al principio del clon, fuera del docroot
  de la página, y sobre todo `guard.php` sirve `default-src 'none'` sin `img-src`,
  así que un `<img>` quedaría bloqueado. Aflojar esa política para poner una
  imagen en un formulario que recoge una contraseña habría sido el peor de los
  intercambios. El SVG se inserta en línea (`webapp/lib/brand.php`, con lista
  blanca de nombres), y el marcado en línea no es un recurso que se descargue, así
  que no necesita ninguna directiva.

  Insertarlo además resuelve el tema oscuro. Los archivos de `brand/` llevan sus
  colores como atributos de presentación, que es lo correcto cuando el SVG se abre
  solo; una regla de CSS gana sobre eso, así que `app.css` repinta `.voluta` con
  `--accent` y `.logotipo` con `--ink` y el logotipo sigue al tema sin una segunda
  versión del archivo. Las dos clases se agregaron a los doce SVG y quedan
  documentadas en `brand/README.md` como lo que son: un punto de agarre, no
  decoración.

- **El listener podía quedarse ciego sin que nada lo dijera**
  ([#37](https://github.com/iaaorgmx/paynani/issues/37), en
  [#39](https://github.com/iaaorgmx/paynani/pull/39) y
  [#41](https://github.com/iaaorgmx/paynani/pull/41)). Detrás de un NAT, WSL2, o
  casi cualquier router doméstico, una conexión IMAP ociosa se descarta sin FIN.
  De este lado el socket se sigue viendo `ESTAB` hasta que alguien intenta
  escribir, así que el listener se quedaba bloqueado esperando un `EXISTS` que ya
  no podía llegar: proceso vivo, socket sano, cero errores en el log, y el correo
  dejando de llegar. Un buzón tranquilo y un listener ciego dan exactamente la
  misma señal, que es la razón de ser de este proyecto al revés.

  Nada sondeaba la conexión porque dos cosas se combinaban: el socket se abría
  sin `SO_KEEPALIVE`, así que el kernel nunca preguntaba al otro extremo, y
  `IDLE_REFRESH` estaba en 25 minutos (número que no es solo cada cuánto se
  reemite IDLE, es cuánto puede durar una conexión muerta sin que nadie se
  entere). Ahora el socket pide keepalive al conectarse, con sondas a los 60
  segundos, y `IDLE_REFRESH` bajó a 5 minutos.

  El arreglo se completó en dos pasos porque el primero estaba incompleto de una
  manera que no se veía. Pedía `TCP_KEEPIDLE`, `TCP_KEEPINTVL` y `TCP_KEEPCNT`
  consultando cada nombre antes de usarlo, con el comentario correcto de que
  macOS no expone `TCP_KEEPIDLE`. El diagnóstico era bueno; la conclusión no:
  **macOS sí tiene ese temporizador, se llama `TCP_KEEPALIVE`**, y no se pedía.
  En un Mac quedaba `SO_KEEPALIVE` encendido con el ocioso del sistema, dos
  horas, o sea ninguna sonda dentro de una ventana útil y toda la protección
  recargada en el `IDLE_REFRESH`. No era catastrófico, era silencioso, que es
  justo lo que esta función existe para eliminar. `scripts/install_macos.py` son
  328 líneas: macOS es un objetivo soportado, no hipotético.

- **`send.sh` no sabía adjuntar archivos**
  ([#38](https://github.com/iaaorgmx/paynani/issues/38), en
  [#40](https://github.com/iaaorgmx/paynani/pull/40)). Armaba un `text/plain` de
  una sola parte y nada más. Cuando Zeus Claude-Tob mandó su reporte de campo
  sobre la instalación, no pudo adjuntar el documento: lo pegó completo en el
  cuerpo y explicó por qué. Con texto se sobrevive; con una captura o un PDF no
  hay salida.

  Ahora acepta `--attach <ruta>`, repetible, en el orden en que se den. **Sin
  `--attach` el mensaje no cambia en absoluto** (mismos encabezados, mismo orden,
  una sola parte), y eso es lo primero que asegura la suite, porque todos los
  envíos que este proyecto hace hoy son ese mensaje. Con adjuntos pasa a
  `multipart/mixed` y el cuerpo se vuelve la primera parte. El tipo sale de una
  tabla de extensiones primero y de `file --mime-type -b` para el resto, porque
  `file(1)` no acierta en varios de los formatos que este proyecto manda a diario.

- **El manual de marca no decía cómo decidir fuera de la lista**
  ([#27](https://github.com/iaaorgmx/paynani/issues/27), en
  [#42](https://github.com/iaaorgmx/paynani/pull/42)). Las reglas decían qué no
  hacer; faltaba con qué criterio resolver un caso que no estuviera en la lista.
  Los ocho criterios ya se habían decidido, pero vivían sólo en el issue: el
  isotipo es un trazo y no una silueta (no se rellena ni se encierra, porque el
  encierro es justo lo que la voluta está dejando atrás), hay un solo acento, el
  nombre es la otra mitad de la marca, el resguardo de `2x` es un mínimo y no un
  objetivo, y la cita no se disfraza de greca.

  Con eso queda también el `social preview` a 1280 × 640 en `brand/`, y junto a
  él el HTML del que sale, para que volver a generarlo no dependa de recordar
  cómo se hizo.

## 0.2.0 (2026-09-04)

**paynani estrena marca, su página de configuración habla cinco idiomas, y el
resolutor de rutas de PHP quedó aislado en su propio archivo.** 51 commits desde
0.1.0.

Basta `git pull`. Ninguna ruta que una unidad de systemd nombre cambió de sitio,
no hay estado que migrar, y los archivos nuevos (`brand/`, `webapp/lib/paths.php`,
`webapp/i18n/`) llegan con el propio pull.

- **El resolutor de rutas de PHP arrastraba media aplicación**
  ([#33](https://github.com/iaaorgmx/paynani/issues/33)). Preguntar en PHP dónde
  vive el `.env` obligaba a cargar el catálogo de idiomas, el control de acceso
  del formulario, la sesión y el CSRF: `envfile.php` y `guard.php` requerían
  `i18n.php`, y las cinco funciones de resolución estaban repartidas entre esos
  dos archivos. En Python basta `harness/paths.py` y en shell basta
  `scripts/envpath.sh`; la tercera implementación de la misma regla era la única
  que no se podía leer sola.

  Ahora viven juntas en `webapp/lib/paths.php` (`home_dir()`, `install_root()`,
  `state_dir()`, `recorded_env()`, `env_path()`, más `HARNESS_ROOTS`,
  `HARNESS_ENV_RELATIVE` y `ENV_BASENAME`) y ese archivo **no requiere nada**. No
  es higiene: es lo que le permite ser comparable por sí solo con las otras dos,
  que es exactamente lo que `test_paths.sh` afirma 151 veces.

  `guard.php` se queda con loopback, llave, CSRF, cabeceras y sesión;
  `envfile.php` con leer, sanear, renderizar y escribir. Los dos siguen
  requiriendo `i18n.php`, y eso es deliberado: `require_loopback()` y
  `write_env()` traducen mensajes que lee alguien que está entregando la
  contraseña de su buzón. Lo que se corta es que el resolutor lo heredara.

- **`scripts/test_paths.sh` comparaba rutas contra un php muerto.** La suite cayó
  a 131 de 151 y los veinte fallos decían «php agrees with python» con la ruta
  esperada de un lado y la cadena vacía del otro. No era un desacuerdo de rutas:
  el `require_once` de `i18n.php` no encontraba su archivo en el clon de prueba,
  que copiaba sólo `envfile.php` y `guard.php`, php moría, y la comparación
  leía ese vacío como una ruta que no coincide.

  Se arregló la copia y, sobre todo, el silenciado: la invocación descartaba
  stderr con `2>/dev/null`, y eso convertía «este archivo no carga» en «este
  archivo resuelve la cadena vacía», que manda a buscar el problema al lado
  equivocado. Ahora, si la salida no es una ruta absoluta, se devuelve el error
  para que aparezca en la línea `actual:`. Sin eso, el mismo fallo se vuelve a
  esconder la próxima vez que alguien agregue un `require`.

- **paynani estrena identidad visual**
  ([#27](https://github.com/iaaorgmx/paynani/issues/27)). El isotipo es **la
  voluta**: la voluta de la palabra con que los códices dibujan el habla saliendo
  de la boca, en trazo de grosor parejo con puntas redondas.

  `brand/` trae catorce archivos, porque la marca se ve en un favicon de 16 px,
  en el avatar de la organización y en la cabecera del README, y cada sitio pide
  una pieza distinta. La **versión reducida**, el mismo trazo sin el rizo
  interior, existe porque por debajo de 32 px el rizo se cierra y queda una
  mancha. El logotipo va **en curvas**, así que ningún archivo depende de tener
  una fuente instalada; las curvas vienen de Spectral Medium, bajo SIL Open Font
  License 1.1, cuyo texto se incluye en `brand/OFL-Spectral.txt`.

  `webapp/assets/app.css` se realineó: el acento pasa de jade `#2f5d50` a grana
  cochinilla `#8f2d2b` (`#d8887f` en oscuro). El cambio no era de una línea. Con
  jade, el acento y el rojo de error estaban a dE76 65.4; con grana quedaban a
  7.7, y en pantalla el botón «Verificar y guardar» y el panel «No se pudo
  conectar» pasaban a ser el mismo rojo. Mover el error hacia el naranja lo
  acercaba al ámbar de aviso, de dE 29.8 a entre 9.8 y 20.8 en oscuro, así que
  la salida fue sacar el acento del botón primario y ponerlo en tinta. El único
  rojo saturado de la página vuelve a ser el error; `--ok`, `--bad` y `--warn`
  quedan intactas.

  El `# paynani` de texto del `README.md` y de sus cuatro traducciones se cambia
  por el logotipo, dentro de un `<h1>` y con `alt="paynani"`, no se pierde ni el
  encabezado de primer nivel ni el nombre para quien usa lector de pantalla, y
  envuelto en `<picture>` con `prefers-color-scheme`, porque el logotipo normal
  tiene el texto en tinta y sobre el tema oscuro de GitHub no se ve.

- **El prompt del Paso 2 no cabía en la pantalla de un teléfono.** Las vallas de
  código no envuelven líneas, nunca, así que una línea de 78 caracteres se
  cortaba donde terminaba la pantalla y el resto quedaba detrás de un
  desplazamiento horizontal que casi nadie descubre. Justo el texto que el README
  pide copiar entero era el que no se podía leer entero.

  Se reenvolvió a 32 columnas en los cinco idiomas, sin cambiar una palabra: como
  se pega en un chat, dónde parta la línea no significa nada. Se conserva la
  valla a propósito (un blockquote envolvería solo, pero perdería el botón de
  copiar, que en un texto cuyo único uso es copiarse es lo que más sirve). La
  única línea que sigue midiendo 35 es la URL del repositorio, que no se puede
  partir y que a 360 px entra completa igual.

- **La página de configuración del buzón habla cinco idiomas.** Quien llena el
  formulario no siempre es quien eligió el idioma del resto de la instalación, y
  está entregando la contraseña de un buzón: tiene derecho a leer en su idioma lo
  que está aceptando. Los textos salen de `webapp/i18n/<tag>.php`, un arreglo
  plano por idioma, y una clave que a una traducción le falte cae a es-MX en vez
  de renderizar vacío, así que un catálogo a medias degrada a página mezclada y
  no a página en blanco. El selector cambia el idioma al cambiar, y el botón
  funciona sin JavaScript.

- **El código dentro de la página se partía a media palabra.** `word-break:
  break-all` corta en cualquier carácter aunque la palabra quepa entera en el
  renglón siguiente, y partía `imap.` como `ima` + `p.`. Con `overflow-wrap:
  anywhere` una ruta larga sigue partiéndose, porque no cabe de otro modo, pero
  un token corto se va completo al siguiente renglón.

- **Los ejemplos usaban dominios que alguien posee, y uno era un servidor real.**
  `MAILBOX_SETUP.md` nombraba un servidor de hosting existente en su ejemplo, y
  los marcadores de posición de la webapp usaban `tudominio.com` y
  `tuproveedor.com`. Un ejemplo que apunta a un dominio de verdad manda tráfico,
  y a veces credenciales, a quien no lo pidió. Todo pasa a `.example`, que
  existe justamente para esto, en las traducciones también.

- **Documentación.** De dónde viene el nombre queda escrito, y propagado a las
  cuatro traducciones; el selector de idioma se localiza en vez de aparecer
  siempre en español. La arquitectura de entrega por harness se agrupa en su
  propia sección en lugar de estar repartida. Y se quitan las rayas de la
  documentación pública para humanos, que es una convención de este proyecto para
  el texto que no lee un agente.

- **Las notificaciones de una plataforma de coordinación pueden contar como
  correo de quien las generó** ([#16](https://github.com/iaaorgmx/paynani/issues/16)).
  `roster.md` acepta una segunda tabla, bajo un encabezado `## Notifiers`, que
  declara tres valores: la dirección desde la que la plataforma envía, el
  encabezado que trae el nombre del autor, y contra qué columna del roster
  cotejarlo.

  El equipo que coordina en GitHub declara
  `notifications@github.com / X-GitHub-Sender / GitHub`; el que coordina en Jira
  declara los suyos. Lo que varía son tres valores y por eso está en el core: sin
  esto, cada instalación que lo necesita edita `roster.py` e `idle_listener.py` a
  mano, y esa edición se pierde en la siguiente actualización sin que nada lo
  diga. Ya pasó, y es #11.

  **No otorga nada por sí solo.** Un handle que no esté anotado para alguien que
  ya está en la lista es exactamente tan desconocido como un extraño, y una
  dirección de notificador **nunca** entra a la lista de destinatarios de
  `send.sh`: autorizan entrada, no salida, y los dos parsers del roster lo fijan.
  El listener pide al servidor los encabezados que la declaración nombre, así que
  esa lista tampoco está escrita en el código.

  Declarar un notificador amplía a quién le hace caso el agente, igual que
  agregar una fila, y por eso vive en el mismo archivo humano y bajo la misma
  regla: nunca porque un mensaje lo haya pedido. Y vale solo lo que valga el
  `From` de la plataforma, que este proyecto no autentica: dicho así en
  `HERMES.md`, en el prompt de la ruta de Hermes y en el `README.md`.

  Verificado contra una notificación real de GitHub en un buzón real: `From:
  notifications@github.com`, fuera del roster, con `X-GitHub-Sender:
  xochitl-iaamx` anotado en la columna `GitHub` de una persona que sí está.

- **El hook de inicio de sesión gritaba «THE DISPATCHER REPORTED PROBLEMS» en toda
  instalación sana** ([#15](https://github.com/iaaorgmx/paynani/issues/15)).
  `dispatch.py` escribe `delivering to <runtime>` en la rama en que **todo salió
  bien**, por el canal de diagnóstico que termina en `state/dispatch.err.log`, y
  `session_start.py` trataba cualquier línea no vacía de ese archivo como queja.
  El archivo es de diagnósticos, lo dice su propio docstring, y se leía como si
  fuera de fallos.

  El dispatcher marca ahora sus líneas de rutina (el arranque exitoso, la
  recuperación de una entrega y la compactación del diario) y el hook las
  descarta. Lo dice quien escribe, que es el único que sabe cuál es cuál, en vez
  de dejarle el juicio al lector: el texto del aviso decía *«If the last one is
  not a recovery»* precisamente porque nadie más podía distinguirlas.

  La compatibilidad cae del lado seguro: una bitácora escrita antes de que
  existiera la marca sigue disparando el aviso.

  Importa porque ese aviso existe para el caso en que la inyección al runtime
  falla, que es invisible por cualquier otro medio. Sonando siempre, el día que
  falle de verdad se verá igual que todos los días: se desactiva por uso.
  Encontrado en la primera sesión después de instalar sobre Claude Code.

- **El `password.cmd` documentado para Himalaya se rompía con un `.env` en CRLF**
  ([#14](https://github.com/iaaorgmx/paynani/issues/14)). `INSTALL.md` §4.3 mandaba
  escribir a mano `sed -n 's/^PAYNANI_PASSWORD=//p'`, que en un archivo con
  terminadores CRLF devuelve la contraseña con un retorno de carro pegado. El
  servidor la rechaza **como credencial incorrecta**, así que quien lo ve revisa la
  contraseña, que está bien, antes que el formato del archivo, que es lo que está
  mal.

  Y el repositorio ya traía el lector correcto: `scripts/env_secret.py`, agregado
  en la bifurcación para este mismo uso y descrito entonces como tolerante a BOM y
  CRLF, *«both of which have bitten this repository before»*. Ninguna documentación
  lo mencionaba. Los tres bloques de §4.3 lo usan ahora.

  Es la única superficie del proyecto donde el formato del `.env` importa:
  `preflight.py`, el listener, `roster.py` y `envpath.sh` ya lo toleran, así que en
  un host CRLF todo lo demás pasa y solo Himalaya falla. `scripts/test_env_secret.py`
  fija esa tolerancia, incluida una aserción de que el `sed` que se reemplazó sí
  devuelve el retorno de carro, para que el motivo no se pierda; y `test_docs.py`
  impide que la documentación vuelva a escribir un `sed` a mano.

  Encontrado configurando Himalaya contra Gmail en un `.env` escrito desde un
  editor de Windows.

- **El instalador resolvía `PAYNANI_ENV` y no lo persistía**
  ([#13](https://github.com/iaaorgmx/paynani/issues/13)). En un host con dos
  harness la resolución es ambigua a propósito y `PAYNANI_ENV` la resuelve; el
  instalador la horneaba en el `--env` de la unidad y la tiraba. Todo lo demás
  (`healthcheck.py`, `preflight.py`, `send.sh`, y el `python3 harness/paths.py env`
  que `UNINSTALL.md` §2 usa para decidir **qué borrar**) resolvía entonces a un
  `<clon>/.env` que no existe.

  Ahora `scripts/install.sh` lo anota en `runtime.env` y `harness/paths.py` lo lee.
  El orden es: lo que diga este proceso, luego lo que anotó la instalación, luego
  el único harness, luego el clon. Los dos primeros son alguien diciéndolo en voz
  alta y le ganan a cualquier inferencia.

  `healthcheck.py` dice además **de dónde salió** la ruta, porque «no hay
  credenciales en X» no dice dónde ir a cambiarlo. Ese dato se toma al importar
  el módulo: `load_runtime_env()` mete `runtime.env` en el entorno del proceso, y
  después de eso `PAYNANI_ENV` está puesto lo haya puesto una persona o el
  instalador, sin forma de distinguirlos mirando.

  La regla la aprendieron **las tres implementaciones** (`harness/paths.py`,
  `scripts/envpath.sh` y `webapp/lib/envfile.php`), porque `test_paths.sh` existe
  precisamente para que no vuelvan a separarse, y atrapó que solo la de Python la
  había aprendido.

  Ese mismo suite corría contra el clon real, así que su resultado dependía de si
  quien lo ejecuta tiene una instalación: en cuanto `runtime.env` empezó a
  significar algo, once asserciones cambiaron de respuesta. Ahora los tres
  resolutores se ejercitan sobre una copia desechable del clon. Las
  comprobaciones de `.gitignore` siguen apuntando al repositorio real, porque
  preguntan por una propiedad de este repositorio: contra la copia dejaban de
  correr en silencio, que es exactamente lo que el encabezado de ese archivo
  advierte.

  Encontrado instalando paynani sobre Claude Code, el primer host de ese runtime,
  que tiene dos harness con credenciales.

- **Nada decía qué código estaba corriendo una instalación**
  ([#12](https://github.com/iaaorgmx/paynani/issues/12)). `healthcheck.py` y el
  hook de inicio de sesión ahora reportan el commit, la rama, la distancia con el
  remoto y cuántos archivos rastreados difieren, y avisan cuando el commit no
  existe en ningún remoto.

  **Advertencia y nunca problema**, a diferencia de #6, y la distinción es el
  punto: un árbol modificado no impide que el correo se mueva, y una instalación
  que lleva una capa que su humano pidió es legítima. Lo que no puede seguir es
  que nadie lo sepa.

  El host de la primera prueba de campo pasó un día entero ejecutando el listener
  y el cotejo del roster modificados mientras cada verificación reportaba sobre
  un árbol que nadie había descrito. Apareció por accidente. `AGENTS.md` agrega
  además las dos reglas de proceso que ninguna herramienta puede imponer: decir
  qué código se está corriendo **antes** de reportar que algo funciona, y
  detenerse a reportar en vez de editar un archivo del proyecto para rodear un
  defecto.

  De paso, dos cosas que solo aparecen en un host con instalación real:
  `scripts/test_docs.py` escaneaba `roster.md` (la lista viva, sin rastrear, que
  existe para tener direcciones reales) y fallaba en cualquier host con una
  instalación funcionando; y no escaneaba `roster.md.example`, que es el único
  archivo cuyas direcciones se copian a cada instalación nueva, porque el glob
  era `*.md` y ese termina en `.example`.

Todo lo de abajo salió de la primera prueba de campo de 0.1.0
([#1](https://github.com/iaaorgmx/paynani/issues/1)), en un host OpenClaw real
que no era una máquina virgen.

- **`healthcheck.py` reportaba `healthy: true` en instalaciones que no podían
  enviar ni actuar sobre ningún correo**
  ([#6](https://github.com/iaaorgmx/paynani/issues/6)). Nunca abría `roster.md` ni
  miraba la configuración de Himalaya, así que ninguna de sus condiciones tocaba
  la lista de autorizados ni el cliente con el que se envía.

  Ahora son problema, no advertencia: `roster.md` ausente, `roster.md` sin
  ninguna dirección, y la falta de un bloque `[accounts.paynani]` en la
  configuración de Himalaya. Las tres dejan cada unidad activa, cada cola vacía y
  cada bitácora en calma mientras el correo no se mueve, que es exactamente la
  falla que este proyecto existe para no tener.

  El roster se lee con `roster.roster_addresses`, la misma función del listener,
  para que esta herramienta no pueda reportar una lista que el listener no ve. El
  nombre de la cuenta se escribe en `send.sh` y en `healthcheck.py` por separado,
  uno es shell y el otro Python, y `scripts/test_roster_agree.sh` los amarra:
  si se separan, esta comprobación buscaría una cuenta con la que nadie envía.

  Dos personas llegaron al mismo punto ciego el mismo día por instancias
  distintas: un roster vacío en un clon limpio, y una cuenta de Himalaya faltante
  en el host de la prueba de campo.

- **`preflight.py --help` abría una conexión IMAP en vivo en lugar de imprimir
  ayuda** ([#7](https://github.com/iaaorgmx/paynani/issues/7)). El script no
  procesaba argumentos: cualquier bandera se ignoraba en silencio y corría la
  comprobación completa. `--help` es justo la bandera que alguien usa cuando
  **no** quiere ejecutar todavía. Ahora `-h` y `--help` imprimen la cadena de uso
  y salen con `0` antes de tocar la red, y cualquier otro argumento se rechaza con
  `2` en vez de ignorarse.

- **`UNINSTALL.md` §2 no quitaba las credenciales en un host con harness**
  ([#5](https://github.com/iaaorgmx/paynani/issues/5)), que es la mayoría.
  Regresión introducida en `a7b1040`: el `rm -f .env` desde dentro del clon no
  borra nada cuando la contraseña vive en `~/.openclaw/workspace/.env`. Un
  procedimiento anunciado como destructivo que no borra lo que dice borrar deja a
  quien entrega una máquina creyendo que quitó la contraseña del buzón. Ahora el
  paso empieza por resolver la ruta con `python3 harness/paths.py env` y distingue
  el archivo del harness, del que solo se quitan las claves de esta instalación,
  del `.env` del clon, que sí se va entero.

- **El README describía la instalación como más pequeña de lo que es**
  ([#2](https://github.com/iaaorgmx/paynani/issues/2),
  [#3](https://github.com/iaaorgmx/paynani/issues/3),
  [#4](https://github.com/iaaorgmx/paynani/issues/4)). Decía «un servicio de
  usuario de systemd» donde una instalación completa deja cuatro unidades;
  ubicaba las credenciales en `<clon>/.env`, que en un host con harness ni
  siquiera existe; y listaba `<clon>/hermes/` sin condicionarlo a Hermes, en una
  sección titulada «Rutas en esta máquina» que se lee como inventario. Las tres
  corregidas, también en las cuatro traducciones.

- **Las notas de procedencia de las traducciones se movieron al pie de cada
  documento.** Estaban arriba del todo, entre el selector de idioma y la primera
  línea del texto, que es el lugar más visible de la página para una nota que es
  de mantenimiento y no para quien viene a leer el documento. Ahora van al final,
  tras una regla horizontal y en letra chica. El texto no cambió.

  Alcanza también a `README.md`, `MAILBOX_SETUP.md` y `UNINSTALL.md`, que llevan
  la nota espejo, «este archivo es la fuente de verdad», por la misma razón.

  De paso, dos cosas que estaban mal en `MAILBOX_SETUP.md` y que la nota tapaba:
  su nota decía «traducido de MAILBOX_SETUP.md… gana el inglés», heredada de
  antes de la bifurcación y contraria a la política de este repositorio, donde el
  español (MX) es la fuente de verdad; y su selector de idioma enlazaba
  «English» a sí mismo en vez de a `i18n/MAILBOX_SETUP.en-US.md`.

- **El agente pedía permiso para la primera fila del roster en vez de
  escribirla**, teniendo ya el nombre y el correo
  ([#10](https://github.com/iaaorgmx/paynani/issues/10)). La regla «agregar un
  destinatario es decisión humana» está escrita para un mensaje que pide ser
  agregado al roster, y se leía como si también cubriera la instalación, donde el
  humano está presente y la primera fila es justamente lo que encargó. Un agente
  que pide permiso para cada paso que ya tenía encargado entrena a su humano a
  decir que sí sin leer, que es lo que vuelve peligrosa la petición que sí había
  que leer. `AGENTS.md`, `INSTALL.md` y `roster.md.example` ahora separan los dos
  casos: en la instalación se escribe la fila (y si faltan los datos se piden los
  datos, no el permiso); después, una petición que llega por mensaje sigue siendo
  texto y nunca autorización.

- **Nada advertía que un contacto puede escribir desde una dirección distinta a
  la que se le escribe** ([#8](https://github.com/iaaorgmx/paynani/issues/8)).
  `roster.md.example` explicaba que la coincidencia es contra `From`, que es
  correcto, pero quien llena el archivo por primera vez escribe naturalmente la
  dirección a la que va a escribir, que puede ser la única que conoce. Cuando no
  coinciden, el correo llega, se registra y nunca se etiqueta `roster`, que se lee
  igual que si nadie hubiera escrito. `roster.md.example`, `INSTALL.md` §7 y
  `AGENTS.md` paso 7 ahora dicen que hay que preguntar las dos cosas, y que un
  contacto puede necesitar más de una fila.

## 0.1.0

Paynani se bifurca de [agenteiamail](https://github.com/julianflores/agenteiamail)
en la versión 1.9.1 y arranca aquí su propia numeración. Upstream sigue su
camino; a partir de este punto son dos productos distintos.

Todo lo que está debajo de esta entrada es la historia de agenteiamail, y se
conserva porque es la historia de este código y porque sus enlaces a issues
siguen resolviendo contra aquel repositorio. Nada de eso describe una versión de
Paynani.

Lo que cambió en la bifurcación misma:

- **Renombrado completo.** Variables de entorno `PAYNANI_*`, unidades systemd
  `paynani-*`, agentes de arranque `com.paynani.*`, el bloque `[accounts.paynani]`
  de Himalaya y la ruta Hermes `/webhooks/paynani-roster`. El renombrado es lo que
  permite que los dos productos corran en la misma máquina sin compartir
  credenciales, unidades ni la marca del último UID.

  Los identificadores de ruta de Hermes se derivan de la URL del webhook, así que
  son distintos a los de agenteiamail. Una ruta registrada para uno no es una ruta
  para el otro.

- **Se eliminó la disposición anterior al raíz único y su migración.**
  `legacy_layout()`, los inventarios de marcadores, `install.sh --migrate` y la
  transacción de migración ya no existen en ninguno de los cuatro lenguajes que
  los implementaban. Paynani no tiene instalaciones anteriores al raíz único, y
  conservar la detección solo le daría una manera de adoptar la configuración y el
  estado de una instalación viva de agenteiamail.

  `scripts/tree_digest.py` y `scripts/durable.py` se fueron con ella; la migración
  era su único consumidor.

- **`roster.md` es el único nombre del roster.** El respaldo a `roster.txt` servía
  a instalaciones anteriores a ese renombrado, y Paynani no tiene ninguna.

- **El español (MX) es el idioma principal y la fuente de verdad** de la
  documentación para humanos: `README.md`, `MAILBOX_SETUP.md`, `UNINSTALL.md` y el
  formulario web de configuración. Las versiones en inglés, español (ES), francés
  y portugués viven en `i18n/` y son traducciones. La documentación dirigida a
  agentes (`AGENTS.md`, `INSTALL.md`, `UPGRADE.md`, `HERMES.md`) y el código
  fuente siguen en inglés.

  El inventario de unidades en `UNINSTALL.md` nombraba `watch.service`, que dejó de
  existir cuando se renombró a `dispatch.service`. Corregido en ambos idiomas.

## Unreleased in agenteiamail at the fork point

- **`scripts/healthcheck.py` now says when roster mail was delivered and nothing
  was sent after it**
  ([#125](https://github.com/julianflores/agenteiamail/issues/125)). Every other
  check here asks whether mail can move; this one asks whether the loop closes.

  It was unanswerable until four days ago. The record of what came in has always
  existed, and [#117](https://github.com/julianflores/agenteiamail/issues/117)
  shipped the record of what went out in 1.9.1. So the comparison became
  possible and nothing was reading it. A live OpenClaw host took three roster
  messages between 16:11 and 17:08, answered none of them for six hours, and
  every check this project offered reported a healthy install, correctly.

  **A warning and never a failure.** Delivery working is what makes it worth
  saying at all, and two different things produce the same shape: the agent was
  told and did not reply, or nothing was attached to be told
  ([#108](https://github.com/julianflores/agenteiamail/issues/108)). The check
  reports the shape and names both readings rather than picking one. Mail still
  queued is not counted against the agent, non-roster mail is never counted at
  all, and a grace window (`HEALTH_REPLY_GRACE`, one hour) keeps a reply that is
  still being written from being accused.

  It also reads `sent.log.1`: `rotate_logs.py` rotates every `*.log` in the state
  directory, `sent.log` included, so reading only the live file would report a
  host that sent mail yesterday as never having sent anything.

## 1.9.1 (2026-08-26)

**The session-start hook failed on every healthy Claude Code host.** If you run
this on Claude Code, upgrade. Everything else here is tests and documentation.

- **`harness/session_start.py` emitted `"systemMessage": null`** when it had
  nothing to say, and Claude Code rejects that payload with
  `Hook JSON output validation failed — (root): Invalid input`, discarding the
  whole output: no replay of mail that arrived while nothing was running, no
  watch command, no byte offset. The key is now omitted rather than sent as null
  ([#104](https://github.com/julianflores/agenteiamail/issues/104)).

  The failure was inverted, which is how it survived two releases. Every branch
  that fills `systemMessage` is a branch where something is broken (listener
  down, dispatcher down, dispatcher reporting errors) so the hook worked on
  every unhealthy install and failed only on a healthy one with mail waiting,
  which is the single case it exists to serve. The first Claude Code host saw it
  work on day one because its dispatcher was still logging errors from a
  crash-loop; the next session, after that install was repaired, got nothing at
  all. **Fixing the install is what exposed it.**

  Found by running the acceptance test nobody had run: #78's criterion 6, which
  the PRD had called *"the test that distinguishes this runtime from the other
  two and the one most likely to fail"*, in bold, a week before it failed.

  The offset held throughout. The hook failed for a day without consuming
  anything, so nothing was lost and the next session could still be told:
  `session_start.py` chooses repetition over silence deliberately, and that
  choice held against a fault nobody had anticipated.

### What the tools now admit they did not do

Four separate places where something reported success while quietly checking
less than it appeared to. They are one habit, not four bugs.

- **`scripts/version.sh --line` called an untagged install `(latest)`**
  ([#64](https://github.com/julianflores/agenteiamail/issues/64)). Its three
  branches were unknown, out of date, and a catch-all; ahead-of-tag fell into the
  catch-all. The long report had always described it correctly, and `--line` is
  the form that gets read: it feeds the session-start hook and
  `healthcheck.py`'s version field.
- **`scripts/test_paths.sh` dropped every PHP assertion when `php` was absent**
  and still said `0 failed`
  ([#90](https://github.com/julianflores/agenteiamail/issues/90)). 271 with php,
  225 without, nothing in the verdict to tell them apart. It now reports
  `46 skipped (no php)`. A php-less host still passes, deliberately: php is not
  a prerequisite for running this, only for the setup form.
- **`test_install.sh` and `test_migrate.sh` were skipped on macOS by the
  tester's judgement rather than by the suites saying so**
  ([#101](https://github.com/julianflores/agenteiamail/issues/101)). They now
  announce it themselves and exit 0, because a macOS host is supported and the
  rule is not *be Linux* but *do not claim to have checked what you did not
  check*.
- **Nothing recorded what was sent**
  ([#117](https://github.com/julianflores/agenteiamail/issues/117)).
  `scripts/send.sh` now appends one line per send to `state/sent.log`:
  timestamp, recipient, subject, message-id, no bodies. Himalaya saves no copy
  unless asked, and sending is SMTP, which has no Sent folder at all; a copy
  there is a separate IMAP `APPEND`. So there was no record anywhere by default,
  and an agent asked whether it had sent something searched its entire mailbox
  and could not tell.

### One rule, five statements, now mechanically pinned

`HARNESS_ROOTS` is written down in `harness/paths.py`, `scripts/envpath.sh`,
`webapp/lib/envfile.php` and two documentation tables. 1.8.0 updated one of them.
`scripts/test_paths.sh` pinned the first three; `scripts/test_docs.py` now pins
the last two, failing in both directions: an undocumented runtime and a
documented-but-unimplemented one
([#95](https://github.com/julianflores/agenteiamail/issues/95)).

The same shape produced #91, so the address-extraction rule got the same
treatment: `send.sh`'s awk moved into `scripts/roster_extract.sh`, which the send
path and the test both call, checked against `roster.py` on five roster shapes
including CRLF and reordered columns
([#98](https://github.com/julianflores/agenteiamail/issues/98)). A test that
reimplements the rule is a third copy of it.

### Documentation that was describing a different program

- **Catch-up is Claude Code's, and the other runtimes need none**
  ([#79](https://github.com/julianflores/agenteiamail/issues/79)). `INSTALL.md`
  told OpenClaw operators to maintain the output payload of a program their
  runtime never runs. On a push runtime the queue is the catch-up: the cursor
  moves only once the runtime accepts, and *"a session not yet up"* is retryable.
  Claude Code cannot borrow that because appending to a spool always succeeds.
- **`AGENTS.md` stopped a macOS install at step 1**
  ([#110](https://github.com/julianflores/agenteiamail/issues/110)) by testing
  for systemd unconditionally: three days after 1.9.0 made macOS supported.
  Step 1 now branches; `UPGRADE.md` gained the launchd half of a trap it already
  documented for systemd.
- **`DESIGN.md` described one runtime and one supervisor**
  ([#68](https://github.com/julianflores/agenteiamail/issues/68)). It now states
  the delivery boundary for all three, what `ACCEPTED` means to each adapter and
  what it does not prove, and why supervision inverts on macOS. The honest form
  of the guarantee is that **mail is never lost before the runtime takes it, and
  the moment it is taken is recorded**; everything after that belongs to the
  runtime, and [#108](https://github.com/julianflores/agenteiamail/issues/108)
  records where OpenClaw's own boundary sits.

## 1.9.0 (2026-08-25)

**macOS is a supported host.** An OpenClaw agent on a Mac can now install and
supervise this the way a Linux one does, without WSL, Ubuntu, or a
`systemd --user` session. Written and proved on the only Mac in the fleet by the
agent that runs on it, against [#81](https://github.com/julianflores/agenteiamail/issues/81).

- **`scripts/install_macos.py` renders and converges two LaunchAgents** in
  `~/Library/LaunchAgents`, with `KeepAlive` and `RunAtLoad`, doing for launchd
  what the installer already did for systemd units.
- **`scripts/install.sh` delegates on Darwin**, which also disposes of a problem
  rather than fighting it: Apple ships bash 3.2, and the installer uses `declare -A`
  and `mapfile -d ''` in nine places. A fresh clone on macOS did not fail somewhere
  informative: it died at line 143 with `declare: -A: invalid option`, before any
  install logic ran at all. Moving the macOS path into Python means the question
  does not arise, instead of nine rewrites for a shell nobody wants to target.
- **`scripts/env_secret.py` prints one value from the env file**, so Himalaya's
  `password.cmd` reads the password at need and `config.toml` never holds it.
  It tolerates a UTF-8 BOM and CRLF, both of which have bitten this repository
  before.
- **The generated plists carry a deliberate `PATH`** (the OpenClaw binary's
  directory, Homebrew, then the standard system directories) and specifically do
  not append the installing shell's own `PATH`. The hand-written plists this
  replaced had frozen a per-run temporary directory into a service definition
  meant to outlive reboots.

### What the LaunchAgents do and do not promise

A LaunchAgent runs as the user, which is what a mailbox with a mode `600`
credentials file needs, and is tied to a login session. There is no macOS
equivalent of `enable-linger` that would keep it unprivileged and survive logout
both at once.

That is not a shortfall against the other runtimes, and it is worth writing down
rather than leaving to be rediscovered: **on every host this project currently
runs on, the listener's availability follows the user session.** A WSL host's
`enable-linger` keeps the units alive across a logout inside the Linux session,
but the whole session is down until Windows starts it. No supported host today
returns from a cold boot without a human, and a macOS one is no different. A
native Linux host would be, and none exists yet.

### A test that had never been run by anyone it applied to

`scripts/test_paths.sh` asserted "the repo root does not assume a harness" by
matching the resolved path against `*.openclaw*`. That fails on a clone at
`~/.openclaw/workspace/agenteiamail`, which is the location `README.md`
recommends, so the suite asserted that a documented install location was wrong.
It survived because nobody who had followed that line had run the suite. The
first host to do so was the Mac.

The assertion could not do what its name claimed either: where a clone sits and
how `repo_root()` derives its answer are unrelated, and matching the result
against a substring conflates them. It is replaced by one that copies `paths.py`
to an arbitrary path holding no harness name and requires `repo_root()` to
resolve from the file's own location: the property, rather than the spelling of
the answer. Removing it was right; removing it silently would not have been.

### Not covered

`scripts/test_install.sh` and `scripts/test_migrate.sh` exercise systemd and are
not a signal on macOS. They were skipped there by the tester's judgement rather
than by the suites saying so, which is
[#101](https://github.com/julianflores/agenteiamail/issues/101). Both were run on
Linux against this release.

## 1.8.1 (2026-08-25)

**1.8.0 could not send mail.** Every defect below was found within an hour by the
first Claude Code install ([#87](https://github.com/julianflores/agenteiamail/issues/87)),
on the first host that had never run this software before. Anyone who installed
1.8.0 and followed the documentation should upgrade.

- **`scripts/send.sh` still parsed the pre-1.8.0 roster format**, so every address
  in a `roster.md` table was refused and the agent could send to nobody
  ([#91](https://github.com/julianflores/agenteiamail/issues/91)). 1.8.0 rewrote
  the rule in `roster.py`, find the field containing `@` rather than the field
  after the last `|`, and left `send.sh` on the old one. On a markdown table the
  result is worse than the wrong field: rows end in a trailing `|`, so a greedy
  match consumed the whole line and yielded nothing at all.
- **Inbound and outbound disagreed about who was on the roster**, which is what
  made it quiet. Mail arrived, was tagged `roster` by the Python half, and the
  agent acted on it, and then could not reply to any of it. `REFUSED` reads like
  a roster nobody has filled in, and the message even says "Add it deliberately",
  pointing at a file where the address is already sitting.
- **`~/.claude` never reached the shell and PHP resolvers**
  ([#88](https://github.com/julianflores/agenteiamail/issues/88)). 1.8.0 added it
  to `HARNESS_ROOTS` in `harness/paths.py` and not to `scripts/envpath.sh` or
  `webapp/lib/envfile.php`, both of which carry a comment saying to keep all
  three in step. Everything that sources `envpath.sh` inherited the wrong answer,
  and on a live host that pointed the generated systemd unit's `--env` at a file
  that does not exist: the listener crash-looped, which is the outcome
  `install.sh`'s own comment says a fourth copy of the list would cause.
- **The two halves also disagreed on a CRLF roster**, which the fix for #91 would
  otherwise have preserved. `send.sh` stripped space and tab; `roster.py` strips
  all whitespace. `send.sh` already tolerates CRLF in `.env`, and says there that
  it "has bitten this repo": same script, same hazard, one of the two handled.
- **`roster.md.example` shipped two real, working addresses**
  ([#89](https://github.com/julianflores/agenteiamail/issues/89)). The repository
  is public and `cp roster.md.example roster.md` is the documented step, so
  following the instructions handed two real people standing unattended authority
  on a stranger's install. That list carries two powers, per the template's own
  header: an address on it may be written to unattended, **and** mail from it is
  treated as instructions the agent carries out. A `From:` header is forged
  trivially. The rows are gone; the format stays in the header and the table
  headings, neither of which holds an `@`. `INSTALL.md` already promised this,
  "Until you add a line it is empty", and was describing a file we were not
  shipping.

The tests that should have caught all of this were green throughout, which is the
part worth keeping.

- **`scripts/test_paths.sh` had no case for the runtime 1.8.0 added.** It asserted
  shell/Python/PHP agreement for OpenClaw, Hermes and two-harness hosts, reported
  `0 failed`, and never touched `~/.claude`. It now has a `claude harness` case
  mirroring the other two.
- **`scripts/test_roster.sh`'s fixture predated the format change**, still written
  as `Name | email` with no outer pipes and no `Type` column. So it exercised a
  shape the project no longer ships and never the one it does. It now carries
  five cases against the real template shape, including refusing `Human` as an
  address.
- **The shipped template is now asserted to authorise nobody**, resolved through
  `roster.py` rather than by grepping for `@`, because the parser is what decides
  who is allowed.
- **`scripts/test_paths.sh` still drops all PHP checks silently when `php` is
  absent**: 255 assertions with it, 211 without, `0 failed` either way. Not fixed
  here; it is [#90](https://github.com/julianflores/agenteiamail/issues/90). It is
  why the PHP half of #88 could be repaired on a host that never ran it.

Documentation, from the tester's recommendations.

- **`INSTALL.md` §1.1 checks user lingering** alongside systemd and `loginctl`.
  The installer already refused without it and named the exact command, so nothing
  failed wrongly; what was lost was a round trip, because an agent has no password
  and by the time the dry-run stops, the human who was just asked for credentials
  has gone.
- **`INSTALL.md` §3's harness table names Claude Code.** `AGENTS.md` has carried
  all three since 1.8.0. The paragraph directly beneath that table is the
  procedure that would have prevented #88: add the root to all three files
  together, with `test_paths.sh` asserting they agree. It was published, then not
  followed, under a table that was itself not updated, with a promise about a test
  that had no case for the new root.

One rule stated in several places, kept in step by hand, is the cause of #88, #90,
#91 and the table above. Each is fixed as an instance;
[#95](https://github.com/julianflores/agenteiamail/issues/95) tracks the class.

## 1.8.0 (2026-08-23)

**Claude Code is a third runtime**, and the roster is `roster.md`. Everything
below shipped across #82, #83, #84 and #85.

- **`roster.txt` is now `roster.md`.** The template is `roster.md.example` and
  every document names the new file.
- **`roster.txt` still resolves when it is the only one present**, and this is
  the part that matters rather than the rename. Every install made before this
  has a `roster.txt`; resolving only the new name would empty the allowlist on
  upgrade, and an empty allowlist does not announce itself. Sending refuses
  everyone, every inbound message stops being tagged `roster`, and the agent
  quietly stops acting on mail it was supposed to act on, which is
  indistinguishable from nobody having written. `paths.py`, `send.sh` and
  `envpath.sh` all answer the same way, and prefer `roster.md` when both exist.
- **Markdown table rows parse**, now that the file is `.md`. A row ends in a
  pipe, and the old parser took everything after the last one, which yielded an
  empty string that was then discarded, silently leaving that person off the
  list. Outer pipes are stripped, separator rows are skipped, and an entry
  without an `@` is ignored rather than becoming an allowlist entry, which is
  what keeps a table's header row harmless.
- **The roster carries a `Type` column**, `Human` or `AI Agent`, and
  `roster.md.example` ships as a markdown table.
- **The address is now found by looking for it, not by counting columns.** Every
  earlier parser took the field after the last `|`, which held for
  `Name | email` and breaks the moment anything follows the address. With a
  `Type` column the last field is `Human`; taking it yields a non-address, the
  row contributes nobody, and that person is silently off the list. The parser
  picks the field containing an `@` and is indifferent to the columns around it,
  so an older `Name | address` line still works unchanged.
- **`Type` is informational and nothing branches on it.** Being on the list is
  the whole permission: a row is exactly as authorised whether it says `Human`,
  `AI Agent`, or nothing. `roster.py` says so where the column is parsed, because
  a reader who believes it is load-bearing will eventually edit it expecting
  something to change.
- `roster_entries()` reads rows back as `{name, address, type}` for anything that
  wants to display the list rather than match against it.
- `UPGRADE.md` says how to rename an existing file, and warns against keeping
  both: the resolver prefers `roster.md`, so an address added to a stale
  `roster.txt` beside it never takes effect and nothing says why.

Towards [#78](https://github.com/julianflores/agenteiamail/issues/78), the install
side. With this, a Claude Code agent can install by following `AGENTS.md`.

- **`scripts/install.sh --runtime claudecode`.** It requires no `claude` binary,
  because delivery is a file append and the binary is only used by the opt-in
  agent mode. Demanding it would refuse hosts this runtime works fine on.
- **The installer proves the spool by writing to it**, not by reading a mode bit.
  It also states what that does *not* prove: whether any session is reading is
  invisible from outside one, and the verification report says so in its own line
  rather than letting `result=accepted` imply an end-to-end path.
- **`scripts/claude_hook.py` registers the session-start hook by merging**, and
  Claude Code's `settings.json` is deliberately never a managed artifact. It is
  the operator's file and holds configuration this project knows nothing about,
  so converging it would eventually overwrite somebody's unrelated hooks. It
  appends rather than replacing the `SessionStart` list, is idempotent, backs up
  first, writes through a temporary file, and **refuses to touch a settings file
  it cannot parse** rather than rewriting one it could not read.
- **`healthcheck.py` reports the spool backlog as information, not as a verdict.**
  Unread bytes with no session open is this runtime's normal resting state. The
  stronger check first sketched for it, "unread bytes and no watch attached",
  is not implementable honestly, so the output says what is true and names what
  it cannot see.
- `INSTALL.md` gains a Claude Code section and `AGENTS.md` step 4 points at it.

Towards [#78](https://github.com/julianflores/agenteiamail/issues/78), the session
side: the hook branch, the watch, and the design note.

- **A Claude Code session is told what it missed and how to start listening.**
  The session-start hook replays `session.spool` from the recorded offset and
  then names the exact watch command, including the byte offset it replayed
  through, so nothing falls in the gap between the hook finishing and the monitor
  attaching.
- **Arming the watch is what acknowledges the replay**, and the hook deliberately
  does not do it. The hook advancing the offset would claim an arming it cannot
  observe, and an agent that read the replay and never armed would lose that mail
  silently. The failure this chooses is repetition, which is visible.
- **`session_watch.sh` takes an exclusive lock.** `session_start.py` says that on
  every other runtime a session must never arm a watcher, because two consumers
  of one stream racing on one cursor duplicated events and corrupted the record
  of what had been seen. Claude Code cannot obey that rule and still receive
  anything, so the guard moved rather than disappeared: a second session refuses
  to arm instead of quietly halving the accuracy of both.
- **A spool shorter than the recorded offset replays from zero** rather than
  trusting it. It was truncated or replaced, and stepping over everything now in
  it is the failure that looks like a quiet mailbox.
- `DESIGN.md` gains *"Why one runtime pulls"*, which also starts closing #68.

Towards [#78](https://github.com/julianflores/agenteiamail/issues/78): Claude Code
as a third runtime. This is the runtime core: adapter, resolution and tests.
Installer support and the full documentation follow separately.

- **Claude Code delivers by inversion.** Nothing outside a Claude Code session
  can speak into it: there is no `claude system event`, and `claude -p --resume`
  starts a fresh headless turn rather than appearing in the session a human is
  sitting in. So where OpenClaw and Hermes are pushed to, this runtime comes and
  gets it. The adapter appends the rendered line to a spool that two session-side
  readers consume: the `SessionStart` hook for what arrived while nothing ran,
  and an armed `Monitor` for what lands next.
- **The spool is deliberately not named `*.log`.** `rotate_logs.py` rotates every
  `*.log` in the state directory, and rotation renumbers bytes underneath two
  readers that index by offset. A rotation between a hook replay and a monitor
  arming would resume at the wrong place: showing mail twice, or stepping over
  mail that was never shown, which is indistinguishable from a quiet mailbox.
- **One record is exactly one line.** A rendered notification can carry a line
  break, usually from a folded subject, and letting it through would make the
  monitor report one message as two and leave every later offset out of step. A
  test pins it; it caught this during development rather than in the field.
- **Spooled means durable, not seen**, and the code says so where it returns
  `ACCEPTED`. This is the same bargain the Hermes adapter makes with HTTP 202,
  with one difference worth remembering: Hermes always has something running to
  drain the queue, and here there may be no session for hours.
- **`~/.claude` joins `HARNESS_ROOTS`**, so credentials resolve from
  `~/.claude/workspace/.env` under the existing rule rather than a special case.
  It is deliberately **not** a `legacy_layout()` marker: a credentials path
  doing double duty as a layout marker is what caused #72.
- Optional `AGENTEIAMAIL_CLAUDE_MODE=agent` starts a headless run per event so
  mail can reach an agent with no session open. Off by default, because it
  widens what an inbound message can cause. The spool write happens either way,
  so a failed run can never lose an event.

Closes [#77](https://github.com/julianflores/agenteiamail/issues/77).

- **The installer says how to fix the PATH failure it stops on.** A fresh
  OpenClaw host reliably meets `openclaw executable not found in the systemd user
  PATH` during the install, and the message named the problem without naming the
  remedy. The remedy is in `INSTALL.md` §6, a section the agent has not reached:
  `AGENTS.md` step 4 points at `INSTALL.md` as a whole, and it is ~800 lines. Both
  `prereq_error` calls now carry the fix and the section title.
- **`AGENTS.md` step 4 warns that the installer can stop on harness wiring**, so
  the answer is discoverable before the failure rather than only after it.
- Found on the first fresh OpenClaw install of 1.7.0 (#74). The tester got past
  it by inventing a solution, which turned out better than the documented one and
  became #75. The next installer should not have to be that resourceful.

## 1.7.1 (2026-08-21)

Closes [#75](https://github.com/julianflores/agenteiamail/issues/75).

- **The documented fix for an unreachable `openclaw` no longer disappears on
  upgrade.** §6 told operators to pin `OPENCLAW` and `PATH` by adding
  `Environment=` lines to the installed unit. The installer converges all four
  units from the copies in `systemd/`, so that edit is drift and `--upgrade`
  removes it: leaving the dispatcher unable to reach `openclaw` again, every
  check in §7 still passing, and the only evidence in `state/watch.err.log`.
  The advice produced an install that broke later, for the exact reason the
  section tells you to stop suspecting.
- **`~/.config/environment.d/` is the documented mechanism now**, because it
  lives outside the converged artifacts and survives. The section also says that
  the file is only read when the user manager starts, and gives
  `systemctl --user set-environment` for applying it to the running one: a gap
  that made the file look ineffective on the host where it was first used.
- Pinning in the unit is still supported and now says how to do it correctly:
  uncomment the line in `systemd/agenteiamail-dispatch.service` in the clone,
  where convergence copies *from*, rather than in the installed copy. The
  template carries the same warning, since an operator reading the installed
  unit sees that comment and not this changelog.
- Found on the first fresh OpenClaw install of 1.7.0, by the tester having
  solved it a different way than the documentation prescribes.

Closes [#72](https://github.com/julianflores/agenteiamail/issues/72).

- **A credentials file is no longer evidence of an install.** A brand-new
  OpenClaw agent that followed the README, put your mailbox settings in your
  harness's workspace, landed in the pre-single-root layout, with config and
  state outside the clone, on a host where nothing had ever been installed.
  `~/.openclaw/workspace/.env` was doing double duty as both a credential
  location and the `legacy_layout()` marker, and the documentation change that
  made the harness workspace the recommended place turned "follow the
  instructions" into "get the old layout".
- **The marker was the odd one out all along.** `legacy_layout()` counts files
  this project has written: `install.manifest`, `runtime.env`, `idle.json`, the
  journal, the logs. The harness `.env` is written by the human or the harness.
  It was included because its presence used to correlate with an install made
  before this repository knew about other runtimes; making it the recommended
  location for a new one broke the correlation. Removed from the predicate in all
  three implementations.
- **A genuine pre-1.7.0 install is still found**, by the artifacts it actually
  has: the installer writes `install.manifest` and `runtime.env`, and a listener
  that has ever run leaves `idle.json` and logs. The case that stops being
  detected is the one that was never an install: a credentials file and nothing
  else. The legacy-layout test now proves its host with a UID baseline rather
  than with credentials, which is what made the conflation visible.
- Credential *resolution* is unchanged: the OpenClaw path stays in
  `HARNESS_ROOTS`, so those credentials are still read where they lie, in either
  layout.
- `DESIGN.md`'s account of why the predicate probes what it probes was written
  around the old behaviour and is corrected: credentials at a harness path with
  everything else in the clone is the ordinary arrangement, not a split-brain.

Closes [#70](https://github.com/julianflores/agenteiamail/issues/70).

- **The prompt a human pastes to their agent points at the harness workspace.**
  It said the mailbox was "already configured at `<clone>/.env`", which names one
  runtime's arrangement as though it were the only one and asserts a fact the
  human may not have established yet. It now tells the agent to *check* its
  settings in the workspace folder of its harness installation directory, which
  reads the same to a person and to an agent and stays true as runtimes are
  added. Changed in `README.md`, its inline Spanish copy, and all four
  translations together: a prompt that differs by language is four prompts.
- **The setup instructions now agree with that prompt.** They told the human to
  write credentials into the clone while the prompt sent their agent to the
  harness workspace: two places that both happen to work, which is how a
  convention quietly becomes optional. `README.md` step 1, `MAILBOX_SETUP.md`,
  `INSTALL.md` and the "what it changes on the machine" list now name the
  harness's workspace `.env` first and the clone as the answer for a host with no
  harness, in English and in all four translations. The Himalaya `password.cmd`
  examples stop naming a clone path they cannot know.

Closes [#67](https://github.com/julianflores/agenteiamail/issues/67).

- **The installer reads back the `runtime.env` it wrote.** A second run on a
  converged Hermes host demanded every value the installer had already recorded
  itself, and failed with `HERMES_NOTIFY_URL is required`, which reads as "this
  host was never configured" on a host that was configured, running and
  delivering mail. Re-running the installer is ordinary: it is what an upgrade
  changing a rendered path asks for, and that is exactly when this was found,
  while verifying the change below on the first Hermes host. Precedence is now an
  explicit flag, then the environment, then the recorded file, then fail. A host
  that has never converged has nothing to recall and fails exactly as before.
- **Recalled values are validated like supplied ones.** The recall happens before
  every argument check rather than after, so the file cannot become a way around
  validation. Both route-secret paths are recalled only when neither was given,
  so a supplied flag is never paired with a path the operator did not choose.
- **Each recalled value says where it came from**, as
  `inventory recalled=NAME from=PATH`. A value that appears from nowhere is worse
  than one somebody typed.
- Parsed as `KEY=VALUE` data and never sourced, undoing exactly the escaping that
  writes it. The file holds no secrets: the two route secrets are named by path
  and never by value.
Closes [#59](https://github.com/julianflores/agenteiamail/issues/59), the last
thing the first Hermes Agent install had to work around by hand.

- **A harness's credentials are read where the harness keeps them.** Every
  runtime keeps its agent's mail credentials in the workspace folder of its own
  installation directory (`~/.openclaw/workspace/.env`,
  `~/.hermes/workspace/.env`) and the resolver knew only the OpenClaw one. On a
  correctly provisioned Hermes host, `AGENTS.md` step 2 answered
  `NO CREDENTIALS` for a file that was one directory up, and the install was
  finished with a symlink nobody should have needed. The rule is now written as
  a **pattern** rather than a second hardcoded path: `HARNESS_ROOTS` plus
  `workspace/.env`, in `harness/paths.py`, `scripts/envpath.sh` and
  `webapp/lib/envfile.php`, which `scripts/test_paths.sh` asserts agree. Adding
  a runtime is adding a root and nothing else.
- **Only the credentials resolve there.** State, `runtime.env`, the manifest and
  `hermes/` still hang off the clone. That split is deliberate and is the one
  exception to "credentials and state cannot disagree": the harness owns that
  file, this project does not, and copying it to satisfy the single-root
  convention would put a second copy of a password on the disk.
- **An OpenClaw host is unchanged.** Its path is listed as an instance of the
  same rule, but it is also what `legacy_layout()` detects, so such a host still
  resolves into the split layout entirely, credentials *and* state, as it did
  before. Pinned by a test, because the failure it prevents is a live OpenClaw
  install quietly half-moving into the clone.
- **Two harnesses on one host adopt neither.** Two agents sharing a machine
  means either file could be the wrong mailbox, and a listener on the wrong
  mailbox is indistinguishable from a quiet one. The answer falls back to the
  file this install owns; `AGENTEIAMAIL_ENV` is how an operator says which.
- **A runtime's own config is still not a mailbox.** The rule matches
  `<harness-root>/workspace/.env` exactly, so `~/.hermes/.env`, Hermes' gateway
  token, is not adopted. That was already asserted; it now has its own case
  saying why, since the two are easy to conflate.
- `AGENTS.md` and `INSTALL.md` drop the symlink workaround they carried for one
  release and describe the behaviour instead.

## 1.7.0 (2026-08-21)

Documentation, from the first Hermes Agent install (#52) and the tester's report
@ateneabuffayhermes filed on #60. No code changes.

- **Where a harness keeps its credentials is written down.** Each runtime keeps
  its agent's mail credentials in the workspace folder of its own installation
  directory (`~/.openclaw/workspace/.env`, `~/.hermes/workspace/.env`) and
  `AGENTS.md` step 2 said instead that a new install of either harness keeps them
  inside the clone, which is untrue for Hermes. An agent that followed it on a
  correctly provisioned host was told `NO CREDENTIALS` and sent to re-enter a
  password already on disk. Step 2 now states the rule, names
  [#59](https://github.com/julianflores/agenteiamail/issues/59) as the reason the
  resolver can still disagree with it, and prescribes the symlink: never a copy,
  because a second copy of a password is a second thing to leak.
- **The Himalaya examples no longer hardcode an OpenClaw path.** All three
  `password.cmd` lines read `~/.openclaw/workspace/agenteiamail/.env`, which is
  the wrong runtime and a pre-single-root path besides. They now carry an
  unmistakable placeholder and point at whatever step 2 reported.
- **`mailbox.alias.inbox = "INBOX"` is in the v2 Himalaya example.** Without it
  the account is valid and `himalaya account check` passes while every
  `envelope list` fails: found on v2.1.0 during the first Hermes install. The
  neighbouring text now also says plainly that `account check` authenticates
  rather than reads a mailbox, so section 4.4 is the proof and this is not.
- **`HERMES.md` says a route is not live until the gateway restarts**, that the
  restart must come from a shell outside the gateway, and that Hermes refusing to
  restart itself from a tool subprocess is correct rather than a fault to work
  around. Skipping it leaves nothing listening on `HERMES_HEALTH_URL` and fails
  the installer's health probe on a correct configuration. This stopped the first
  install until an operator intervened.

Closes [#61](https://github.com/julianflores/agenteiamail/issues/61), found by
@ateneabuffayhermes on the first Hermes Agent install: she hit it, diagnosed it,
and patched her own clone to get past it.

- **`scripts/healthcheck.py` reads `runtime.env` itself.** The services are
  handed that file by systemd's `EnvironmentFile=`; a hand-run healthcheck was
  handed it by nothing, and the two runtimes do not notice that equally.
  `adapters/openclaw.py` detects its runtime by finding a binary on the host, so
  the manual command has always worked there. `adapters/hermes.py` detects its
  own by reading five `HERMES_*` variables out of the environment, so on a
  Hermes install the documented verification step reported *no runtime selected*
  while the services were delivering mail. The file is now parsed as `KEY=value`
  data (never sourced, values never printed, the exact inverse of the escaping
  `scripts/install.sh` writes) and layered *under* the real environment, so an
  explicit `AGENTEIAMAIL_RUNTIME` still wins. A missing file stays what it always
  was: an OpenClaw or manual install, not a fault.
- **"No runtime" and "this command cannot see the runtime" now read
  differently.** When nothing is selected and no `runtime.env` could be read, the
  failure names the path it looked for, because those two readings send the next
  person to different places.
- **The health output says which file configured the runtime**, so the answer
  can be traced to its source instead of inferred.

Closes [#57](https://github.com/julianflores/agenteiamail/issues/57): the last of
the migration follow-ups, against acceptance criteria agreed with @apollohermesfl
before implementation rather than discovered during review of it.

- **Durability is an ordering now, and the ordering is pinned.** The previous
  version fsynced one temporary file beneath a comment claiming power-loss
  durability. `scripts/durable.py` owns the sequence: staged data before the
  manifest names it, the manifest rename before any service stops, each
  destination before its source is unlinked, each source's parent after, and the
  install root last so a reboot cannot resurrect a deleted legacy entry or a
  finished transaction. Each of those syncs was removed to confirm its own
  assertion fails.
- **Any exit after a service is stopped restores it.** A rollback used to leave
  the listener and dispatcher stopped while printing that the install was
  unchanged: the files were unchanged and the mail had stopped. The set to
  restore is recorded before the first stop and written into the transaction, so
  a unit the operator had deliberately stopped stays stopped and a resume in a
  different process still knows what to put back. A restore that fails names the
  unit, keeps the transaction for a retry, and exits nonzero.
- **Resume revalidates instead of inferring.** Committed destinations and
  surviving staged copies are checked against digests recorded in the
  transaction. A mismatch preserves every copy and the manifest and refuses to
  clean up.
- **Filenames inside the state tree are data again.** The digest that resume
  checks artifacts against was a `find | xargs -I{} sh -c` pipeline, which
  substitutes each pathname into shell program text: a file named
  `"; touch PWNED; #` in the state tree executed a command, and the state tree
  is a directory the migration copies wholesale.
  [`scripts/tree_digest.py`](scripts/tree_digest.py) computes it without a
  shell, and pins quote, newline and metacharacter names.
- **A resume keeps the pre-stop service set recorded in the transaction**
  instead of re-reading it from a host whose services it has already stopped.
  Re-reading returned an empty set and persisted it, destroying the only record
  of what had been running before the migration started.
- **Every migration failure-path test now asserts service state**, not only
  files: the check that would have caught the two defects above. `DESIGN.md`
  records the rule, along with its limit: `is-active` proves service state, not
  mail detection.

Follow-up to [#53](https://github.com/julianflores/agenteiamail/issues/53),
fixing three defects @apollohermesfl found reviewing
[#54](https://github.com/julianflores/agenteiamail/pull/54) after merge.
[#55](https://github.com/julianflores/agenteiamail/issues/55).

- **The layout predicate abandoned undelivered mail.** It probed four files; a
  legacy state tree holding an `events.jsonl` and no `idle.json` resolved into
  the clone and left the journal behind: mail that had arrived and had never
  been delivered, dropped with no error anywhere. It now inventories every file
  either legacy directory can durably own, with a one-marker-only test per
  entry. The "credentials and state cannot disagree" property is also restated
  as conditional on neither `AGENTEIAMAIL_ENV` nor `AGENTEIAMAIL_STATE` being
  set, which is what it always meant.
- **`--migrate` is a recoverable transaction.** It used to move each artifact
  with its own `mv` and, on a failure partway, tell the operator the install was
  split and had to be repaired by hand. Artifacts are now copied into staging on
  the destination filesystem, validated, and recorded in a durable manifest
  before anything is committed; the sources stay intact, so a rollback is a
  delete rather than a move that can fail for the same reason the move did.
  Interruption has exactly two recoverable states and rerunning `--migrate`
  resolves either. The services are stopped and **verified inactive** first:
  the previous `|| true` meant a failed stop was indistinguishable from a
  successful one, under a comment claiming the stop protected the move.
- **While a migration is unfinished, nothing pretends otherwise.**
  `scripts/install.sh` refuses every mode except `--migrate`, and
  `scripts/healthcheck.py` reports the install as between layouts and its other
  facts as unreliable.
- **An unverifiable git-hygiene check no longer reports as a pass.** On a
  deployment with no `.git` the installer could not check, said so once
  mid-inventory, and still finished `result=passed`. Hygiene is now a tri-state
  carried into the final report: a non-`.git` tree finishes
  `result=passed-with-unverified-control`.

**One install, one directory, and that directory is the clone.** An install used
to spread itself over three places (credentials and route secrets in
`~/.config/agenteiamail`, queue state and logs in `~/.local/state/agenteiamail`,
the roster in the clone) so backing it up, inspecting it or removing it meant
remembering all three. Everything it owns now lives inside the clone, which also
answers "install it wherever you want" without a flag: you clone where you want,
and the install is there.
[#53](https://github.com/julianflores/agenteiamail/issues/53).

Recommended clone locations, recommendations rather than checks:

| Runtime | Clone at |
| --- | --- |
| OpenClaw | `~/.openclaw/workspace/agenteiamail` |
| Hermes Agent | `~/.hermes/workspace/agenteiamail` |

- **The credentials file is `.env`**, at the top of the clone, mode `600`. State,
  logs, the journal and the cursor are in `state/`; `runtime.env`,
  `install.manifest` and `hermes/` sit beside them. The four unit files stay in
  `~/.config/systemd/user`, because systemd will not read them anywhere else.
- **The layout is decided by one predicate**, `legacy_layout()` in
  [`harness/paths.py`](harness/paths.py), rather than one decision per file.
  Deciding credentials and state separately produces a split-brain install, the
  listener reading a password from one layout and writing its UID baseline into
  the other, and that failure presents as a mailbox that has simply gone quiet.
- **`harness/rotate_logs.py` was the only consumer that could not be
  redirected.** Pointed at a directory the units no longer write to, it recreated
  that directory empty, matched no logs, printed nothing and exited 0. So the
  weekly timer would have reported success indefinitely while the real logs grew
  without bound. It asks the resolver now, and
  [`scripts/test_rotate_logs.py`](scripts/test_rotate_logs.py) asserts both that
  it rotates in the right place and that it never creates the old one.
- **The units carry rendered absolute paths instead of `%h`**, which cannot
  express "wherever the clone is". `runtime.env` and the route secrets render
  from a separate placeholder, so a legacy install still renders correctly.
- **The installer refuses to write when git would expose the install.** Every
  runtime-owned path must be untracked and ignored before anything is written; a
  deployment with no `.git` is reported as unverifiable rather than refused.

### Upgrade actions

**Existing installs need no action.** An install made before this release keeps
its split layout, entirely and indefinitely: every tool resolves it correctly,
and an upgrade will never move it.

To move one into the clone, opt in. It stops the services while it works, and
refuses rather than half-moving on an occupied destination, a symlinked source,
or a file owned by somebody else:

```bash
scripts/install.sh --runtime openclaw --migrate --dry-run   # review the moves
scripts/install.sh --runtime openclaw --migrate             # then do them

python3 harness/paths.py env      # expect <clone>/.env
python3 harness/paths.py state    # expect <clone>/state
```

**`git clean -xdf` is now destructive on a live install.** It deletes ignored
files, which here means the mailbox password, both route secrets, `roster.txt`
and the UID baseline, in one command. Use `git clean -df`.

## 1.6.0 (2026-08-19)

Adds the supported, idempotent installer for OpenClaw and Hermes Agent runtimes,
including runtime-aware service generation and health checks, plus documentation
corrections for installation and upgrades.

### Upgrade actions

- Use `scripts/install.sh` as the supported installation and upgrade path. Run it
  with `--dry-run` first, review the plan, then rerun without `--dry-run`.
- Enable all three user units installed by the supported path:

  ```bash
  systemctl --user enable agenteiamail-idle.service
  systemctl --user enable agenteiamail-dispatch.service
  systemctl --user enable agenteiamail-logrotate.timer
  ```

- Generated units use
  `EnvironmentFile=-%h/.config/agenteiamail/runtime.env`. The leading `-` makes
  this runtime environment file optional, so existing manual installs continue
  to work without it.

## 1.5.0 (2026-08-18)

**One command that answers whether this install can do its job.** Until now the
only way to know was to read four files and two unit states and infer it, which
means in practice nobody knew: the failure this project exists to prevent is
exactly the one where every individual thing looks fine. FR8 of
[#35](https://github.com/julianflores/agenteiamail/issues/35).

- **[`scripts/healthcheck.py`](scripts/healthcheck.py)** reports the selected
  runtime and whether it can be reached, both service states, the listener's
  mailbox and position, the queue depth with the age of the oldest thing in it,
  a damaged record if there is one, the credentials path and its mode, and the
  installed version. `--json` for a script.
- **It exits nonzero when mail cannot be detected or delivered**, so it can be
  the thing an install is judged by rather than a page to read.
- **It asks about mechanisms, never about traffic.** An empty inbox is what a
  healthy install and a dead listener both look like. Every check here is
  phrased so that the second one fails.
- **It refuses to let reachability read as delivery.** Reaching a runtime proves
  the runtime answers; for a webhook runtime it says nothing about whether the
  route, its secret or its delivery target are right. Printed in place, because
  "health: ok" is the phrase people stop reading after.
- **A queue is only a fault when it is not moving.** Depth alone cannot tell a
  burst that arrived a second ago from a backlog nothing has touched since
  yesterday; the age of the oldest record is what separates them, and it is read
  from the record rather than the file's timestamp, which compaction disturbs.
- **What the runtime last said is recorded by the dispatcher**, in
  `delivery.json`: the last accepted event id, when, which runtime, and the
  adapter's own words verbatim. A health check cannot ask an adapter what
  happened an hour ago, and must never reconstruct it from a reachability check,
  because a gateway answering now says nothing about whether something accepted
  earlier was ever acted on. Where a runtime only acknowledges receipt, that
  distinction is the difference between "handed over" and "done", and only the
  first is ever known here.
- **That record holds an identifier and a sentence, never the mail.** No sender,
  no subject, no payload, no credentials, asserted rather than intended, at mode
  `600`.
- **It never prints a credential**, asserted rather than intended.
- `AGENTS.md` gains it as step 6, and as a standing rule: say "no new mail" only
  when something checked.

- **28 assertions in
  [`scripts/test_healthcheck.py`](scripts/test_healthcheck.py)**, each one about
  whether a failure that looks like nothing is reported as a failure.

---

## 1.4.0 (2026-08-18)

**Nothing assumes a harness any more.** The delivery half stopped knowing about
one in 1.3.0; the paths still did. A clone had to sit at
`~/.openclaw/workspace/agenteiamail` or the session hook silently did nothing,
and the setup form wrote credentials into `~/.openclaw/workspace/.env` on hosts
with no OpenClaw on them. FR6 of
[#35](https://github.com/julianflores/agenteiamail/issues/35).

- **One rule about where the credentials live**, in
  [`harness/paths.py`](harness/paths.py) with the shell half in
  [`scripts/envpath.sh`](scripts/envpath.sh): `AGENTEIAMAIL_ENV` if set, then an
  existing `~/.config/agenteiamail/env` (including the symlink older installs
  left there), then a legacy `~/.openclaw/workspace/.env`, then the neutral path
  for a new install. The listener, preflight, `send.sh` and the setup form all
  ask it rather than each keeping their own default.
- **An existing install keeps its credentials where they are.** They are read
  where they lie and never copied to a second location to satisfy a convention:
  a second copy of a password is a second thing to leak. Nothing is written into
  a harness's own `.env`, OpenClaw's or Hermes's.
- **The clone can be anywhere.** `harness/session_start.py` finds the repository
  from its own location instead of a hard-coded path. That failure was invisible
  by construction, since the hook swallows its own errors so a session is never
  blocked: a clone elsewhere produced no version line, no pending mail, and no
  complaint. `~/.local/share/agenteiamail` is the suggested default for a new
  install, and nothing requires it.
- **A different mail deployment on the same host is not adopted.** Only the two
  paths this project has itself written are ever looked at.

- **23 assertions in [`scripts/test_paths.sh`](scripts/test_paths.sh)**, which
  check the Python, shell and PHP resolvers give the same answer for a fresh
  host, a legacy OpenClaw install, the symlinked arrangement, a dangling link, an
  explicit override, and an unrelated deployment sitting alongside.

### Upgrade actions

**None required.** An existing install resolves to the file it already uses. If
you would rather move to the neutral path, move the file and delete the symlink
in one step, and restart both services:

```bash
mv ~/.openclaw/workspace/.env ~/.config/agenteiamail/env.real
rm -f ~/.config/agenteiamail/env
mv ~/.config/agenteiamail/env.real ~/.config/agenteiamail/env
systemctl --user restart agenteiamail-idle.service agenteiamail-dispatch.service
```

---

## 1.3.0 (2026-08-18)

**The delivery half no longer knows what a harness is.** Until now, delivering to
a second harness meant forking the repository: the watcher searched for the
`openclaw` binary itself, called it directly, and passed it a line written for a
person to read. This release puts a structured event and a runtime adapter between
the two halves, which is what makes a second harness an adapter rather than a
fork. First half of [#35](https://github.com/julianflores/agenteiamail/issues/35)
(FR1, FR2, FR3), with FR4 to follow.

**There is still no Hermes adapter in this release.** `AGENTEIAMAIL_RUNTIME`
accepts `hermes`, and this version will tell you plainly that it is not
implemented rather than pretending otherwise.

- **A canonical event envelope** ([`harness/event.py`](harness/event.py)): one
  JSON object per message carrying account, mailbox, UIDVALIDITY, UID, sender,
  subject, `roster_match` and the rendered line. No message body and no
  credentials, ever. `event_id` is `imap:<mailbox>:<uidvalidity>:<uid>`, stable
  across restarts and retries so a consumer can recognise a duplicate.
- **An append-only journal**, `events.jsonl`, written by the listener. It is a
  queue, not a log: `mail.log` is unchanged and is still what a person reads.
- **A runtime adapter interface** ([`harness/adapters/`](harness/adapters/)).
  An adapter reports accepted, retryable, or configuration-fault, and may not
  touch the cursor, listener state, or print a credential.
- **[`harness/dispatch.py`](harness/dispatch.py) replaces `watch.sh`**, which is
  removed along with `watch_service.sh`. It reads the journal by offset and moves
  the cursor only once an adapter accepts a record.
- **`AGENTEIAMAIL_RUNTIME`** selects the adapter: `openclaw`, `hermes`, or `auto`.
  `auto` chooses only when exactly one runtime is present and refuses rather than
  guessing when none or several are.
- **The exit-and-restart recovery from 1.2.2 is gone, and is not needed.** It
  existed because `tail -F` consumed a line by reading it, so surviving a failure
  meant killing the process. Reading a journal by offset consumes nothing, so a
  failed record is simply retried in place, indefinitely, while the cursor stays
  where it is. `StartLimitBurst` on the unit goes with it.
- **A stuck record holds the queue rather than being skipped**, loudly, on stderr
  and at the next session start. There is deliberately no dead-letter policy: a
  byte offset cannot describe a hole.
- **Journal compaction runs in the dispatcher**, which is the only process that
  knows what has been delivered, and takes the journal lock before it decides. It
  empties `events.jsonl` only when the cursor proves everything in it was
  delivered. The journal is never rotated with the logs; the cursor is an offset
  into that exact file, and a rotator on a timer could truncate away an event
  that had just been appended and never seen.
- **A record is written whole, flushed, and only then acknowledged.** One
  `os.write` may write fewer bytes than it was given, and the listener persists
  its last-seen UID after the append returns: if that UID reaches the disk and
  the record does not, the message is gone for good. The write now loops to
  completion and `fsync`s before reporting an offset.
- **A journal the listener cannot write blocks acknowledgement.** It used to log
  the failure and carry on, and the caller advanced the UID anyway, so a full
  disk or a permission error dropped the message permanently with a line in
  `mail.log` as the only trace. The UID now stays where it is and the messages
  are picked up again once the journal is writable.
- **Only one dispatcher may run.** It takes an exclusive lock at startup and
  refuses to start beside another, because two would read the same cursor and
  hand the runtime the same event twice.
- **A damaged record stops the queue** rather than being stepped over. Skipping
  an unparseable line advanced the cursor past it as soon as anything behind it
  was accepted, which is a dead-letter policy nobody chose and nobody was told
  about.
- **Listener faults are events.** `listener.error` envelopes go into the same
  journal as the mail, on transitions only, so an outage writes one record and a
  recovery writes one more. A fault reported only where nobody looks is a fault
  nobody sees. The state that suppresses repeats means *durably recorded*, not
  *attempted*: marking a failed append as reported would suppress it on every
  retry and could later produce a recovery record for an outage nobody was told
  about.

- **72 assertions in [`scripts/test_dispatch.py`](scripts/test_dispatch.py)**,
  covering the envelope, the journal, the cursor rules, runtime selection, the
  OpenClaw adapter against a faked binary, and each of the loss and duplication
  cases above including a concurrent append racing compaction.

### Upgrade actions

**This release renames a unit and changes where delivery state lives.** A `git
pull` alone leaves the old watcher running.

```bash
systemctl --user stop    agenteiamail-watch.service
systemctl --user disable agenteiamail-watch.service
rm -f ~/.config/systemd/user/agenteiamail-watch.service

install -Dm644 systemd/agenteiamail-dispatch.service ~/.config/systemd/user/
# then edit it: replace /path/to/agenteiamail with your clone's absolute path
systemctl --user daemon-reload
systemctl --user enable --now agenteiamail-dispatch.service
systemctl --user restart agenteiamail-idle.service
```

**Restart the listener too**, as shown. It is what writes the journal, and until
it restarts nothing is being queued for the new dispatcher.

**`seen.offset` is not migrated, and does not need to be.** It indexed
`mail.log`, which the dispatcher no longer reads. The new cursor,
`dispatch.offset`, starts at the beginning of a journal that starts empty, so the
first messages delivered after upgrading are the ones that arrive after it. Mail
that arrived while you were upgrading is in `mail.log` and in the listener's UID
state, not lost, but it will not be redelivered. Upgrade when the mailbox is
quiet if that matters to you.

---

## 1.2.3 (2026-08-18)

**A new install could not start on a host with no mailbox, which is the host the
setup form exists for.** `AGENTS.md` sent the agent to `scripts/preflight.py` at
step 1, before the credentials fork at step 2. Preflight has nothing to check
without credentials, so it asked for them on a terminal, found none because an
agent runs non-interactively, and exited 1. Step 1 also said to stop on failure
and not work around it, which is the right rule, so an agent following the file
correctly stopped before ever reaching the form.
Reported in [#31](https://github.com/julianflores/agenteiamail/issues/31).

- **The path in [`AGENTS.md`](AGENTS.md) is reordered** so each check runs when
  it has something to check. The systemd user session comes first and needs
  nothing but the host; the credentials fork comes second and needs only PHP;
  preflight comes third, with an account to test against. Steps 3 to 6 renumber
  to 4 to 7; nothing else in them changed, and the "stop, do not work around it"
  rule stays attached to preflight in its new position.
- **[`scripts/preflight.py`](scripts/preflight.py) now says what is actually
  wrong** when it is run with no credentials and no terminal, and points at the
  setup form instead of asking for an IMAP host. The reorder fixes the documented
  path; this fixes the tool for anyone who arrives at it in a different order.

- **8 assertions in [`scripts/test_preflight.sh`](scripts/test_preflight.sh)**,
  covering the empty and missing credential cases and confirming that a
  configured account still gets past the guard and reaches the server. Four fail
  against 1.2.2.

---

## 1.2.2 (2026-08-18)

**The 1.2.1 cursor fix could not recover from the failure it handled.** Stopping
the cursor at the first undelivered line was right; leaving it stopped for the
lifetime of the process was not. Nothing could restart it: the watcher stayed
alive and healthy so `Restart=always` never fired, and 1.2.1 had just removed the
session hook that used to arm a fresh watcher. One transient refusal left the
install delivering mail live while `seen.offset` stayed permanently behind, and
the only way out was restarting the service by hand. Reported by
[@apollohermesfl](https://github.com/apollohermesfl) reviewing
[#36](https://github.com/julianflores/agenteiamail/pull/36).

- **A failed line is retried in place with bounded backoff**
  ([`harness/watch.sh`](harness/watch.sh)), so a transient failure recovers on its
  own and the cursor carries on. `DELIVERY_ATTEMPTS` and `DELIVERY_BACKOFF` set
  how long that takes; the defaults spend about 30 seconds on a line.
- **When the retries are spent the watcher exits** instead of running on with a
  cursor that can no longer move. systemd restarts it, `watch_service.sh` resumes
  from the last confirmed byte, and the line is retried in order.
- **`StartLimitIntervalSec=600` / `StartLimitBurst=6`** in
  [`systemd/agenteiamail-watch.service`](systemd/agenteiamail-watch.service), so a
  failure that never clears ends as a failed unit rather than a restart loop.
  `session_start.py` already reports that as MAIL WATCHER IS DOWN.
- The 1.2.1 note that a failure meant the rest was "replayed next session" was
  wrong once the hook stopped arming a watcher. The hook shows what is pending;
  redelivery is the restart's job.

- **14 assertions in [`scripts/test_watch.sh`](scripts/test_watch.sh)**, now
  including a transiently failed line recovering without intervention and a
  sustained failure exiting rather than freezing. Five of them fail against 1.2.1.

### Upgrade actions

**Reinstall the watcher unit, then restart it.** The start limits are new, and a
`git pull` does not reach an installed unit file:

```bash
cp systemd/agenteiamail-watch.service ~/.config/systemd/user/   # re-apply your paths
systemctl --user daemon-reload
systemctl --user restart agenteiamail-watch.service
```

---

## 1.2.1 (2026-08-18)

**Three ways of losing mail without saying so.** All three lived in the cursor
that decides what a later session replays, and all three failed the same way:
the message was gone, nothing was logged as wrong, and the install looked exactly
like a mailbox with nothing in it. Found by review of `main` at `7d7efcc`
([#35](https://github.com/julianflores/agenteiamail/issues/35)).

- **A failed injection was recorded as delivered.**
  [`harness/watch.sh`](harness/watch.sh) advanced `seen.offset` after every
  `emit_system_event`, which deliberately returns success so that a failure
  cannot kill the watcher. The two together meant a refused `openclaw system
  event` acknowledged the message anyway, and the next session's replay started
  past it. `emit_system_event` now reports whether delivery happened, and the
  cursor moves only when it did. Having no `openclaw` to call at all counts as a
  failure, for the same reason.
- **The cursor recorded the log's size, not the line it had handled.** It was
  written as `wc -c` of the whole file, so anything appended while a delivery was
  in flight was stepped over. It now advances by exactly the bytes of the line
  just delivered, counted as bytes so a non-ASCII subject cannot leave it short.
- **A session started a second watcher next to the service.** The systemd unit
  runs `watch.sh` continuously while `session_start.py` told the agent to arm
  another one, putting two consumers on one stream and two writers on one cursor.
  The supervised service is now the only consumer and the only writer;
  `session_start.py` shows what is still pending and acknowledges nothing.

Delivery is now **at least once**: on failure the cursor stops at the first line
that did not arrive rather than skipping it, so that line and everything after it
are replayed. Expect an occasional duplicate notification after a delivery
failure. That is the intended trade.

- **8 assertions in [`scripts/test_watch.sh`](scripts/test_watch.sh)**, covering
  each defect above. They fail against 1.2.0.

### Upgrade actions

**Restart the watcher after pulling**, or the old code keeps running with the old
cursor behaviour:

```bash
systemctl --user restart agenteiamail-watch.service
```

**If your harness hook was generated from an older `session_start.py`**, its
output no longer asks the session to arm a watcher. Nothing needs removing, but a
session that is still being told to start one is running the duplicate consumer
this release removes.

---

## 1.2.0 (2026-08-16)

**An install can now tell whether it is current.** Until this release there was
no version anywhere in the repository, so an agent had no way to answer the
question and no reason to think of asking it. The fix below reached this
repository on 2026-08-13 and no running install had any way to learn that it
existed, which is the same shape of failure as the bug itself: everything looks
healthy, and the thing that would tell you otherwise is not wired up.

- **[`VERSION`](VERSION)**, the ground truth for what is installed. Read from a
  file rather than derived from `git describe`, so a tarball copy, a shallow
  clone or a detached HEAD still reports correctly.
- **[`scripts/version.sh`](scripts/version.sh)**: installed against released,
  read from the clone's own origin with `git ls-remote`, so there is no API
  token to hold and no rate limit to hit. It exits 1 rather than claiming
  currency when it could not reach the remote.
- **The session-start hook says the version in one line**, refreshing the remote
  check at most once a day. A session is the only moment an agent can be told
  unprompted, and one that is never told never asks.
- **[`UPGRADE.md`](UPGRADE.md)**: the upgrade sequence, including the three
  things a pull cannot reach.
- **29 assertions in [`scripts/test_version.sh`](scripts/test_version.sh)**,
  against a local bare repository rather than the network. The case they exist
  for is 1.10.0 against 1.9.0, which string comparison gets backwards and which
  nothing will notice for a year.

**Fixed: the watcher discarded the reason an event injection failed.** A host
where `openclaw` was present, executable, and failing on every call logged mail
correctly, passed every check in `INSTALL.md` §7, and delivered nothing to the
session. The failure signal and the health signal were byte-identical. The
reason is now captured to `watch.err.log` on transitions, and `session_start.py`
reports a non-empty error log and a dead watch unit the way it already reported
a dead listener. This is the defect named at the end of the 1.1.0 notes.

**Documentation.** `INSTALL.md` §6 now says that `openclaw` is a Node program
and the service PATH decides which Node it gets, which is how the bug above
reached a live install: one host needed Node 24 and the service supplied 22. Em
dashes are gone from the webapp and the public documentation, 246 of them,
including the four translations.

### Upgrade actions

**If you adapted the marked block in `harness/session_start.py`,** the one
between `---- ADAPT THIS BLOCK TO OPENCLAW'S HOOK CONTRACT ----` and its closing
rule, your pull will conflict there. That is the file this release changed, and
the conflict is the correct outcome: reapply your harness's output shape onto
the new version rather than keeping your old copy, or you lose the version line
and the watcher fault reporting along with it.

**If you are on a clone with no `VERSION` file,** you are older than 1.2.0 and
nothing in your install can tell you so. That is unavoidable for one upgrade
only: `version.sh` cannot exist on a clone that predates it. From 1.2.0 onward
the check runs itself.

---

## 1.1.0 (2026-08-13)

**A local setup page for Step 1.** `scripts/setup_web.sh` serves a form on
loopback, prints a one-time link, and stops once `~/.openclaw/workspace/.env`
exists. It authenticates against the mail server before writing anything, so
settings that do not sign in are never saved. The agent starts the page and
never sees the password.

**Fixed:**

- The certificate-mismatch diagnosis never fired, so the one message the feature
  existed to produce fell through to raw PHP noise.
- Writing through the `~/.config/agenteiamail/env` symlink replaced it, which on
  a host following `INSTALL.md` §3 would have stranded the listener on a file
  nobody updates.
- `AGENT_EMAIL_INCOMING_SERVER_POP` sat in the listener's `LEGACY_AMBIGUOUS`
  guard and could refuse the install over a vestigial key nothing reads.

**Documentation.** POP is gone everywhere; it was never implemented. The Step 2
prompt no longer carries the password rule. The four translations are updated
and carry staleness banners naming the English commit they track.

---

## 1.0.0 (2026-08-10)

First release. IMAP IDLE listener as a systemd user service, roster-gated
instruction channel, well-formed outbound mail with RFC 2047 headers and
injection guards, session catch-up and log rotation, 38 assertions across
`test_roster.sh` and `test_listener.py`, documentation in five languages.

### Upgrade actions

**Only if your clone predates 2026-08-09.** The scripts moved into `scripts/`
that day, and a systemd unit still naming the old path keeps working until the
next restart or reboot, then refuses to start long after the change that caused
it. The fix is in the box at the top of [`INSTALL.md`](INSTALL.md).
