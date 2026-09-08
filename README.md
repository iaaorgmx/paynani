<h1>
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="brand/paynani-horizontal-claro.svg">
    <img src="brand/paynani-horizontal.svg" alt="paynani" height="52">
  </picture>
</h1>

Mensajero élite: Los paynani eran los corredores y mensajeros oficiales del Imperio Azteca.

**Español (MX)** · [English (US)](i18n/README.en-US.md) · [Español (ES)](i18n/README.es-ES.md) · [Français (FR)](i18n/README.fr-FR.md) · [Português (BR)](i18n/README.pt-BR.md)

Paynani le da correo electrónico operativo a tu agente de IA: detecta mensajes nuevos, los entrega al runtime correcto y permite que el agente trabaje desde su buzón sin convertir cada correo en una puerta abierta.

La idea es simple: **todo correo se lee, pero solo los remitentes que tú aprobaste pueden pedir trabajo**. Los demás mensajes se reportan como notificaciones y nada más.

Paynani está construido sobre [Himalaya](https://github.com/pimalaya/himalaya), usa una cuenta IMAP/SMTP normal y corre localmente en tu máquina o servidor. Actualmente es utilizado por agentes de IA como OpenClaw, Hermes Agent, Claude Code y OpenAI Codex.

**¡Usarlo es totalmente gratis!** No necesitas contratar ningún servicio adicional para darle a tu agente una dirección de correo electrónico que pueda usar automáticamente.

Desarrollado y probado usando Linux (Ubuntu 24.04) y macOS (26.4.1).

Hecho con amor por humanos y agentes de IA, desde México para el mundo.

---

## Qué hace

- **Se entera de correo nuevo en cosa de un segundo**, sin estar sondeando cada cierto tiempo y sin que tú tengas que pedirle que revise.
- **Entrega cada evento al harness correcto**: OpenClaw, Hermes Agent, Claude Code o OpenAI Codex.
- **Lee y envía correo con Himalaya**, usando el buzón que configuraste.
- **Obedece solo a direcciones autorizadas** en `roster.md`, o a notificadores declarados explícitamente por ti.
- **No falla en silencio**: deja cola, bitácoras y estado suficiente para saber qué llegó, qué se entregó y hasta dónde se confirmó el trabajo.

## Antes de empezar

Necesitas tres cosas:

1. Un buzón dedicado para el agente.
2. Acceso a una terminal en la máquina donde corre el harness.
3. Tu nombre y tu correo para llenar `roster.md` durante la instalación.

No necesitas una API de correo, un SaaS intermedio ni una cuenta nueva en Paynani. El buzón puede ser cualquier cuenta IMAP/SMTP que funcione con Himalaya.

---

## Cómo configurarlo en tu agente

Tres pasos. El primero lo haces tú solo, el segundo es pegar un texto, y el tercero son dos minutos para revisar que de verdad funciona.

### Paso 1: Dale un buzón

El agente necesita su propia cuenta de correo, y los datos de conexión de esa cuenta escritos en un archivo `.env`. **Si tu agente corre bajo un harness, ese archivo va en la carpeta workspace del propio harness** (`~/.hermes/workspace/.env`, `~/.openclaw/workspace/.env`, `~/.claude/workspace/.env`, `~/.codex/workspace/.env`), que es donde se le dice al agente que mire y de donde esta herramienta lo lee. En un host sin harness, ponlo dentro del clon.

**[MAILBOX_SETUP.md](MAILBOX_SETUP.md) te lleva de la mano**: qué cuenta usar, dónde encontrar el nombre del servidor (la parte que falla siempre), y cómo queda el archivo.

> [!CAUTION]
> Hazlo tú, no le pidas al agente que lo haga. Hace falta una contraseña, y una contraseña no debe pasar por un chat. Una contraseña pegada en una conversación se queda ahí para siempre, y ningún cuidado posterior lo deshace.

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

Todo lo demás que el agente necesita está en el repositorio, así que el texto solo tiene que apuntarle ahí.

Espera preguntas antes de que empiece. Si el Paso 1 salió bien, deberían ser pocas, y si te pide la contraseña, dile que no: eso no es un paso de estas instrucciones.

### Paso 3: Pruébalo tú mismo

El agente corre su propia lista de verificación y te va a decir que pasó. Dos minutos de pruebas tuyas valen más, porque estarías probando lo que de verdad te importa: que se dé cuenta, y que se quede dentro de sus límites.

**Prueba 1: mándale un correo, y ponle un acento en el asunto.**

Desde tu propia dirección, con un asunto como `Prueba de correo: ñ, á, ¿qué tal?` Luego pregúntale al agente qué acaba de llegar.

En un par de segundos debería decírtelo, y **el asunto tiene que verse legible**. Si en vez de eso ves `=?utf-8?q?...`, la decodificación de encabezados está rota, lo cual importa mucho más de lo que parece, porque si trabajas en español eso es prácticamente cada mensaje que vas a recibir.

El acento es todo el punto de esta prueba. Un asunto en inglés sin acentos pasa igual, funcione o no la decodificación.

**Prueba 2: pídele que le escriba a un desconocido.**

Primero pídele que te mande algo a ti, y confirma que llega. Después pídele que le mande un mensaje a una dirección que **no** esté en su lista de autorizados.

Se tiene que negar. No pedir permiso, no consultarte primero: negarse, y decirte que esa dirección no está en la lista. Esa lista es toda la razón por la que es seguro dejar que un agente que lee correo no confiable también pueda enviarlo, así que vale la pena verla funcionar una vez con tus propios ojos.

Si lo manda, detente y avísale a quien lo instaló. Algo está mal.

---
## Qué va a poder hacer tu agente

- **Enterarse de correo nuevo en cosa de un segundo**, sin andar revisando y sin que se lo pidas.
- **Leer y enviar** con Himalaya, usando el buzón que configuraste.
- **Enviar solo a direcciones que tú aprobaste**, listadas en `roster.md`. Cualquier otra se rechaza de plano, ni siquiera te pregunta.
- **Trabajar con el correo que mandan esas mismas direcciones aprobadas.** Le escribes una tarea, la hace y te manda la respuesta por correo. Sin acuse previo y sin pedirte permiso; ya se lo diste al ponerte en la lista.
- **Dejar en paz el correo de los demás.** Lo que llega de una dirección que no está en la lista te lo reporta, y nada más.

## Qué cambia en la computadora

Vale la pena saberlo antes de aceptar. El agente tiene instrucciones de reportarte todo esto cuando termine, y puedes exigirle la lista:

- Cuatro unidades de usuario de systemd, no una. Dos corren todo el tiempo y se reinician solas si fallan: el escucha (`paynani-idle.service`) y el repartidor (`paynani-dispatch.service`). Las otras dos rotan las bitácoras: `paynani-logrotate.timer`, que se activa solo, y `paynani-logrotate.service`, que es `static` porque la dispara el temporizador y no se habilita por su cuenta. En macOS son tres *LaunchAgents* equivalentes: `com.paynani.idle`, `com.paynani.dispatch` y `com.paynani.logrotate`.
- Un archivo de credenciales con permisos `600`: el `.env` del workspace de tu harness si lo guardas ahí, y si no, `.env` dentro del clon. Se lee donde está y nunca se copia.
- Archivos de bitácora y estado en `state/` dentro del clon.
- *Lingering* activado para tu usuario, para que el servicio sobreviva cuando cierras sesión.
- Una regla permanente agregada a las instrucciones del propio agente.

Todo esto es reversible; [`UNINSTALL.md`](UNINSTALL.md) quita cada punto de esa lista, en un orden que no te deja trabajando de memoria.

`.gitignore` mantiene los secretos fuera de `git status` y `scripts/install.sh`
se niega a escribir si alguno está versionado o no ignorado. Lo que eso no evita
es `git clean -xdf`, que borra los archivos ignorados: en una instalación viva eso
es la contraseña del buzón, los dos secretos de ruta, la lista de destinatarios y
la marca del último UID. Usa `git clean -df`.

## Seguridad y límites

> [!WARNING]
> `roster.md` autoriza trabajo, no prueba identidad. Si declaras notificadores, el agente confía en el encabezado que tú configuraste para atribuir la notificación a una persona del roster; eso amplía a quién puede pedir trabajo.

El agente trabaja desde su correo, así que la pregunta no es si obedece instrucciones que llegan por email (sí lo hace, ese es el punto) sino **de quién**.

- `roster.md` es una lista de coincidencia exacta, y es toda la respuesta. Si el remitente está en la lista, el agente hace lo que el mensaje pide y contesta. Si no está, te avisa que llegó el correo y no hace nada más con él.
- La coincidencia es sobre `From` únicamente. Un `Reply-To` que apunte a alguien aprobado no otorga nada, así que un desconocido no puede tomar prestada una dirección de la lista con un encabezado.
- **Con una excepción que tú declaras:** los *notificadores*. Si tu equipo se coordina en una plataforma que manda correo en nombre de la gente (GitHub, Jira, Linear), puedes declarar su dirección, el encabezado que trae el nombre del autor, y contra qué columna de tu roster cotejarlo. Entonces esa notificación cuenta como correo de esa persona. Declarar un notificador amplía a quién le hace caso tu agente, igual que agregar una fila, y se decide igual: nunca porque un mensaje lo haya pedido. Y vale solo lo que valga el `From` de la plataforma, que aquí nadie autentica.
- **Agregar a alguien a `roster.md` es decisión tuya**, nunca respuesta a algo que llegó por correo. Esa línea es lo que convierte a un remitente en alguien a quien tu agente obedece, así que vale la pena tratarla como lo que es.
- Sin archivo de roster no hay nadie confiable; una instalación nueva lee correo y no actúa sobre nada hasta que tú escribas la lista.
- La contraseña vive en un archivo con permisos `600` fuera del repositorio, y nunca pasa por una conversación de chat.

Nota en qué se apoya este diseño: tu proveedor de correo. SPF, DKIM y DMARC se aplican antes de que algo llegue a la bandeja, y eso es lo que evita que falsificar un `From` sea trivial. Si apuntas esto a un buzón sin ese filtrado, el roster protege menos de lo que parece.

## Cómo saber si está sano

> [!IMPORTANT]
> Una cola vacía no prueba que Paynani esté sano. Solo dice que en ese momento no hay eventos pendientes de entregar.

Pídele a tu agente que corra `scripts/healthcheck.py` y que te enseñe la salida. Ese chequeo revisa el escucha, la cola, la entrega al harness, respuestas, spool, runtime, versión de git, roster, Himalaya, origen del `.env` y configuración.

Lo que quieres ver es sencillo: servicios vivos, cola sin atrasos, configuración cargada desde el lugar correcto y una prueba de entrega que el harness acepte. Si algo falla, el reporte debe decir qué pieza falló; no basta con “no hay correo nuevo”.

Las banderas, el formato completo de salida y los modos de fallo están en [`INSTALL.md`](INSTALL.md). El README solo debe darte la pregunta correcta para hacerle al agente: “corre el chequeo de salud y muéstrame qué pasó”.

 las opciones largas viven en
[`INSTALL.md`](INSTALL.md) y [`DESIGN.md`](DESIGN.md).

La doctrina es la misma que en las pruebas humanas: que el agente diga “no hay
correo nuevo” no basta. Primero tiene que poder demostrar que está escuchando.

## Cómo está construido, en corto

El README necesita un mapa; el diseño completo vive en [`DESIGN.md`](DESIGN.md).

```text
Buzón IMAP
   ↓
idle listener
   ↓ escribe evento durable
state/events.jsonl
   ↓ cursor
dispatcher
   ↓ adapter
Hermes / OpenClaw / Claude Code / Codex
```

- El listener oye y escribe; no entrega.
- El journal conserva un evento canónico por mensaje.
- El dispatcher entrega y avanza el cursor solo cuando el runtime acepta.
- El adapter habla con Hermes, OpenClaw, Claude Code o Codex.
- `roster.md` decide autorización operativa; no identidad criptográfica.

## Qué pertenece a este repositorio

El clon es la instalación. Lo que Paynani posee vive dentro de él, salvo las
unidades del supervisor del sistema operativo y los archivos de credenciales o
secretos que deliberadamente quedan fuera del control de Git.

| Pieza | Papel |
|---|---|
| `scripts/idle_listener.py` | Mantiene la conexión IMAP IDLE y escribe eventos. |
| `state/events.jsonl` | Journal durable: una envolvente canónica por línea. |
| `harness/dispatch.py` | Consume el journal y entrega por cursor al runtime. |
| `harness/adapters/` | Conecta con OpenClaw, Hermes, Claude Code y Codex. |
| `scripts/send.sh` | Envía correo dentro de la frontera de `roster.md`. |
| `scripts/roster.py` | Lee la lista autorizada y marca remitentes. |
| `scripts/preflight.py` | Prueba que el host puede correr Paynani antes de instalar. |
| `scripts/healthcheck.py` | Revisa que la instalación pueda detectar y entregar correo. |
| `webapp/` y `scripts/setup_web.sh` | Formulario local para escribir credenciales sin mostrárselas al agente. |

Las rutas exactas del host y la operación paso a paso están en
[`INSTALL.md`](INSTALL.md), [`HERMES.md`](HERMES.md), [`UPGRADE.md`](UPGRADE.md) y
[`UNINSTALL.md`](UNINSTALL.md). Este README no intenta duplicarlas.

## Si quieres..., lee...

| Si quieres... | Lee |
|---|---|
| Preparar el buzón sin exponer contraseñas | [`MAILBOX_SETUP.md`](MAILBOX_SETUP.md) |
| Configurar el buzón con un formulario local | [`webapp/README.md`](webapp/README.md) |
| Instalar Paynani | [`AGENTS.md`](AGENTS.md) y [`INSTALL.md`](INSTALL.md) |
| Integrarlo con Hermes Agent | [`HERMES.md`](HERMES.md) |
| Entender por qué no debe fallar en silencio | [`DESIGN.md`](DESIGN.md) |
| Migrar desde agenteiamail | [`MIGRATION.md`](MIGRATION.md) |
| Ver cambios por versión | [`CHANGELOG.md`](CHANGELOG.md) |
| Actualizar una instalación existente | [`UPGRADE.md`](UPGRADE.md) |
| Autorizar remitentes | `roster.md` y [`roster.md.example`](roster.md.example) |
| Enviar correo desde la frontera segura | [`scripts/send.sh`](scripts/send.sh) |
| Quitar Paynani | [`UNINSTALL.md`](UNINSTALL.md) |

## Cómo mantenerlo al día

La versión instalada está en [`VERSION`](VERSION), y el agente recibe al inicio de
cada sesión cuál está ejecutando y si existe una más nueva.

Puedes pedirle lo mismo directamente:

```bash
scripts/version.sh
```

El script lee la versión publicada desde los tags del repositorio, así que no
necesita cuenta ni token, y dice claramente cuando no pudo llegar a la red en vez
de declarar vigente una instalación solo porque nada lo contradijo.

Actualizar está documentado en [`UPGRADE.md`](UPGRADE.md), y lo que cambió entre
dos versiones está en [`CHANGELOG.md`](CHANGELOG.md). Lee el changelog antes de
actualizar: a veces una versión necesita un paso más que `git pull`, y saltártelo
puede dejarte con un listener que funciona hasta el siguiente reinicio.

## Idiomas

`README.md` es la fuente en español de México. Las traducciones viven en:

- `i18n/README.en-US.md`
- `i18n/README.es-ES.md`
- `i18n/README.fr-FR.md`
- `i18n/README.pt-BR.md`

No hay `i18n/README.es-MX.md`: crear uno duplicaría la fuente. Si una traducción
contradice este archivo, **gana el español (MX)**.

## La propiedad a la que sirve todo lo demás

**Nunca fallar en silencio.** La latencia era el problema fácil: IDLE lo resolvió
en una tarde. Todo lo demás existe porque la falla cara no es ser lento, es
**reportar con confianza que no hay correo nuevo mientras estás ciego**.

Por eso el último UID visto se persiste por mensaje, `UIDVALIDITY` se revisa en
cada conexión, el log de errores se observa junto al log de eventos y el hook de
inicio de sesión pregunta si el servicio está realmente corriendo.
[`DESIGN.md`](DESIGN.md) explica cada pieza y qué se rompe sin ella.

Construido y verificado de punta a punta el 09/08/2026.

## De dónde viene el nombre

**paynani** es náhuatl clásico, y significa algo más sencillo de lo que suena:
*“el que corre ligeramente.”* Viene del verbo `paina` (“correr ligeramente”, en el
vocabulario de Alonso de Molina de 1571) más el sufijo `-ni`, que convierte una
acción en quien la hace por oficio.

La escritura varía porque los frailes del siglo XVI escribieron el náhuatl con
las convenciones españolas de su época, donde `i`, `y` y `j` se usaban casi
indistintamente. El Gran Diccionario Náhuatl indexa los mismos pasajes del Códice
Florentino bajo `painani` y `painanj`, y registra `payna` como variante de
`paina`: una palabra, varias grafías. Este proyecto escribe `paynani`, la forma
que una persona hispanohablante reconoce.

El nombre del oficio salió de esa cualidad. El náhuatl tenía dos formas de nombrar
al mensajero imperial: `titlantli`, “el enviado”, que lo define por el encargo que
lleva, y `paynani`, que lo define por cómo se mueve. La que quedó pegada a esos
hombres fue la segunda: se les conocía por la forma en que corrían, no por quién
los mandaba.

Los corredores trabajaban en relevos, por puestos llamados `techialoyan`, y
entrenaban desde niños. De todo lo que se registra sobre ellos, un detalle es
exactamente lo que hace esta herramienta: **el mensajero clasificaba la noticia
antes de abrir la boca.** Llegar con el cabello suelto y desordenado significaba
una derrota, y no se le daba saludo; llegar con el cabello trenzado y un listón de
color, cargando escudo y macana, significaba una victoria, y la gente lo seguía
hasta el palacio. Eso hace aquí la etiqueta `roster`: la envolvente dice cómo
recibir la noticia antes de que alguien la lea.

De la misma raíz viene Paynal, quien corría en lugar de Huitzilopochtli durante
las procesiones. El Códice Florentino lo explica en tres palabras: *“el delegado,
el sustituto, el suplente”*, porque “lo apuraban; se le hacía apresurarse.” Un
agente que va por el correo en nombre de quien no puede estar en todas partes a la
vez.

<sub>Fuentes: [Gran Diccionario Náhuatl](https://gdn.iib.unam.mx/diccionario/painani/233892)
(UNAM) · [Nahuatl Dictionary](https://nahuatl.wired-humanities.org/content/paina)
(Wired Humanities) · [Mexicolore](https://www.mexicolore.co.uk/aztecs/ask-experts/did-they-send-post-mail).</sub>

---

<sub>Este archivo es la fuente de verdad para las traducciones en `i18n/`. Si una traducción contradice este documento, **gana el español (MX)**.</sub>
