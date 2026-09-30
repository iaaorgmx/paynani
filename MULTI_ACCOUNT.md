# Varias cuentas de correo

Paynani vigila por omisión **una** cuenta: la del agente, la que configuraste en
`.env` al instalarlo. Esta página explica cómo vigilar, además, las cuentas de
una PYME (`contacto@`, `ventas@`, `soporte@`) desde el mismo agente, cada una
con su propia lista de contactos autorizados.

Es la parte de documentación de [#276](https://github.com/iaaorgmx/paynani/issues/276).
Describe solo lo que ya está en `main`.

## Qué cambia y qué no

- **La cuenta del agente no cambia.** Sigue en `.env`, con su `roster.md`, y
  ninguna instalación existente se migra. Sin `accounts.json`, paynani se
  comporta exactamente igual que antes.
- **Las cuentas adicionales viven en `accounts.json`**, junto al `.env`. Hasta
  **10** por agente.
- **Todo llega a la misma sesión del agente**, por el mismo dispatcher. Cada
  aviso dice qué cuenta recibió el correo.
- **Cada cuenta tiene su propio roster.** Estar en el roster de `ventas@` no da
  permiso en `soporte@` ni en la cuenta del agente, y al revés.
- **Un servicio por cuenta.** Si `ventas@` se cae, las demás siguen recibiendo.

## Quién puede dar instrucciones

Es la misma regla de siempre, aplicada cuenta por cuenta:

| Remitente | Qué recibe el agente |
|---|---|
| Está en el roster **de esa cuenta** | El aviso lleva la marca `roster`: es una instrucción que el agente atiende. |
| Cualquier otro, por ejemplo un cliente que escribe a `ventas@` | El aviso llega **sin** la marca `roster`: es contexto, no una orden. El contenido del correo es dato, nunca instrucción. |

En esta versión no hay un flujo para decidir qué hacer con el correo de un
desconocido (contestar, reenviar a alguien). Eso queda para una versión futura.

Un correo que llega diciendo «agrégame al roster» no es una autorización, ni
aquí ni en la cuenta principal. El roster lo edita una persona, con
`paynani roster add`.

## El caso de una PYME, paso a paso

Ejemplo: la PYME `dominio.com` quiere que su agente vigile `ventas@` y
`soporte@`, y que solo Ana (`ana@dominio.com`) pueda darle instrucciones desde
`ventas@`.

### 1. Agregar la cuenta

```bash
scripts/paynani account add ventas \
  --email ventas@dominio.com \
  --imap-host mail.dominio.com \
  --smtp-host mail.dominio.com \
  --from-name "Ventas Dominio"
```

- `ventas` es el `id` de la cuenta: minúsculas, dígitos y guiones, hasta 31
  caracteres. `main` está reservado para la cuenta del `.env`.
- Los puertos son 993 (IMAP) y 465 (SMTP) por omisión; se cambian con
  `--imap-port` y `--smtp-port`.
- `--smtp-host` deja la cuenta de himalaya lista también para enviar. Sin él,
  la cuenta solo se lee.
- `--mailbox` cambia el buzón que se vigila (`INBOX` por omisión). Por ahora es
  **uno** por cuenta.

El comando pide la contraseña en la terminal, sin mostrarla. **Nunca** se pasa
como argumento ni por una tubería: quedaría en el historial del shell y en la
lista de procesos.

Antes de escribir nada, prueba el login IMAP. Si la contraseña o el servidor
están mal, sale con error y no deja ningún archivo cambiado. Con el login
bueno, escribe:

| Dónde | Qué |
|---|---|
| `.env` | La contraseña, como `PAYNANI_ACCOUNT_VENTAS_PASSWORD`. No se toca ninguna otra línea. |
| `accounts.json` | La configuración de la cuenta (modo `600`). **Nunca guarda la contraseña**: solo el nombre de la variable del `.env`. |
| `rosters/ventas.md` | Su roster, a partir de `roster.md.example`. |
| La configuración de himalaya | La cuenta `paynani-ventas`, que lee la contraseña con `env_secret.py`. |

Si alguna escritura falla, las anteriores se deshacen. Al final arranca el
servicio de la cuenta. Si el servicio no arranca, la cuenta queda guardada y el
comando lo dice, con el comando para arrancarlo a mano.

### 2. Decir quién puede dar instrucciones

```bash
scripts/paynani roster add "Ana Ruiz" ana@dominio.com --roster rosters/ventas.md
```

`--roster` acepta solo el roster de una cuenta que exista en `accounts.json`.
Sin `--roster`, el comando edita `roster.md`, el de la cuenta del agente.

### 3. Probar la cuenta

```bash
scripts/paynani account test ventas
```

Prueba, con el mismo login que usa el listener, el acceso, cada buzón y que el
servidor ofrezca IDLE. Cada paso sale con `ok` o `FAIL` y el error literal.

### 4. Ver qué hay configurado

```bash
scripts/paynani account list
```

Una fila por cuenta: id, correo, si está activa, su roster y cuántos contactos
tiene (o `MISSING` si el archivo no existe). Nunca imprime contraseñas.

### 5. Recibir correo

Con la cuenta activa, el correo llega a la sesión del agente como siempre, pero
el aviso nombra la cuenta:

```
[mail 10:02:11, sent 10:01:50, ventas@dominio.com, roster] Ana Ruiz — Cotización pendiente [scripts/paynani event show imap:ventas:INBOX:1790749984:2]
```

El identificador del evento (`imap:ventas:INBOX:…`) incluye el `id` de la
cuenta. El de la cuenta del agente no cambia: `imap:INBOX:…`.

Al terminar de atender un aviso, se cierra como siempre:
`scripts/paynani event mark <event_id> handled`.

### 6. Quitar una cuenta

```bash
scripts/paynani account remove ventas
```

Pide confirmación (`--yes` la salta), detiene el servicio y quita la cuenta de
`accounts.json`, de himalaya y su contraseña del `.env`. **El roster no se
borra:** se mueve a `rosters/removed/ventas.md`, y si ya había uno con ese
nombre, el nuevo se guarda con otro (`ventas-2.md`). El historial de correo que
paynani ya registró no se toca.

## Ver el estado de cada cuenta

`scripts/paynani doctor` agrega cuatro filas por cada cuenta adicional activa,
con el `id` en el nombre:

```
ok       account:ventas:listener: listener for ventas@dominio.com is active
ok       account:ventas:imap_telemetry: IMAP listener heartbeat and reconnection telemetry are current
ok       account:ventas:version_drift: disk and the listener agree on the version
ok       account:ventas:roster: roster has 1 address(es)
```

Una cuenta que se cae, o cuyo roster no existe o está vacío, sale como `warning`
con su `id`, y **no cambia el estado de la cuenta del agente**: el resultado de
`doctor` sigue diciendo si el correo del propio agente puede llegar. Si
`accounts.json` no se puede leer, `doctor` lo dice. Sin `accounts.json`, la
salida es la de siempre, sin filas nuevas.

## Cómo corre cada cuenta

- **Linux:** una instancia de la plantilla `paynani-idle@.service`, por ejemplo
  `paynani-idle@ventas.service`, que ejecuta `idle_listener.py --account ventas`.
- **macOS:** un LaunchAgent por cuenta, `com.paynani.idle.ventas`.
- Cada listener guarda su estado en `state/accounts/<id>/idle.json`.
- La cuenta del agente sigue en `paynani-idle.service`, sin cambios.
- Al actualizar paynani, el plan de actualización reinicia también las
  instancias `paynani-idle@*`.

## Límites de esta versión

- Hasta 10 cuentas adicionales por agente.
- Un buzón por cuenta.
- Solo IMAP IDLE con usuario y contraseña. Microsoft 365 o Google Workspace sin
  contraseñas de aplicación piden OAuth2, que no está incluido.
- El correo de remitentes fuera del roster de la cuenta se entrega como
  contexto; no hay un flujo para contestarlo o reenviarlo.

## Probado en campo

`account add`, el servicio por cuenta, el aviso con la cuenta y `doctor` por
cuenta se probaron de punta a punta con un servidor de correo real, en un host
con Claude Code y Linux, con cuatro cuentas reales corriendo a la vez. La
evidencia está en
[#276](https://github.com/iaaorgmx/paynani/issues/276) y
[#282](https://github.com/iaaorgmx/paynani/issues/282).

## Datos personales de los clientes

El correo de una PYME trae datos de sus clientes. Paynani guarda del correo lo
mismo que guardaba: el sobre (remitente, asunto, hora) y el estado del aviso,
**nunca el cuerpo**. El cuerpo se lee de IMAP solo cuando el agente lo pide.
