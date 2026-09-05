<h1>
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="brand/paynani-horizontal-claro.svg">
    <img src="brand/paynani-horizontal.svg" alt="paynani" height="52">
  </picture>
</h1>

Mensajero élite: Los paynani eran los corredores y mensajeros oficiales del Imperio Azteca.

**Español (MX)** · [English (US)](i18n/README.en-US.md) · [Español (ES)](i18n/README.es-ES.md) · [Français (FR)](i18n/README.fr-FR.md) · [Português (BR)](i18n/README.pt-BR.md)

Correo electrónico por notificación inmediata para un agente de IA. Se entera de
que llegó un correo en más o menos un segundo, sin andar revisando cada rato, y
puede leer y enviar dentro de una lista de destinatarios autorizados.

Construido sobre [Himalaya](https://github.com/pimalaya/himalaya) para una cuenta
IMAP/SMTP común y corriente, en Ubuntu 24.04 bajo el harness OpenClaw, Hermes
Agent, Claude Code u OpenAI Codex.

---

## Cómo configurarlo en tu agente

Tres pasos. El primero lo haces tú solo, el segundo es pegar un texto, y el
tercero son dos minutos para revisar que de verdad funciona.

### Paso 1: Dale un buzón

El agente necesita su propia cuenta de correo, y los datos de conexión de esa
cuenta escritos en un archivo `.env`. **Si tu agente corre bajo un harness, ese
archivo va en la carpeta workspace del propio harness** (`~/.hermes/workspace/.env`,
`~/.openclaw/workspace/.env`, `~/.claude/workspace/.env`,
`~/.codex/workspace/.env`), que es donde se le
dice al agente que mire y de donde esta herramienta lo lee. En un host sin
harness, ponlo dentro del clon.

**[MAILBOX_SETUP.es-MX.md](MAILBOX_SETUP.md) te lleva de la mano**: qué cuenta usar,
dónde encontrar el nombre del servidor (la parte que falla siempre), y cómo queda
el archivo.

Hazlo tú, no le pidas al agente que lo haga. Hace falta una contraseña, y una
contraseña no debe pasar por un chat.

### Paso 2: Apunta al agente a este repositorio

Pégale esto a tu agente:

```text
Revisa la configuración de tu
cuenta de correo electrónico;
está en la carpeta workspace del
directorio de instalación de tu
Harness.

../workspace/.env

Después, instala este
repositorio para poder usarla:
https://github.com/iaaorgmx/paynani

Sigue las instrucciones del
archivo AGENTS.md del
repositorio.

Vas a necesitar mi nombre y mi
dirección de correo electrónico
para el archivo roster.md.

Pregúntame lo que necesites.
```

Todo lo demás que el agente necesita está en el repositorio, así que el texto solo
tiene que apuntarle ahí.

Espera preguntas antes de que empiece. Si el Paso 1 salió bien, deberían ser
pocas, y si te pide la contraseña, dile que no: una contraseña pegada en un chat
se queda en esa conversación para siempre, y ningún cuidado posterior lo deshace.
Eso no es un paso de estas instrucciones.

### Paso 3: Pruébalo tú mismo

El agente corre su propia lista de verificación y te va a decir que pasó. Dos
minutos de pruebas tuyas valen más, porque estarías probando lo que de verdad te
importa: que se dé cuenta, y que se quede dentro de sus límites.

**Prueba 1: mándale un correo, y ponle un acento en el asunto.**

Desde tu propia dirección, con un asunto como `Prueba de correo: ñ, á, ¿qué tal?`
Luego pregúntale al agente qué acaba de llegar.

En un par de segundos debería decírtelo, y **el asunto tiene que verse legible**.
Si en vez de eso ves `=?utf-8?q?...`, la decodificación de encabezados está rota,
lo cual importa mucho más de lo que parece, porque si trabajas en español eso es
prácticamente cada mensaje que vas a recibir.

El acento es todo el punto de esta prueba. Un asunto en inglés sin acentos pasa
igual, funcione o no la decodificación.

**Prueba 2: pídele que le escriba a un desconocido.**

Primero pídele que te mande algo a ti, y confirma que llega. Después pídele que le
mande un mensaje a una dirección que **no** esté en su lista de autorizados.

Se tiene que negar. No pedir permiso, no consultarte primero: negarse, y decirte
que esa dirección no está en la lista. Esa lista es toda la razón por la que es
seguro dejar que un agente que lee correo no confiable también pueda enviarlo, así
que vale la pena verla funcionar una vez con tus propios ojos.

Si lo manda, detente y avísale a quien lo instaló. Algo está mal.

---

## Arquitectura de entrega por harness

Quien opere Hermes configura dos rutas autenticadas como se describe en
[`HERMES.md`](HERMES.md).

Claude Code y OpenAI Codex funcionan distinto a los otros dos, y la diferencia
no es cosmética. El correo no se les empuja al agente: el agente va por él. En
Claude Code el hook de inicio de sesión reproduce lo que llegó mientras no había
nada corriendo y luego le pide al agente que arme una vigilancia para lo que
llegue después. En Codex esta primera versión repone en `SessionStart`; lo que
llegue a media sesión aparece hasta el siguiente inicio, reanudación, limpieza o
compactación. Ver [`INSTALL.md`](INSTALL.md) §6.

## Qué va a poder hacer tu agente

- **Enterarse de correo nuevo en cosa de un segundo**, sin andar revisando y sin
  que se lo pidas.
- **Leer y enviar** con Himalaya, usando el buzón que configuraste.
- **Enviar solo a direcciones que tú aprobaste**, listadas en `roster.md`.
  Cualquier otra se rechaza de plano, ni siquiera te pregunta.
- **Trabajar con el correo que mandan esas mismas direcciones aprobadas.** Le
  escribes una tarea, la hace y te manda la respuesta por correo. Sin acuse previo
  y sin pedirte permiso; ya se lo diste al ponerte en la lista.
- **Dejar en paz el correo de los demás.** Lo que llega de una dirección que no
  está en la lista te lo reporta, y nada más.

## Qué cambia en la computadora

Vale la pena saberlo antes de aceptar. El agente tiene instrucciones de reportarte
todo esto cuando termine, y puedes exigirle la lista:

- Cuatro unidades de usuario de systemd, no una. Dos corren todo el tiempo y se
  reinician solas si fallan: el escucha (`paynani-idle.service`) y el repartidor
  (`paynani-dispatch.service`). Las otras dos rotan las bitácoras:
  `paynani-logrotate.timer`, que se activa solo, y `paynani-logrotate.service`,
  que es `static` porque la dispara el temporizador y no se habilita por su
  cuenta. En macOS son tres *LaunchAgents* equivalentes: `com.paynani.idle`,
  `com.paynani.dispatch` y `com.paynani.logrotate`
- Un archivo de credenciales con permisos `600`: el `.env` del workspace de tu
  harness si lo guardas ahí, y si no, `.env` dentro del clon. Se lee donde está y
  nunca se copia
- Archivos de bitácora y estado en `state/` dentro del clon
- *Lingering* activado para tu usuario, para que el servicio sobreviva cuando
  cierras sesión
- Una regla permanente agregada a las instrucciones del propio agente

Todo esto es reversible; [`UNINSTALL.md`](UNINSTALL.md) quita cada punto de esa
lista, en un orden que no te deja trabajando de memoria.

## Cómo mantenerlo al día

La versión instalada está en [`VERSION`](VERSION), y al agente se le dice cuál
está corriendo al inicio de cada sesión, junto con si ya salió alguna más nueva.

Puedes preguntarle lo mismo directamente:

```bash
scripts/version.sh
```

Lee la versión publicada de las etiquetas de este repositorio, así que no hay
cuenta ni token de por medio, y avisa claramente cuando no pudo alcanzar la red,
en vez de dar por actualizada una instalación nada más porque nada lo contradijo.

Actualizar es [`UPGRADE.md`](UPGRADE.md), y lo que cambió entre dos versiones
está en [`CHANGELOG.md`](CHANGELOG.md). Lee primero el changelog: de vez en
cuando una versión necesita algo más que un `git pull`, y la forma en que falla
saltárselo es un listener que funciona hasta el siguiente reinicio.

## Seguridad

El agente trabaja desde su correo, así que la pregunta no es si obedece
instrucciones que llegan por email (sí lo hace, ese es el punto) sino **de
quién**.

- `roster.md` es una lista de coincidencia exacta, y es toda la respuesta. Si el
  remitente está en la lista, el agente hace lo que el mensaje pide y contesta. Si
  no está, te avisa que llegó el correo y no hace nada más con él.
- La coincidencia es sobre `From` únicamente. Un `Reply-To` que apunte a alguien
  aprobado no otorga nada, así que un desconocido no puede tomar prestada una
  dirección de la lista con un encabezado.
- **Con una excepción que tú declaras:** los *notificadores*. Si tu equipo se
  coordina en una plataforma que manda correo en nombre de la gente (GitHub,
  Jira, Linear), puedes declarar su dirección, el encabezado que trae el nombre
  del autor, y contra qué columna de tu roster cotejarlo. Entonces esa
  notificación cuenta como correo de esa persona. Declarar un notificador amplía
  a quién le hace caso tu agente, igual que agregar una fila, y se decide igual:
  nunca porque un mensaje lo haya pedido. Y vale solo lo que valga el `From` de
  la plataforma, que aquí nadie autentica.
- **Agregar a alguien a `roster.md` es decisión tuya**, nunca respuesta a algo que
  llegó por correo. Esa línea es lo que convierte a un remitente en alguien a quien
  tu agente obedece, así que vale la pena tratarla como lo que es.
- Sin archivo de roster no hay nadie confiable; una instalación nueva lee correo y
  no actúa sobre nada hasta que tú escribas la lista.
- La contraseña vive en un archivo con permisos `600` fuera del repositorio, y
  nunca pasa por una conversación de chat.

Nota en qué se apoya este diseño: tu proveedor de correo. SPF, DKIM y DMARC se
aplican antes de que algo llegue a la bandeja, y eso es lo que evita que falsificar
un `From` sea trivial. Si apuntas esto a un buzón sin ese filtrado, el roster
protege menos de lo que parece.

---

## El resto del repositorio

Los que llevan **(en)** están en inglés: son documentación para agentes o para
quien modifica el código, y el código se queda en inglés.

| | |
|---|---|
| [`MAILBOX_SETUP.md`](MAILBOX_SETUP.md) | Paso 1: el buzón y el archivo `.env` |
| [`UNINSTALL.md`](UNINSTALL.md) | Cómo quitarlo todo |
| [`AGENTS.md`](AGENTS.md) | **(en)** Lo que sigue el agente. Empieza aquí si eres uno. |
| [`INSTALL.md`](INSTALL.md) | **(en)** La secuencia de instalación, paso por paso |
| [`UPGRADE.md`](UPGRADE.md) | **(en)** Llevar una instalación ya existente a una versión más nueva |
| [`HERMES.md`](HERMES.md) | **(en)** El adaptador de Hermes Agent: rutas, firmas y confianza |
| [`DESIGN.md`](DESIGN.md) | **(en)** Por qué las piezas son así; léelo antes de cambiar cualquier cosa |
| [`CHANGELOG.md`](CHANGELOG.md) | **(en)** Qué cambió en cada versión, y cuáles piden algo más que un pull |
| [`webapp/README.md`](webapp/README.md) | **(en)** El Paso 1 sin terminal: un formulario local |

```
scripts/idle_listener.py  Servicio systemd --user. Mantiene abierta una conexión
  │                       IMAP IDLE; el servidor avisa en cuanto llega correo.
  │  una línea por mensaje
  ▼
<clon>/state/
  mail.log                el flujo de eventos
  idle.err.log            diagnóstico, se vigila aparte
  events.jsonl            la cola: un sobre canónico por línea
  dispatch.offset         hasta dónde se confirmó la entrega
  │
  ├─► harness/dispatch.py         el único consumidor supervisado. Lee el diario,
  │                               entrega cada evento a un adaptador de runtime y
  │                               solo avanza el cursor cuando el runtime lo acepta
  │     └─► harness/adapters/     openclaw, hermes, claudecode y codex. Lo único aquí
  │                               que sabe qué es un harness
  ├─► harness/session_start.py    muestra lo encolado; nunca lo da por entregado
  └─► harness/rotate_logs.py      rotación con copytruncate, en un timer de usuario

scripts/version.sh        la versión instalada frente a la más reciente publicada,
                          y qué hacer con la diferencia.
himalaya                  lee y envía. El listener nunca descarga cuerpos.
scripts/send.sh + roster.md  el envío está restringido a destinatarios autorizados.
scripts/roster.py         la misma lista, que el listener lee para marcar remitentes.
scripts/preflight.py      comprueba que una máquina puede correr esto antes de instalarlo.
webapp/ + setup_web.sh    un formulario local que escribe el archivo de credenciales,
                          para quien no quiere usar la terminal. Solo por loopback.
```

## Rutas en esta máquina

El clon *es* la instalación: todo lo que le pertenece vive dentro de él, así que
elegir dónde clonar es cómo eliges dónde instalar.

- Repositorio: donde sea; `~/.openclaw/workspace/paynani` en OpenClaw,
  `~/.hermes/workspace/paynani` en Hermes Agent,
  `~/.claude/workspace/paynani` en Claude Code o
  `~/.codex/workspace/paynani` en OpenAI Codex si no hay preferencia
- Credenciales: el `.env` del workspace de tu harness cuando hay exactamente uno
  (`~/.openclaw/workspace/.env`, `~/.hermes/workspace/.env`,
  `~/.claude/workspace/.env`, `~/.codex/workspace/.env`) y `<clon>/.env` cuando no. Permisos `600`, ignorado
  por git, nunca se sube. Se lee donde está y nunca se copia al clon: una segunda
  copia de una contraseña es una segunda cosa que se puede filtrar. Pregúntale a
  la instalación en vez de adivinar, con `python3 harness/paths.py env`
- Estado y eventos: `<clon>/state/`
- Secretos de ruta: `<clon>/hermes/`, permisos `600`. **Solo en Hermes**: en
  OpenClaw, Claude Code y OpenAI Codex ese directorio no existe y no falta nada
- Unidades de usuario: `~/.config/systemd/user/paynani-idle.service`,
  `paynani-dispatch.service`, `paynani-logrotate.service` y
  `paynani-logrotate.timer`, lo único que queda fuera del clon, porque systemd
  no lee unidades de otro lado. En macOS, los tres `.plist` de
  `com.paynani.*` en `~/Library/LaunchAgents/`

`.gitignore` mantiene los secretos fuera de `git status` y `scripts/install.sh`
se niega a escribir si alguno está versionado o no ignorado. Lo que eso no evita
es `git clean -xdf`, que borra los archivos ignorados: en una instalación viva eso
es la contraseña del buzón, los dos secretos de ruta, la lista de destinatarios y
la marca del último UID. Usa `git clean -df`.

## La propiedad a la que sirve todo lo demás

**Nunca fallar en silencio.** La latencia era el problema fácil: IDLE lo resolvió
en una tarde. Todo lo demás que hay aquí existe porque el fallo caro no es ir
lento, es **decir con confianza que no hay correo nuevo estando ciego**.

Por eso el último UID visto se guarda mensaje por mensaje, por eso se revisa
`UIDVALIDITY` en cada conexión, por eso la bitácora de errores se vigila junto con
la de eventos, y por eso el hook de inicio de sesión pregunta si el servicio de
verdad está corriendo. [`DESIGN.md`](DESIGN.md) explica cada uno y qué se rompe
sin él.

Construido y verificado de extremo a extremo el 2026-08-09.

## De dónde viene el nombre

**paynani** es náhuatl clásico y quiere decir, sin adornos, *«el que corre
ligeramente»*: del verbo `paina` («correr ligeramente», en el vocabulario de
Alonso de Molina, 1571) más el sufijo `-ni`, que convierte una acción en quien la
hace de oficio.

La grafía varía porque los frailes del siglo XVI escribieron el náhuatl con las
convenciones del español de su época, donde `i`, `y` y `j` se usaban casi
indistintamente. El Gran Diccionario Náhuatl indexa los mismos pasajes del Códice
Florentino bajo `painani` y bajo `painanj`, y registra `payna` como variante de
`paina`: son la misma palabra. Aquí se escribe `paynani`, que es la forma que un
lector hispanohablante reconoce.

De esa cualidad salió el nombre del oficio. El náhuatl tenía dos maneras de
nombrar al mensajero imperial: `titlantli`, «el enviado», que lo define por el
encargo que lleva, y `paynani`, que lo define por cómo se mueve. La que se quedó
pegada a esos hombres fue la segunda: se los conocía por la manera de correr, no
por quién los mandaba.

Los corredores trabajaban en relevos, con postas llamadas `techialoyan`, y se
entrenaban desde niños. De todo lo que se cuenta de ellos hay un detalle que es
justamente lo que hace esta herramienta: **el mensajero clasificaba la noticia
antes de abrir la boca.** Si llegaba con el pelo suelto y revuelto traía una
derrota, y no se le daba ni el saludo; si llegaba con el pelo trenzado y una cinta
de color, con escudo y macana, traía una victoria y la gente lo seguía hasta el
palacio. Eso es lo que hace aquí la etiqueta `roster`: el sobre dice cómo recibir
la noticia antes de que se lea.

De la misma raíz viene Paynal, el que corría en lugar de Huitzilopochtli en las
procesiones. El Códice Florentino lo explica en tres palabras, *«el delegado, el
sustituto, el suplente»*, porque «lo apuraban, lo hacían correr». Un agente que va
por el correo en lugar de quien no puede estar en todas partes.

<sub>Fuentes: [Gran Diccionario Náhuatl](https://gdn.iib.unam.mx/diccionario/painani/233892)
(UNAM) · [Nahuatl Dictionary](https://nahuatl.wired-humanities.org/content/paina)
(Wired Humanities) · [Mexicolore](https://www.mexicolore.co.uk/aztecs/ask-experts/did-they-send-post-mail).</sub>

---

<sub>Este archivo es la fuente de verdad. Las versiones en otros idiomas son traducciones: si alguna contradice a esta, **gana el español (MX)**.</sub>
