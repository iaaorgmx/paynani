<h1>
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="brand/paynani-horizontal-claro.svg">
    <img src="brand/paynani-horizontal.svg" alt="paynani" height="52">
  </picture>
</h1>

**Español (MX)** · [English (US)](i18n/README.en-US.md) · [Español (ES)](i18n/README.es-ES.md) · [Français (FR)](i18n/README.fr-FR.md) · [Português (BR)](i18n/README.pt-BR.md)

Paynani es un puente de correo para agentes de IA.

Le da a tu agente un buzón propio, detecta correo nuevo en segundos y entrega
cada evento por una ruta supervisada, sin perder mensajes en silencio y sin
convertir cualquier correo en una instrucción autorizada.

**¡Usarlo es totalmente gratis!** No necesitas contratar ningún servicio
adicional para instalarlo: usa el buzón IMAP/SMTP que tú le des al agente y corre
en tu propia máquina o en el harness donde ya trabajas.

Desarrollado y probado usando Linux (Ubuntu 24.04) y macOS (26.4.1).

Con Paynani, tu agente puede:

- enterarse cuando llega correo nuevo;
- leer y responder desde su propio buzón;
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

La instalación no solo copia archivos. También deja piezas vivas para que el
correo llegue aunque no tengas una terminal abierta:

- crea o actualiza el archivo `.env` con la configuración IMAP/SMTP del buzón;
- detecta la ruta correcta del harness con `python3 harness/paths.py env` antes
  de escribir la configuración en vez de adivinar;
- instala cuatro unidades de `systemd --user`: listener, dispatcher y timers de
  salud/recuperación;
- activa *lingering* para que esos servicios puedan seguir corriendo después de
  cerrar sesión;
- crea archivos locales de estado, incluyendo un journal de eventos, un cursor de
  último UID aceptado y un roster con permisos explícitos;
- ajusta permisos para que los secretos locales queden privados para tu usuario.

Todo esto es reversible; [`UNINSTALL.md`](UNINSTALL.md) quita cada punto de esa
lista.

El comando de limpieza peligroso en una instalación viva es `git clean -xdf`, que
borra archivos ignorados: la contraseña del buzón, los dos secretos de ruta de
Hermes (`<clon>/hermes/`, solo en Hermes), la lista de destinatarios y la marca
del último UID. Usa `git clean -df`.

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
> listener, dispatcher, credenciales, runtime y cursor.

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

## Cómo mantenerlo al día

Antes de actualizar una instalación viva, lee [`CHANGELOG.md`](CHANGELOG.md) y
confirma si hay cambios de migración, servicios o variables de entorno. Después,
actualiza desde el repositorio, corre la verificación y revisa que el listener y
el dispatcher sigan activos.

No hagas una limpieza destructiva del clon sin revisar `## Qué cambia en la
computadora`: ahí están los archivos locales que no deben borrarse por accidente.

## Idiomas y mantenimiento

`README.md` es la fuente en español de México. Las traducciones mantenidas son:

- [`i18n/README.en-US.md`](i18n/README.en-US.md);
- [`i18n/README.es-ES.md`](i18n/README.es-ES.md);
- [`i18n/README.fr-FR.md`](i18n/README.fr-FR.md);
- [`i18n/README.pt-BR.md`](i18n/README.pt-BR.md).

No existe ni debe crearse `i18n/README.es-MX.md`: esta página ya es la versión
es-MX.

## La propiedad a la que sirve todo lo demás

Paynani existe para que el correo del agente no falle en silencio. Si llega un
mensaje, debe quedar un rastro durable; si el runtime lo acepta, debe avanzar el
cursor; si no está autorizado, debe avisarse sin obedecer; y si algo se rompe,
debe haber una verificación que diga dónde.

Esa propiedad pesa más que cualquier comodidad de instalación: es mejor detenerse
con un error claro que perder un correo, repetir una tarea o convertir texto no
confiable en instrucciones.

Construido y verificado de extremo a extremo el 2026-08-09.

## De dónde viene el nombre

Los paynani eran corredores y mensajeros oficiales del Imperio Azteca. Este
proyecto toma el nombre de esa función: llevar mensajes rápido, con ruta clara y
sin perderlos en silencio.

Hecho con amor por humanos y agentes de IA, desde México para el mundo.

<sub>Este archivo es la fuente de verdad. Las versiones en otros idiomas son
traducciones: si alguna contradice a esta, **gana el español (MX)**.</sub>
