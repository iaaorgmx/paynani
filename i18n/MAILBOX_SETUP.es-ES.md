# Configurar el fichero del buzón

[Español (MX)](../MAILBOX_SETUP.md) · [English](MAILBOX_SETUP.en-US.md) · **Español (ES)** · [Français](MAILBOX_SETUP.fr-FR.md) · [Português (BR)](MAILBOX_SETUP.pt-BR.md)

Paso 1 del [README](README.es-ES.md#cómo-configurarlo-en-tu-agente). Esto lo haces
tú, antes de involucrar al agente, porque hace falta una contraseña y una
contraseña no debe pasar por un chat.

Diez minutos, y la mayor parte se te va en encontrar un nombre de servidor.

> **Hay un formulario para esto.** Si escribir un fichero en una terminal no es lo
> tuyo, pídele al agente que ejecute `scripts/setup_web.sh`. Eso no rompe la regla
> de arriba: el agente solo levanta una página en su propia máquina y te pasa el
> enlace. La contraseña la escribes tú en la página, así que sigue sin pasar por el
> chat.
>
> La página pide los mismos datos que describe este documento, los comprueba contra
> tu servidor de correo y escribe el fichero por ti, incluido el problema del
> nombre del servidor que viene más abajo, que te lo diagnostica por su nombre en
> vez de dejarte dar con él. Ve [`webapp/README.md`](../webapp/README.md).
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
`mail.ejemplo.com`. Suele ser algo como `nc-ph-2488.xmhosting.com` o
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
cd ~/.hermes/workspace        # o ~/.openclaw/workspace, ~/.claude/workspace — tu harness
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

Vuelve al [README](README.es-ES.md#cómo-configurarlo-en-tu-agente) y pega el texto
del Paso 2. A partir de ahí se encarga el agente, y te preguntará si algo de esto
resulta faltar o estar mal.

**Una cosa que nunca debería pedirte: la contraseña.** Tiene la ruta del fichero y
puede leerlo cuando lo necesite. Si te pide que pegues la contraseña en el chat,
niégate, eso no es un paso de ninguna de estas instrucciones.

---

<sub>Traducido de [`MAILBOX_SETUP.md`](../MAILBOX_SETUP.md) en el commit `a7b1040`, que es la fuente de verdad. Si algo aquí contradice al original en español (MX), **manda el español**, y avísanos, porque significa que esta traducción se ha quedado atrás.</sub>
