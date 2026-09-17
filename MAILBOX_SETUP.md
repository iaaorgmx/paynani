# Configurar el archivo del buzón

**Español (MX)** · [English (US)](i18n/MAILBOX_SETUP.en-US.md) · [Español (ES)](i18n/MAILBOX_SETUP.es-ES.md) · [Français (FR)](i18n/MAILBOX_SETUP.fr-FR.md) · [Português (BR)](i18n/MAILBOX_SETUP.pt-BR.md)

Referencia para el Paso 2 del [README](README.md#instalación):
qué cuenta usar y qué significa cada dato, tanto si lo llenas en el formulario
que te va a dar el agente como si escribes el archivo tú mismo. Normalmente ese
paso lo hace el agente por ti: te pasa un enlace y ahí llenas la contraseña,
nunca en el chat. Solo hace falta leer esto de principio a fin si vas a
escribir el archivo a mano.

Diez minutos, y la mayoría se te van en encontrar un nombre de servidor.

> **Hay un formulario para esto.** Si escribir un archivo en una terminal no es lo
> tuyo, pídele al agente que corra `scripts/paynani onboard`. Eso no rompe la
> regla de arriba: el agente solo levanta una página en su propia máquina y te
> pasa el enlace. La contraseña la escribes tú en la página, así que sigue sin
> pasar por el chat.
>
> La página pide los mismos datos que describe este documento, los revisa contra tu
> servidor de correo y escribe el archivo por ti, incluido el problema del nombre
> del servidor que viene más abajo, que te lo diagnostica por su nombre en vez de
> dejarte encontrarlo.
>
> Para cambiar un solo dato más adelante, como rotar la contraseña o corregir un
> nombre de servidor, no hace falta repetir todo esto: `paynani set CLAVE
> VALOR` cambia esa clave sola, y por omisión vuelve a probarla contra tu
> servidor antes de guardarla.
>
> El resto de esta página es la ruta manual, y vale la pena leerla de todos modos:
> explica *por qué* cada ajuste es lo que es, y eso el formulario no lo puede
> hacer.

---

## Qué necesitas primero

**Un buzón propio para el agente.** No el tuyo. El agente va a leer todo lo que
llegue ahí y puede enviar desde esa cuenta, así que dale una cuenta que le
confiarías a alguien nuevo en su primer día.

**Una contraseña de aplicación, si tu proveedor las ofrece.** Fastmail, Zoho, casi
todo el hosting empresarial y Google Workspace las tienen. Se pueden revocar sin
cambiar tu propia contraseña, y eso importa el día que quieras quitarle el acceso.

**El nombre real del servidor de correo.** Esta es la parte que todo el mundo se
equivoca, así que tiene su propia sección abajo.

---

## El nombre del servidor, y por qué es la parte latosa

Tu dirección de correo termina en un dominio: `ejemplo.com`. El servidor donde de
verdad vive tu correo casi nunca es `ejemplo.com`, y casi nunca es
`mail.ejemplo.com` tampoco. Suele ser algo como `s1042.hosting.example.net` o
`imappro.zoho.com`.

`mail.ejemplo.com` muchas veces **sí** resuelve, y ahí está la trampa: se ve bien,
conecta, y luego resulta que el certificado TLS está emitido para el servidor de
abajo y no para tu nombre bonito. La verificación falla, y como un error de
certificado llega disfrazado de error de red, el listener se queda reintentando
para siempre con `connection lost` en la bitácora y nada que diga por qué.

**Dónde encontrar el bueno:**

- **cPanel:** Cuentas de correo → *Conectar dispositivos* (o *Configurar cliente de
  correo*). Usa los datos **seguros/SSL**, no los inseguros.
- **Google Workspace:** `imap.gmail.com` / `smtp.gmail.com`, y es obligatorio usar
  contraseña de aplicación.
- **Zoho:** `imappro.zoho.com` / `smtppro.zoho.com`.
- **Cualquier otro:** busca "IMAP settings" en su documentación.

**Compruébalo antes de anotarlo.** Esto imprime los nombres que el certificado
cubre de verdad. El que uses tiene que ser uno de ellos:

```bash
openssl s_client -connect TU_SERVIDOR:993 -servername TU_SERVIDOR </dev/null 2>/dev/null \
  | openssl x509 -noout -subject -ext subjectAltName
```

Si el nombre que escribiste no aparece en esa salida, usa uno que sí aparezca.

---

## Crea el archivo

Si tu agente corre bajo un harness, este archivo va en la carpeta workspace de
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
contraseña, no después; un archivo que estuvo un rato legible para todos ya pudo
haber sido leído.

Luego ábrelo en un editor y llena:

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
tienes duda, prueba primero el `465`.

**Usa un editor, no `echo`.** Todo lo que escribes en la línea de comandos se queda
en el historial de tu shell, y ese historial es un archivo que vive meses.

---

## Y luego

Si escribiste el archivo a mano antes de meter al agente, regresa al
[README](README.md#instalación) y envíale al agente el prompt del Paso 1.
De ahí en adelante lo lleva el agente, y te va a preguntar si algo de esto
resultó faltar o estar mal.

**Una cosa que nunca debería pedirte: la contraseña.** Tiene la ruta del archivo y
puede leerlo cuando lo necesite. Si te pide que pegues la contraseña en el chat,
dile que no, eso no es un paso de ninguna de estas instrucciones.

**Tu fila en la lista de contactos autorizados.** El formulario de
`scripts/paynani onboard` pide, además de estos siete datos del buzón, tu
nombre y tu correo, y al guardar te agrega a `roster.md`, creando la lista si
todavía no existe. Esta ruta manual no pasa por el formulario, así que la
lista no se crea sola: el agente la crea durante la instalación y te agrega, o
te pide tu nombre y tu correo si no los tiene. Si prefieres hacerlo tú, corre
`scripts/paynani roster add "Tu Nombre" tu@correo.example`: crea `roster.md` a
partir de la plantilla si todavía no existe y te agrega como primer contacto.

---

<sub>Este archivo es la fuente de verdad. Las versiones en otros idiomas son traducciones: si alguna contradice a esta, **gana el español (MX)**.</sub>
