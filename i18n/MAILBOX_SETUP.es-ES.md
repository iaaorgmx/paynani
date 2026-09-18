# Configurar el fichero del buzón

[Español (MX)](../MAILBOX_SETUP.md) · [English (US)](MAILBOX_SETUP.en-US.md) · **Español (ES)** · [Français (FR)](MAILBOX_SETUP.fr-FR.md) · [Português (BR)](MAILBOX_SETUP.pt-BR.md)

Referencia para el Paso 2 del [README](README.es-ES.md#instalación): qué cuenta
usar y qué significa cada dato, tanto si lo rellenas en el formulario que te
dará el agente como si escribes el fichero tú mismo. Normalmente ese paso lo
hace el agente por ti: te pasa un enlace y ahí rellenas la contraseña, nunca en
el chat. Solo hace falta leer esto de principio a fin si vas a escribir el
fichero a mano.

Diez minutos, y la mayor parte se te va en encontrar un nombre de servidor.

> **Hay un formulario para esto.** Si escribir un fichero en una terminal no es lo
> tuyo, pídele al agente que ejecute `scripts/paynani onboard`. Eso no rompe la
> regla de arriba: el agente solo levanta una página en su propia máquina y te pasa
> el enlace. La contraseña la escribes tú en la página, así que sigue sin pasar por
> el chat.
>
> La página pide los mismos datos que describe este documento, los comprueba contra
> tu servidor de correo y escribe el fichero por ti, incluido el problema del
> nombre del servidor que viene más abajo, que te lo diagnostica por su nombre en
> vez de dejarte dar con él.
>
> Para cambiar un solo dato más adelante, como rotar la contraseña o corregir un
> nombre de servidor, no hace falta repetir todo esto: `paynani set CLAVE VALOR`
> cambia solo esa clave y, por defecto, vuelve a probarla contra tu servidor
> antes de guardarla.
>
> El resto de esta página es la ruta manual, y merece la pena leerla igualmente:
> explica *por qué* cada ajuste es lo que es, y eso el formulario no puede
> hacerlo.

---

## Qué necesitas primero

**Un buzón propio para el agente.** No el tuyo. El agente leerá todo lo que llegue
ahí y puede enviar desde esa cuenta, así que dale una cuenta que confiarías a
alguien nuevo en su primer día.

**Una contraseña de aplicación, si tu proveedor las ofrece.** Fastmail, Zoho, la
mayoría del hosting profesional y Google Workspace las tienen. Se pueden revocar
sin cambiar tu propia contraseña, y eso importa el día que quieras retirar el
acceso.

**El nombre real del servidor de correo.** Esta es la parte que todo el mundo se
equivoca, así que tiene su propia sección más abajo.

---

## El nombre del servidor, y por qué es la parte pejiguera

Tu dirección de correo termina en un dominio: `ejemplo.com`. El servidor donde
realmente vive tu correo casi nunca es `ejemplo.com`, ni suele ser
`mail.ejemplo.com`. Suele ser algo como `s1042.hosting.example.net` o
`imappro.zoho.com`.

`mail.ejemplo.com` a menudo **sí** resuelve, y ahí está la trampa: parece
correcto, conecta, y luego resulta que el certificado TLS está emitido para el
servidor subyacente y no para tu nombre de vanidad. La verificación falla, y como
un error de certificado llega con aspecto de error de red, el listener se queda
reintentando indefinidamente con `connection lost` en el registro y nada que
explique por qué.

**Dónde encontrar el bueno:**

- **cPanel:** Cuentas de correo → *Conectar dispositivos* (o *Configurar cliente de
  correo*). Usa los datos **seguros/SSL**, no los inseguros.
- **Google Workspace:** `imap.gmail.com` / `smtp.gmail.com`, y es obligatorio usar
  contraseña de aplicación.
- **Zoho:** `imappro.zoho.com` / `smtppro.zoho.com`.
- **Cualquier otro:** busca "IMAP settings" en su documentación.

**Compruébalo antes de anotarlo.** Esto imprime los nombres que el certificado
cubre realmente. El que uses tiene que ser uno de ellos:

```bash
openssl s_client -connect TU_SERVIDOR:993 -servername TU_SERVIDOR </dev/null 2>/dev/null \
  | openssl x509 -noout -subject -ext subjectAltName
```

Si el nombre que has escrito no aparece en esa salida, usa uno que sí aparezca.

---

## Crea el fichero

Si tu agente corre bajo un harness, este fichero va en la carpeta workspace de
ese harness, que es donde se le dice al agente que mire:

```bash
cd ~/.hermes/workspace        # o ~/.openclaw/workspace, ~/.claude/workspace, ~/.codex/workspace, ~/.opencode/workspace (tu harness)
touch .env
chmod 600 .env
```

En un host sin harness, ponlo en la raíz del clon:

```bash
cd /ruta/a/tu/clon
touch .env
chmod 600 .env
```

`chmod 600` significa que solo tu usuario puede leerlo. Hazlo **antes** de poner la
contraseña, no después; un fichero que estuvo un rato legible para todos ya pudo
haber sido leído.

Luego ábrelo en un editor y rellena:

```bash
AGENT_EMAIL_ACCOUNT=agente@ejemplo.com
AGENT_EMAIL_PASSWORD=
AGENT_EMAIL_FROM_NAME=Tu Agente

AGENT_EMAIL_INCOMING_SERVER_IMAP_HOST=
AGENT_EMAIL_INCOMING_SERVER_IMAP_PORT=993

AGENT_EMAIL_OUTGOING_SERVER_SMTP_HOST=
AGENT_EMAIL_OUTGOING_SERVER_SMTP_PORT=465
```

**Puertos:** el `993` para IMAP es prácticamente universal. Para SMTP, el `465` es
TLS implícito y el `587` es STARTTLS; la página de tu proveedor dirá cuál. Si
dudas, prueba primero el `465`.

**Usa un editor, no `echo`.** Todo lo que escribes en la línea de comandos queda en
el historial de tu shell, y ese historial es un fichero que vive durante meses.

---

## Y después

Si has escrito el fichero a mano antes de involucrar al agente, vuelve al
[README](README.es-ES.md#instalación) y envía al agente el prompt del Paso 1. A
partir de ahí se encarga el agente, y te preguntará si algo de esto resulta
faltar o estar mal.

**Una cosa que nunca debería pedirte: la contraseña.** Tiene la ruta del fichero y
puede leerlo cuando lo necesite. Si te pide que pegues la contraseña en el chat,
niégate, eso no es un paso de ninguna de estas instrucciones.

**Firma opcional de salida.** Si quieres que `scripts/send.sh` añada una firma de
texto plano a cada respuesta, define `PAYNANI_SIGNATURE_FILE=/ruta/firma.txt` en
este mismo fichero.

**Tu fila en la lista de contactos autorizados.** El formulario de
`scripts/paynani onboard` pide, además de estos siete datos del buzón, tu nombre
y tu correo, y al guardar te añade a `roster.md`, creando la lista si todavía no
existe. Esta ruta manual no pasa por el formulario, así que la lista no se crea
sola: el agente la crea durante la instalación y te añade, o te pide tu nombre y
tu correo si no los tiene. Si prefieres hacerlo tú, ejecuta
`scripts/paynani roster add "Tu Nombre" tu@correo.example`: crea `roster.md` a
partir de la plantilla si todavía no existe y te añade como primer contacto.

---

<sub>Traducido de [`MAILBOX_SETUP.md`](../MAILBOX_SETUP.md) en el commit `9adbce6`, que es la fuente de verdad. Si algo aquí contradice al original en español (MX), **manda el español**, y avísanos, porque significa que esta traducción se ha quedado atrás.</sub>
