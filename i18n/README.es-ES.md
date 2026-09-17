<h1>
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="../brand/paynani-horizontal-claro.svg">
    <img src="../brand/paynani-horizontal.svg" alt="paynani" height="52">
  </picture>
</h1>

Mensajero de élite: los paynani eran los corredores y mensajeros oficiales del Imperio Azteca.

[Español (MX)](../README.md) · [English (US)](README.en-US.md) · **Español (ES)** · [Français (FR)](README.fr-FR.md) · [Português (BR)](README.pt-BR.md)

Paynani permite que tu agente de IA lea automáticamente su correo electrónico
unos segundos después de que llega, procese los mensajes recibidos y atienda las
instrucciones del correo tal como lo haría un colaborador humano.

Todos los correos recibidos se leen, pero solo se siguen las instrucciones de los
correos que vienen de una lista de contactos autorizados. Esa lista la escribes
tú, y vive en un fichero llamado `roster.md`.

Paynani está construido sobre
[Himalaya](https://github.com/pimalaya/himalaya) y funciona con una cuenta de
correo corriente, del mismo tipo que configurarías en cualquier programa de
correo.

**¡Usarlo es totalmente gratis!** No necesitas contratar ningún servicio
adicional para darle a tu agente una dirección de correo electrónico que pueda
usar por su cuenta.

Se ejecuta en tu propio ordenador o servidor, dentro del programa que ya aloja a
tu agente. A ese programa anfitrión se le llama *harness*, y así se usa la
palabra en el resto de esta página. Actualmente Paynani lo usan agentes de IA
como OpenClaw, Hermes Agent, Claude Code, OpenAI Codex y OpenCode.

Desarrollado y probado en Linux (Ubuntu 24.04) y macOS (26.4.1).

Hecho con amor por humanos y agentes de IA, desde México para el mundo.

---

## Antes de empezar

Necesitas tres cosas:

1. una cuenta de correo dedicada al agente, no tu correo personal;
2. acceso a un terminal en la máquina donde se ejecuta tu agente;
3. un momento para escribir tú la contraseña, en el formulario que te dará el
   agente o a mano en un fichero, sin pegarla nunca en un chat.

Nada más. No hace falta una API de correo, ni un servicio intermedio, ni una
cuenta nueva en ningún sitio.

## Instalación

Tres pasos: enviarle un prompt al agente, rellenar el formulario que él mismo te
dará en cuanto lo necesite, y dos minutos tuyos al final para comprobar que de
verdad funciona.

### Paso 1: Prompt de instalación

Envía el siguiente prompt a tu agente:

```text
Instala este repositorio:
https://github.com/iaaorgmx/paynani

Sigue las instrucciones del
fichero AGENTS.md del
repositorio.

Cuando necesites la cuenta
de correo, enséñame el
enlace del formulario para
configurarla.
```

### Paso 2: Configuración de la cuenta de correo

Tu agente te enseñará un enlace al formulario para configurar la cuenta de
correo.

Si tu agente se ejecuta en una máquina a la que no llegas directamente desde el
navegador, junto con el enlace te dará el comando `ssh -L` para llegar al
formulario.

Si tu agente se ejecuta en OpenCode, o en otro harness que no le avisa cuando
guardas el formulario, te pedirá que le escribas «listo» después de guardar.
Escríbeselo para que siga con la instalación.

Si lo prefieres, puedes configurarla a mano creando el fichero `.env` como
indica [`MAILBOX_SETUP.es-ES.md`](MAILBOX_SETUP.es-ES.md).

Al guardar, el formulario también crea `roster.md` con tu nombre y tu correo
como primer contacto autorizado. Si escribes el `.env` a mano, el agente crea
`roster.md` durante la instalación, o puedes crearlo tú con
`scripts/paynani roster add "Tu Nombre" tu@correo.example`.

> [!CAUTION]
> Escribe tú la contraseña, directamente en el formulario. Nunca la pegues en el
> chat con el agente: lo que pegas en una conversación se queda ahí para
> siempre.

### Paso 3: Pruebas

El agente ejecuta su propia lista de verificación, pero te recomendamos hacer
también estas pruebas.

**Prueba 1: Envía un correo a tu agente desde tu cuenta.**

Desde tu cuenta de correo, la misma que pusiste en la configuración anterior,
envía un correo electrónico a tu agente pidiéndole que te responda.

**Ejemplo de correo**

```text
Asunto: Prueba #1 de paynani: ñ, á, ¿qué tal?

Hola, {nombre de tu agente}:

Responde a este correo con el asunto
tal y como lo ves.
```

La respuesta tiene que traer el asunto legible. Si ves `=?utf-8?q?...`, algo
está roto en la forma en que lee las cabeceras.

**Prueba 2: Envía un correo a tu agente desde una cuenta que no está en
`roster.md`.**

Cuando paynani recibe un correo desde una dirección que no está en `roster.md`,
el agente te avisa de que ha llegado, pero no actúa sobre él. Deberías recibir
ese aviso y ninguna respuesta en la otra cuenta.

La lista de contactos de `roster.md` es toda la razón por la que es seguro dejar
que un agente que lee correo también pueda responderlo y actuar, así que merece
la pena verla funcionar una vez con tus propios ojos.

## ¿Para quién es Paynani?

Para quien quiere darle a su agente una dirección de correo de verdad sin mezclar
ahí su buzón personal, sus contraseñas ni sus decisiones de confianza.

Te sirve si quieres que tu agente:

- reciba tareas por correo, tuyas o de tu equipo;
- te avise cuando llegue algo que merezca la pena mirar;
- conteste desde su propia cuenta, no desde la tuya;
- se niegue a obedecer, o a escribir, a quien no esté en tu lista.

No sirve para delegar tu criterio en cualquier mensaje que llegue. El correo lo
manda cualquiera, así que Paynani trata todo lo que entra como no fiable hasta
que el remitente coincide con tu lista.

## ¿Qué va a poder hacer tu agente?

- **Enterarse de correo nuevo en cosa de un segundo**, sin ir comprobando y sin
  que se lo pidas.
- **Leer y enviar** desde el buzón que has configurado.
- **Enviar solo a direcciones que tú has aprobado**, las de tu lista. Cualquier
  otra se rechaza de plano, ni siquiera te pregunta.
- **Trabajar con el correo que mandan esas mismas direcciones aprobadas.** Le
  escribes una tarea, la hace y te manda la respuesta por correo. Sin acuse previo
  y sin pedirte permiso; ya se lo diste al ponerte en la lista.
- **Dejar en paz el correo de los demás.** Lo que llega de una dirección que no
  está en la lista te lo informa, y nada más.
- **No perder lo que ha llegado** si la máquina se reinicia a media tarea. Cada
  mensaje detectado se anota en disco antes de entregarse.

## ¿Qué cambia en el ordenador?

Merece la pena saberlo antes de aceptar. El agente tiene instrucciones de
informarte de todo esto cuando termine, y puedes exigirle la lista:

- **Dos servicios que quedan ejecutándose todo el tiempo** y se reinician solos
  si fallan: el que escucha el buzón y el que entrega los mensajes a tu agente.
  Se instalan como servicios de tu usuario, no del sistema.
- **Dos más que solo se encargan de recortar los registros** para que no crezcan
  sin fin.
- **Un fichero con la contraseña del buzón**, legible solo por tu usuario. Se lee
  donde tú lo has dejado y nunca se copia a otro sitio.
- **Ficheros de registro y estado** dentro de la carpeta del proyecto.
- **Permiso para que esos servicios sigan vivos cuando cierras sesión.**
- **Una regla permanente añadida a las instrucciones del propio agente.**
- **En OpenCode, un fichero más:** el plugin que le pasa el correo a tu sesión,
  en `~/.config/opencode/plugins/paynani.js`.

Todo esto es reversible; [`UNINSTALL.md`](../UNINSTALL.md) quita cada punto de esa
lista, en un orden que no te deja trabajando de memoria.

<details>
<summary>Los nombres exactos, si los necesitas</summary>

Cuatro unidades de usuario de systemd, no una. Dos se ejecutan todo el tiempo y
se reinician solas si fallan: el escucha (`paynani-idle.service`) y el repartidor
(`paynani-dispatch.service`). Las otras dos rotan los registros:
`paynani-logrotate.timer`, que se activa solo, y `paynani-logrotate.service`, que
es `static` porque lo dispara el temporizador y no se habilita por su cuenta. En
macOS son tres *LaunchAgents* equivalentes: `com.paynani.idle`,
`com.paynani.dispatch` y `com.paynani.logrotate`.

El fichero de credenciales lleva permisos `600`: el `.env` del workspace de tu
harness si lo guardas ahí, y si no, `.env` dentro del clon. Los registros y el
estado viven en `state/`, dentro del clon. El *lingering* es lo que mantiene vivos
los servicios después de cerrar sesión.

</details>

`.gitignore` mantiene los secretos fuera de `git status` y `scripts/install.sh`
se niega a escribir si alguno está versionado o no ignorado. Lo que eso no evita
es `git clean -xdf`, que borra los ficheros ignorados: en una instalación viva
eso es la contraseña del buzón, los dos secretos de ruta de Hermes
(`<clon>/hermes/`, solo en Hermes), la lista de destinatarios y la marca del
último mensaje visto. Usa `git clean -df`.

## Seguridad y límites

> [!WARNING]
> Tu lista de contactos autorizados decide de quién acepta trabajo tu agente. No
> demuestra quién es esa persona. Un correo de alguien que no está en la lista se
> te informa, y ahí se queda.

El agente trabaja desde su correo, así que la pregunta no es si obedece
instrucciones que llegan por email. Sí lo hace, ese es el sentido. La pregunta es
**de quién**.

- `roster.md` es una lista de coincidencia exacta, y es toda la respuesta. Si el
  remitente está en la lista, el agente hace lo que el mensaje pide y contesta. Si
  no está, te avisa de que ha llegado el correo y no hace nada más con él.
- La coincidencia es sobre el remitente que trae el mensaje, y solo sobre ese. Un
  desconocido no puede tomar prestada una dirección de tu lista poniéndola en otro
  campo.
- **Con una excepción que tú declaras:** los *notificadores*. Si tu equipo se
  coordina en una plataforma que manda correo en nombre de la gente (GitHub, Jira,
  Linear), puedes declarar su dirección y contra qué parte de tu lista cotejar al
  autor. Entonces esa notificación cuenta como correo de esa persona. Declarar un
  notificador amplía a quién hace caso tu agente, igual que añadir una fila, y se
  decide igual: nunca porque un mensaje lo haya pedido.
- **Añadir a alguien a la lista es decisión tuya**, nunca respuesta a algo que ha
  llegado por correo. Esa línea es lo que convierte a un remitente en alguien a
  quien tu agente obedece.
- Sin lista no hay nadie de confianza. Una instalación nueva lee correo y no actúa
  sobre nada hasta que tú la escribas.

Merece la pena saber en qué se apoya todo esto: tu proveedor de correo. Los
filtros que traen Gmail, Outlook y los demás son los que evitan que falsificar un
remitente sea trivial, y se aplican antes de que el mensaje llegue a la bandeja.
Si apuntas Paynani a un buzón sin ese filtrado, la lista protege menos de lo que
parece.

## Cómo saber si está sano

> [!IMPORTANT]
> Que no haya mensajes pendientes no demuestra que Paynani esté sano. También se
> ve así cuando ha dejado de escuchar.

Pídele a tu agente que ejecute la comprobación de salud y que te enseñe la salida:

```bash
python3 scripts/healthcheck.py
```

Revisa los servicios, las credenciales, la cola de mensajes, la entrega a tu
agente y la lista de autorizados. Lo que quieres ver es que los servicios están
vivos, que no hay nada atascado y que la configuración se está leyendo del sitio
correcto. Si algo falla, el informe te dice qué pieza, no solo que no hay correo.

En OpenCode, el informe también dice en cuál de tres estados está: entregando
el correo a tu sesión, abierto pero esperando a que escribas algo en una sesión,
o cerrado. Con OpenCode cerrado el correo espera sin perderse, y eso es normal.

Las opciones largas y los modos de fallo están en [`INSTALL.md`](../INSTALL.md).

## Cómo está construido, en corto

Un servicio mantiene abierta una conexión con tu servidor de correo, del tipo en
que el servidor avisa solo en cuanto llega algo, sin que nadie tenga que estar
preguntando. Cuando llega un mensaje, ese servicio lo anota en disco antes de
hacer nada más. Un segundo servicio lee esas anotaciones y se las entrega a tu
agente, y solo marca una como entregada cuando el agente confirma que la ha
recibido.

Esa separación es la que evita perder correo cuando algo se cae a medias.
[`DESIGN.md`](../DESIGN.md) explica cada pieza, por qué está así y qué se rompe si
se quita.

## Qué pertenece a este repositorio

Aquí vive la instalación, los dos servicios, los scripts de envío, la lista de
autorizados, las pruebas y la documentación de operación.

Aquí no vive tu buzón, ni tu contraseña, ni una garantía de que quien escribe es
quien dice ser. Eso le toca a tu proveedor de correo, a tu fichero `.env` y a tu
propio criterio sobre a quién le das entrada.

## Si quieres..., lee...

| Si quieres... | Lee |
|---|---|
| Preparar el buzón sin exponer contraseñas | [`MAILBOX_SETUP.es-ES.md`](MAILBOX_SETUP.es-ES.md) |
| Instalar Paynani | [`AGENTS.md`](../AGENTS.md) e [`INSTALL.md`](../INSTALL.md) |
| Integrarlo con Hermes Agent | [`HERMES.md`](../HERMES.md) |
| Entender por qué no debe fallar en silencio | [`DESIGN.md`](../DESIGN.md) |
| Migrar desde agenteiamail | [`MIGRATION.md`](../MIGRATION.md) |
| Quitar Paynani | [`UNINSTALL.md`](../UNINSTALL.md) |
| Ver cambios por versión | [`CHANGELOG.md`](../CHANGELOG.md) |
| Autorizar remitentes | `roster.md` y [`roster.md.example`](../roster.md.example) |
| Enviar correo desde la frontera segura | [`scripts/send.sh`](../scripts/send.sh) |

## Cómo mantenerlo al día

La versión instalada está en [`VERSION`](../VERSION), y al agente se le dice cuál
está ejecutando al inicio de cada sesión, junto con si ya ha salido alguna más
nueva.

Puedes preguntarle lo mismo directamente:

```bash
scripts/version.sh
```

Lee la versión publicada de las etiquetas de este repositorio, así que no hay
cuenta ni token de por medio, y avisa claramente cuando no ha podido alcanzar la
red, en vez de dar por actualizada una instalación solo porque nada lo ha
contradicho.

Actualizar es [`UPGRADE.md`](../UPGRADE.md), y lo que ha cambiado entre dos
versiones está en [`CHANGELOG.md`](../CHANGELOG.md). Lee primero el changelog: de
vez en cuando una versión necesita algo más que un `git pull`, y la forma en que
falla saltárselo es un servicio que funciona hasta el siguiente reinicio.

## Idiomas

`README.md` es la fuente en español de México. Las traducciones mantenidas son:

- [`i18n/README.en-US.md`](README.en-US.md);
- [`i18n/README.es-ES.md`](README.es-ES.md);
- [`i18n/README.fr-FR.md`](README.fr-FR.md);
- [`i18n/README.pt-BR.md`](README.pt-BR.md).

No existe ni debe crearse `i18n/README.es-MX.md`: la página fuente ya es la
versión es-MX.

## La propiedad a la que sirve todo lo demás

**Nunca fallar en silencio.** La latencia era el problema fácil: se resolvió en
una tarde en cuanto el servidor pudo avisar solo. Todo lo demás que hay aquí
existe porque el fallo caro no es ir lento, es **decir con confianza que no hay
correo nuevo estando ciego**.

Por eso el último mensaje visto se guarda uno a uno, por eso en cada conexión se
comprueba que el buzón siga siendo el mismo, por eso el registro de errores se
vigila junto con el de eventos, y por eso al arrancar una sesión se pregunta si el
servicio de verdad se está ejecutando. [`DESIGN.md`](../DESIGN.md) explica cada
uno y qué se rompe sin él.

Construido y verificado de extremo a extremo el 2026-08-09.

## De dónde viene el nombre

**paynani** es náhuatl clásico y significa, sin adornos, *«el que corre
ligeramente»*: del verbo `paina` («correr ligeramente», en el vocabulario de
Alonso de Molina, 1571) más el sufijo `-ni`, que convierte una acción en quien la
hace de oficio.

La grafía varía porque los frailes del siglo XVI escribieron el náhuatl con las
convenciones del español de su época, en las que `i`, `y` y `j` se usaban casi
indistintamente. El Gran Diccionario Náhuatl indexa los mismos pasajes del Códice
Florentino bajo `painani` y bajo `painanj`, y registra `payna` como variante de
`paina`: son la misma palabra. Aquí se escribe `paynani`, que es la forma que un
lector hispanohablante reconoce.

De esa cualidad salió el nombre del oficio. El náhuatl tenía dos maneras de
nombrar al mensajero imperial: `titlantli`, «el enviado», que lo define por el
encargo que lleva, y `paynani`, que lo define por cómo se mueve. La que se quedó
pegada a esos hombres fue la segunda: se los conocía por la manera de correr, no
por quién los mandaba.

Los corredores trabajaban por relevos, con postas llamadas `techialoyan`, y se
entrenaban desde niños. De todo lo que se cuenta de ellos hay un detalle que es
justo lo que hace esta herramienta: **el mensajero clasificaba la noticia antes de
abrir la boca.** Si llegaba con el pelo suelto y revuelto traía una derrota, y no
se le daba ni el saludo; si llegaba con el pelo trenzado y una cinta de color, con
escudo y macana, traía una victoria y la gente lo seguía hasta el palacio. Eso es
lo que hace aquí la etiqueta `roster`: el sobre dice cómo recibir la noticia antes
de que se lea.

De la misma raíz viene Paynal, el que corría en lugar de Huitzilopochtli en las
procesiones. El Códice Florentino lo explica en tres palabras, *«el delegado, el
sustituto, el suplente»*, porque «lo apremiaban, lo hacían correr». Un agente que
va a por el correo en lugar de quien no puede estar en todas partes.

<sub>Fuentes: [Gran Diccionario Náhuatl](https://gdn.iib.unam.mx/diccionario/painani/233892)
(UNAM) · [Nahuatl Dictionary](https://nahuatl.wired-humanities.org/content/paina)
(Wired Humanities) · [Mexicolore](https://www.mexicolore.co.uk/aztecs/ask-experts/did-they-send-post-mail).</sub>

---

<sub>Traducido de [`README.md`](../README.md), que es la fuente de verdad. Si algo aquí contradice al original en español (MX), **manda el español**, y avísanos, porque significa que esta traducción se ha quedado atrás.</sub>
