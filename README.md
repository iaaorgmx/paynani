<h1>
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="brand/paynani-horizontal-claro.svg">
    <img src="brand/paynani-horizontal.svg" alt="paynani" height="52">
  </picture>
</h1>

Mensajero élite: Los paynani eran los corredores y mensajeros oficiales del Imperio Azteca.

**Español (MX)** · [English (US)](i18n/README.en-US.md) · [Español (ES)](i18n/README.es-ES.md) · [Français (FR)](i18n/README.fr-FR.md) · [Português (BR)](i18n/README.pt-BR.md)

Paynani le permite a tu agente de IA leer automáticamente su correo electrónico
unos segundos después de que llega, procesar los mensajes recibidos y atender las
instrucciones del correo tal como lo haría un colaborador humano.

Todos los correos recibidos se leen, pero solo se siguen las instrucciones de los
correos provenientes de una lista de contactos autorizados. Esa lista la escribes
tú, y vive en un archivo llamado `roster.md`.

Paynani fue construido sobre
[Himalaya](https://github.com/pimalaya/himalaya) y funciona con una cuenta de
correo común y corriente, del mismo tipo que configurarías en cualquier programa
de correo.

**¡Usarlo es totalmente gratis!** No necesitas contratar ningún servicio
adicional para darle a tu agente una dirección de correo electrónico que pueda
usar automáticamente.

Corre en tu propia computadora o servidor, dentro del programa que ya hospeda a
tu agente. A ese programa anfitrión se le llama *harness*, y así se usa la
palabra en el resto de esta página. Actualmente Paynani es utilizado por agentes
de IA como OpenClaw, Hermes Agent, Claude Code y OpenAI Codex.

Desarrollado y probado usando Linux (Ubuntu 24.04) y macOS (26.4.1).

Hecho con amor por humanos y agentes de IA, desde México para el mundo.

---

## Para quién es

Para quien quiere darle a su agente una dirección de correo de verdad sin mezclar
ahí su buzón personal, sus contraseñas ni sus decisiones de confianza.

Te sirve si quieres que tu agente:

- reciba tareas por correo, de ti o de tu equipo;
- te avise cuando llegue algo que vale la pena mirar;
- conteste desde su propia cuenta, no desde la tuya;
- se niegue a obedecer, o a escribirle, a quien no esté en tu lista.

No sirve para delegarle criterio a cualquier mensaje que llegue. El correo lo
manda cualquiera, así que Paynani trata todo lo que entra como no confiable
hasta que el remitente coincide con tu lista.

## Antes de empezar

Necesitas cuatro cosas:

1. una cuenta de correo dedicada al agente, no tu correo personal;
2. acceso a una terminal en la máquina donde corre tu agente;
3. un momento para escribir tú la contraseña en un archivo, sin pegarla en un chat;
4. tu nombre y tu dirección de correo, para la lista de contactos autorizados.

Nada más. No hace falta una API de correo, un servicio intermedio ni una cuenta
nueva en ningún lado.

## Cómo configurarlo en tu agente

Tres pasos. El primero lo haces tú solo, el segundo es pegar un texto, y el
tercero son dos minutos para revisar que de verdad funciona.

### Paso 1: Dale un buzón

El agente necesita su propia cuenta de correo, y los datos de conexión de esa
cuenta escritos en un archivo llamado `.env`. **Si tu agente corre bajo un
harness, ese archivo va en la carpeta `workspace` del propio harness**
(`~/.hermes/workspace/.env`, `~/.openclaw/workspace/.env`,
`~/.claude/workspace/.env`, `~/.codex/workspace/.env`), que es donde se le dice
al agente que mire y de donde esta herramienta lo lee. Si no hay harness, el
archivo puede vivir dentro de la carpeta del proyecto. Y si no sabes dónde quedó,
puedes preguntárselo a la instalación con `python3 harness/paths.py env`.

**[MAILBOX_SETUP.md](MAILBOX_SETUP.md) te lleva de la mano**: qué cuenta usar,
dónde encontrar el nombre del servidor (la parte que falla siempre), y cómo queda
el archivo.

> [!CAUTION]
> Hazlo tú, no le pidas al agente que lo haga. Hace falta una contraseña, y una
> contraseña no debe pasar por un chat: la que pegas en una conversación se queda
> ahí para siempre, y ningún cuidado posterior lo deshace. Si prefieres no usar la
> terminal, `scripts/setup_web.sh` abre un formulario local que escribe el archivo
> por ti.

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

Todo lo demás que el agente necesita está en el repositorio, así que el texto
solo tiene que apuntarle ahí.

Espera preguntas antes de que empiece. Si el Paso 1 salió bien, deberían ser
pocas. Si te pide la contraseña, dile que no: eso no es un paso de estas
instrucciones.

### Paso 3: Pruébalo tú mismo

El agente corre su propia lista de verificación y te va a decir que pasó. Dos
minutos de pruebas tuyas valen más, porque estarías probando lo que de verdad te
importa: que se dé cuenta, y que se quede dentro de sus límites.

**Prueba 1: mándale un correo, y ponle un acento en el asunto.**

Desde tu propia dirección, con un asunto como `Prueba de correo: ñ, á, ¿qué tal?`
Luego pregúntale al agente qué acaba de llegar.

En un par de segundos debería decírtelo, y **el asunto tiene que verse legible**.
Si en vez de eso ves `=?utf-8?q?...`, hay algo roto en la forma en que lee los
encabezados, y eso importa mucho más de lo que parece: si trabajas en español,
son prácticamente todos los mensajes que vas a recibir.

El acento es todo el punto de esta prueba. Un asunto en inglés sin acentos pasa
igual, funcione o no.

**Prueba 2: pídele que le escriba a un desconocido.**

Primero pídele que te mande algo a ti, y confirma que llega. Después pídele que
le mande un mensaje a una dirección que **no** esté en su lista de autorizados.

Se tiene que negar. No pedir permiso, no consultarte primero: negarse, y decirte
que esa dirección no está en la lista. Esa lista es toda la razón por la que es
seguro dejar que un agente que lee correo no confiable también pueda enviarlo,
así que vale la pena verla funcionar una vez con tus propios ojos.

Si lo manda, detente y avísale a quien lo instaló. Algo está mal.

## Qué va a poder hacer tu agente

- **Enterarse de correo nuevo en cosa de un segundo**, sin andar revisando y sin
  que se lo pidas.
- **Leer y enviar** desde el buzón que configuraste.
- **Enviar solo a direcciones que tú aprobaste**, las de tu lista. Cualquier otra
  se rechaza de plano, ni siquiera te pregunta.
- **Trabajar con el correo que mandan esas mismas direcciones aprobadas.** Le
  escribes una tarea, la hace y te manda la respuesta por correo. Sin acuse previo
  y sin pedirte permiso; ya se lo diste al ponerte en la lista.
- **Dejar en paz el correo de los demás.** Lo que llega de una dirección que no
  está en la lista te lo reporta, y nada más.
- **No perder lo que llegó** si la máquina se reinicia a media tarea. Cada
  mensaje detectado se anota en disco antes de entregarse.

## Qué cambia en la computadora

Vale la pena saberlo antes de aceptar. El agente tiene instrucciones de reportarte
todo esto cuando termine, y puedes exigirle la lista:

- **Dos servicios que quedan corriendo todo el tiempo** y se reinician solos si
  fallan: el que escucha el buzón y el que le entrega los mensajes a tu agente.
  Se instalan como servicios de tu usuario, no del sistema.
- **Dos más que solo se encargan de recortar las bitácoras** para que no crezcan
  sin fin.
- **Un archivo con la contraseña del buzón**, con permisos restringidos a tu
  usuario. Se lee donde tú lo dejaste y nunca se copia a otro lado.
- **Archivos de bitácora y estado** dentro de la carpeta del proyecto.
- **Permiso para que esos servicios sigan vivos cuando cierras sesión.**
- **Una regla permanente agregada a las instrucciones del propio agente.**

Todo esto es reversible; [`UNINSTALL.md`](UNINSTALL.md) quita cada punto de esa
lista, en un orden que no te deja trabajando de memoria.

<details>
<summary>Los nombres exactos, si los necesitas</summary>

Cuatro unidades de usuario de systemd, no una. Dos corren todo el tiempo y se
reinician solas si fallan: el escucha (`paynani-idle.service`) y el repartidor
(`paynani-dispatch.service`). Las otras dos rotan las bitácoras:
`paynani-logrotate.timer`, que se activa solo, y `paynani-logrotate.service`, que
es `static` porque la dispara el temporizador y no se habilita por su cuenta. En
macOS son tres *LaunchAgents* equivalentes: `com.paynani.idle`,
`com.paynani.dispatch` y `com.paynani.logrotate`.

El archivo de credenciales lleva permisos `600`: el `.env` del workspace de tu
harness si lo guardas ahí, y si no, `.env` dentro del clon. Las bitácoras y el
estado viven en `state/`, dentro del clon. El *lingering* es lo que mantiene vivos
los servicios después de cerrar sesión.

</details>

`.gitignore` mantiene los secretos fuera de `git status` y `scripts/install.sh`
se niega a escribir si alguno está versionado o no ignorado. Lo que eso no evita
es `git clean -xdf`, que borra los archivos ignorados: en una instalación viva
eso es la contraseña del buzón, los dos secretos de ruta de Hermes
(`<clon>/hermes/`, solo en Hermes), la lista de destinatarios y la marca del
último mensaje visto. Usa `git clean -df`.

## Seguridad y límites

> [!WARNING]
> Tu lista de contactos autorizados decide de quién acepta trabajo tu agente. No
> prueba quién es esa persona. Un correo de alguien que no está en la lista se te
> reporta, y ahí se queda.

El agente trabaja desde su correo, así que la pregunta no es si obedece
instrucciones que llegan por email. Sí lo hace, ese es el punto. La pregunta es
**de quién**.

- `roster.md` es una lista de coincidencia exacta, y es toda la respuesta. Si el
  remitente está en la lista, el agente hace lo que el mensaje pide y contesta. Si
  no está, te avisa que llegó el correo y no hace nada más con él.
- La coincidencia es sobre el remitente que trae el mensaje, y solo sobre ese. Un
  desconocido no puede tomar prestada una dirección de tu lista poniéndola en otro
  campo.
- **Con una excepción que tú declaras:** los *notificadores*. Si tu equipo se
  coordina en una plataforma que manda correo en nombre de la gente (GitHub, Jira,
  Linear), puedes declarar su dirección y contra qué parte de tu lista cotejar al
  autor. Entonces esa notificación cuenta como correo de esa persona. Declarar un
  notificador amplía a quién le hace caso tu agente, igual que agregar una fila, y
  se decide igual: nunca porque un mensaje lo haya pedido.
- **Agregar a alguien a la lista es decisión tuya**, nunca respuesta a algo que
  llegó por correo. Esa línea es lo que convierte a un remitente en alguien a
  quien tu agente obedece.
- Sin lista no hay nadie confiable. Una instalación nueva lee correo y no actúa
  sobre nada hasta que tú la escribas.

Vale la pena saber en qué se apoya todo esto: tu proveedor de correo. Los
filtros que traen Gmail, Outlook y los demás son los que evitan que falsificar un
remitente sea trivial, y se aplican antes de que el mensaje llegue a la bandeja.
Si apuntas Paynani a un buzón sin ese filtrado, la lista protege menos de lo que
parece.

## Cómo saber si está sano

> [!IMPORTANT]
> Que no haya mensajes pendientes no prueba que Paynani esté sano. También se ve
> así cuando dejó de escuchar.

Pídele a tu agente que corra el chequeo de salud y que te enseñe la salida:

```bash
python3 scripts/healthcheck.py
```

Revisa los servicios, las credenciales, la cola de mensajes, la entrega a tu
agente y la lista de autorizados. Lo que quieres ver es que los servicios están
vivos, que no hay nada atorado y que la configuración se está leyendo del lugar
correcto. Si algo falla, el reporte te dice qué pieza, no solo que no hay correo.

Las opciones largas y los modos de fallo están en [`INSTALL.md`](INSTALL.md).

## Cómo está construido, en corto

Un servicio mantiene abierta una conexión con tu servidor de correo, del tipo en
que el servidor avisa solo en cuanto llega algo, sin que nadie tenga que estar
preguntando. Cuando llega un mensaje, ese servicio lo anota en disco antes de
hacer nada más. Un segundo servicio lee esas anotaciones y se las entrega a tu
agente, y solo marca una como entregada cuando el agente confirma que la recibió.

Esa separación es la que evita perder correo cuando algo se cae a medias.
[`DESIGN.md`](DESIGN.md) explica cada pieza, por qué está así y qué se rompe si
se quita.

## Qué pertenece a este repositorio

Aquí vive la instalación, los dos servicios, los scripts de envío, la lista de
autorizados, las pruebas y la documentación de operación.

Aquí no vive tu buzón, ni tu contraseña, ni una garantía de que quien escribe es
quien dice ser. Eso le toca a tu proveedor de correo, a tu archivo `.env` y a tu
propio criterio sobre a quién le das entrada.

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
saltárselo es un servicio que funciona hasta el siguiente reinicio.

## Idiomas

`README.md` es la fuente en español de México. Las traducciones mantenidas son:

- [`i18n/README.en-US.md`](i18n/README.en-US.md);
- [`i18n/README.es-ES.md`](i18n/README.es-ES.md);
- [`i18n/README.fr-FR.md`](i18n/README.fr-FR.md);
- [`i18n/README.pt-BR.md`](i18n/README.pt-BR.md).

No existe ni debe crearse `i18n/README.es-MX.md`: esta página ya es la versión
es-MX.

## La propiedad a la que sirve todo lo demás

**Nunca fallar en silencio.** La latencia era el problema fácil: se resolvió en
una tarde en cuanto el servidor pudo avisar solo. Todo lo demás que hay aquí
existe porque el fallo caro no es ir lento, es **decir con confianza que no hay
correo nuevo estando ciego**.

Por eso el último mensaje visto se guarda uno por uno, por eso en cada conexión se
revisa que el buzón siga siendo el mismo, por eso la bitácora de errores se vigila
junto con la de eventos, y por eso al arrancar una sesión se pregunta si el
servicio de verdad está corriendo. [`DESIGN.md`](DESIGN.md) explica cada uno y qué
se rompe sin él.

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

<sub>Este archivo es la fuente de verdad. Las versiones en otros idiomas son
traducciones: si alguna contradice a esta, **gana el español (MX)**.</sub>
