<h1>
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="brand/paynani-horizontal-claro.svg">
    <img src="brand/paynani-horizontal.svg" alt="paynani" height="52">
  </picture>
</h1>

Mensajero élite: Los paynani eran los corredores y mensajeros oficiales del Imperio Azteca.

**Español (MX)** · [English (US)](i18n/README.en-US.md) · [Español (ES)](i18n/README.es-ES.md) · [Français (FR)](i18n/README.fr-FR.md) · [Português (BR)](i18n/README.pt-BR.md)

Paynani es un puente de correo para agentes de IA.

Le da a tu agente un buzón propio, detecta correo nuevo en segundos y entrega
cada evento por una ruta supervisada, sin perder mensajes en silencio y sin
convertir cualquier correo en una instrucción autorizada.

Paynani fue construido sobre [Himalaya](https://github.com/pimalaya/himalaya)
y funciona con una cuenta IMAP/SMTP común y corriente.

**¡Usarlo es totalmente gratis!** No necesitas contratar ningún servicio
adicional para instalarlo: usa el buzón IMAP/SMTP que tú le des al agente y corre
en tu propia máquina o en el harness donde ya trabajas.

Actualmente es utilizado por agentes de IA como OpenClaw, Hermes Agent, Claude
Code y OpenAI Codex.

Desarrollado y probado usando Linux (Ubuntu 24.04) y macOS (26.4.1).

Con Paynani, tu agente puede:

- enterarse cuando llega correo nuevo;
- leer y responder desde su propio buzón;
- leer y enviar con Himalaya, usando el buzón que configuraste;
- actuar solo cuando el remitente coincide con tu `roster.md`.

Paynani no reemplaza tu criterio ni autentica mágicamente a quien escribe: separa
el aviso de correo, la autorización operativa y la entrega al runtime para que el
fallo no sea silencioso.

## Para quién es

Paynani es para personas que quieren darle correo real a un agente de IA sin
mezclar su buzón personal, sus contraseñas ni sus decisiones de confianza con una
conversación de chat.

Sirve si quieres que un agente:

- reciba tareas por correo;
- te avise cuando llega algo importante;
- responda desde una cuenta propia;
- rechace trabajo o envíos que no estén en una lista explícita de personas y
  notificadores autorizados.

No es para delegar criterio humano a cualquier mensaje que llegue. El correo es
entrada no confiable; `roster.md` define quién puede generar trabajo.

## Antes de empezar

Antes de pedirle al agente que instale Paynani, ten preparadas tres cosas:

- un buzón dedicado para el agente, no tu correo personal;
- una terminal abierta en la misma máquina donde corre el harness;
- tu nombre y tu dirección de correo para que el agente cree `roster.md`.

## Configúralo en tres pasos

El primer paso lo haces tú, el segundo es pegar una instrucción y el tercero son
dos pruebas humanas. El detalle operativo para el agente vive en [`AGENTS.md`](AGENTS.md),
[`INSTALL.md`](INSTALL.md) y [`HERMES.md`](HERMES.md).

### 1. Dale un buzón

Crea una cuenta de correo para el agente y escribe sus datos de conexión en un
archivo `.env`. Si tu agente corre bajo un harness, ese `.env` va en el workspace
del harness (`~/.hermes/workspace/.env`, `~/.openclaw/workspace/.env`,
`~/.claude/workspace/.env` o `~/.codex/workspace/.env`). En un host sin harness,
puede vivir dentro del clon. Si no sabes dónde quedó, pregúntale a la instalación
con `python3 harness/paths.py env`.

[`MAILBOX_SETUP.md`](MAILBOX_SETUP.md) explica qué cuenta usar, dónde encontrar
el servidor IMAP/SMTP y cómo escribir el archivo sin exponer la contraseña al
agente.

> [!CAUTION]
> Nunca pegues contraseñas de correo en un chat. Usa [`MAILBOX_SETUP.md`](MAILBOX_SETUP.md)
> o el formulario de `scripts/setup_web.sh` para que el agente no vea secretos.

Haz este paso tú. Si el agente te pide la contraseña en el chat, dile que no.

### 2. Pégale la instrucción a tu agente

Pégale esto a tu agente para delegarle la instalación con límites claros:

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

El agente debe hacer la instalación desde el repositorio, pedir solo los datos
humanos que falten y negarse a recibir secretos por chat.

### 3. Haz dos pruebas humanas

El agente corre su propia verificación, pero estas dos pruebas validan lo que tú
necesitas ver.

**Prueba de acentos.** Mándale un correo desde tu dirección autorizada con un
asunto como `Prueba de correo: ñ, á, ¿qué tal?` y pregúntale qué acaba de llegar.
Debe detectar el mensaje en segundos y mostrar el asunto legible, no como
`=?utf-8?q?...`.

**Prueba de rechazo.** Pídele primero que te mande un correo a ti y confirma que
llega. Luego pídele que escriba a una dirección que no esté en `roster.md`. Debe
negarse de plano y decir que esa dirección no está autorizada.

Si cualquiera de estas pruebas falla, detente y revisa la instalación antes de
usar el buzón para trabajo real.

## Qué puede hacer tu agente

Con Paynani configurado, tu agente puede:

- recibir avisos de correo nuevo sin que tengas que pedirle que revise el buzón;
- leer mensajes desde su propia cuenta;
- responder o enviar correo con `scripts/send.sh` y el backend SMTP configurado;
- convertir en trabajo los mensajes que coinciden con `roster.md`;
- avisar sobre correo no autorizado sin obedecerlo;
- conservar eventos en un journal para que un reinicio no borre trabajo pendiente.

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

`.gitignore` mantiene los secretos fuera de `git status` y `scripts/install.sh`
se niega a escribir si alguno está versionado o no ignorado. Lo que eso no evita
es `git clean -xdf`, que borra los archivos ignorados: en una instalación viva
eso es la contraseña del buzón, los dos secretos de ruta de Hermes
(`<clon>/hermes/`, solo en Hermes), la lista de destinatarios y la marca del
último UID. Usa `git clean -df`.

## Seguridad y límites

> [!WARNING]
> `roster.md` autoriza trabajo; no prueba identidad criptográfica. Un correo no
> listado puede avisarse, pero no debe convertirse en tarea.

Paynani separa tres cosas que suelen confundirse:

| Cosa | Qué significa |
|---|---|
| Correo recibido | Hay un mensaje en el buzón. |
| Coincidencia en `roster.md` | Ese remitente o notificador está autorizado para generar trabajo. |
| Identidad autenticada | Paynani no la promete por sí solo; depende del proveedor y de validaciones externas. |

Paynani sí es responsable de:

- entregar eventos de correo por una ruta observable;
- mantener un cursor para no saltarse mensajes aceptados por el runtime;
- separar notificación de autorización;
- rechazar envíos a destinatarios fuera del roster desde la frontera segura;
- exponer verificaciones de salud para instalación y operación.

Paynani no es responsable de:

- decidir si el contenido de un correo es verdadero;
- autenticar criptográficamente a una persona;
- proteger una contraseña que fue pegada en un chat;
- reemplazar las reglas de seguridad del proveedor de correo;
- convertir correo no listado en instrucciones operativas.

## Cómo saber si está sano

> [!IMPORTANT]
> Una cola vacía no prueba que Paynani esté sano. `scripts/healthcheck.py` revisa
> servicios, credenciales, cola, entrega al harness y roster.

No basta con ver que no hay mensajes pendientes. Para revisar el sistema usa:

```bash
python3 scripts/healthcheck.py
```

Ese chequeo revisa los servicios, las credenciales, la cola, la entrega al
harness y el roster.
Si necesitas investigar una instalación rota, sigue [`INSTALL.md`](INSTALL.md) y
[`HERMES.md`](HERMES.md) antes de tocar credenciales o servicios.

## Cómo está construido, en corto

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

El listener oye el buzón y escribe eventos durables. El journal conserva lo que
llegó. El dispatcher entrega cada evento y avanza el cursor solo cuando el runtime
lo acepta. El adapter traduce esa entrega al harness que estés usando.

[`DESIGN.md`](DESIGN.md) explica por qué Paynani está construido así y qué fallos
busca evitar.

## Qué pertenece a este repositorio

Este repositorio contiene la instalación, el listener, el dispatcher, los scripts
de envío, la configuración de roster, pruebas y documentación de operación.

No contiene tu buzón, tus contraseñas ni una garantía de identidad de terceros.
Esas piezas pertenecen a tu proveedor de correo, a tu archivo `.env` local y a tus
propias reglas de confianza.

## Si quieres..., lee...

| Si quieres... | Lee |
|---|---|
| Preparar el buzón sin exponer contraseñas | [`MAILBOX_SETUP.md`](MAILBOX_SETUP.md) |
| Instalar Paynani | [`AGENTS.md`](AGENTS.md) y [`INSTALL.md`](INSTALL.md) |
| Integrarlo con Hermes Agent | [`HERMES.md`](HERMES.md) |
| Entender por qué no debe fallar en silencio | [`DESIGN.md`](DESIGN.md) |
| Migrar desde agenteiamail | [`MIGRATION.md`](MIGRATION.md) |
| Quitar Paynani | [`UNINSTALL.md`](UNINSTALL.md) |
| Ver cambios por versión | [`CHANGELOG.md`](CHANGELOG.md) |
| Autorizar remitentes | `roster.md` y [`roster.md.example`](roster.md.example) |
| Enviar correo desde la frontera segura | [`scripts/send.sh`](scripts/send.sh) |

Construido y verificado de extremo a extremo el **`2026-08-09`**.

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

## Idiomas

`README.md` es la fuente en español de México. Las traducciones mantenidas son:

- [`i18n/README.en-US.md`](i18n/README.en-US.md);
- [`i18n/README.es-ES.md`](i18n/README.es-ES.md);
- [`i18n/README.fr-FR.md`](i18n/README.fr-FR.md);
- [`i18n/README.pt-BR.md`](i18n/README.pt-BR.md).

No existe ni debe crearse `i18n/README.es-MX.md`: esta página ya es la versión
es-MX.

## La propiedad a la que sirve todo lo demás

**Nunca fallar en silencio.** La latencia era el problema fácil: IDLE lo resolvió
en una tarde. Todo lo demás que hay aquí existe porque el fallo caro no es ir
lento, es **decir con confianza que no hay correo nuevo estando ciego**.

Por eso el último UID visto se guarda mensaje por mensaje, por eso se revisa
`UIDVALIDITY` en cada conexión, por eso la bitácora de errores se vigila junto con
la de eventos, y por eso el hook de inicio de sesión pregunta si el servicio de
verdad está corriendo. [`DESIGN.md`](DESIGN.md) explica cada uno y qué se rompe
sin él.


## De dónde viene el nombre

Los paynani eran corredores y mensajeros oficiales del Imperio Azteca. Este
proyecto toma el nombre de esa función: llevar mensajes rápido, con ruta clara y
sin perderlos en silencio.

Hecho con amor por humanos y agentes de IA, desde México para el mundo.

<sub>Este archivo es la fuente de verdad. Las versiones en otros idiomas son
traducciones: si alguna contradice a esta, **gana el español (MX)**.</sub>
