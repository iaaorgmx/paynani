# Cómo quitar paynani

**Español (MX)** · [English](i18n/UNINSTALL.en-US.md)

> Este archivo es la fuente de verdad. Las versiones en otros idiomas son
> traducciones: si alguna contradice a esta, **gana el español (MX)**.

Esto instala un servicio en segundo plano que toca seis lugares de la
computadora. Aquí está cómo quitarlo todo, sea para reinstalar limpio, para
entregar la máquina a alguien más, o porque cambiaste de opinión.

**Nada de lo que sigue toca el buzón.** El correo que ya se entregó se queda en
el servidor. Si además quieres que el agente pierda el acceso, revoca su
contraseña de aplicación con tu proveedor de correo, que es el único paso que no
se puede deshacer desde esta computadora.

Si la instalación es de las que registra su manifiesto de propiedad FR7, usa la
desinstalación que sabe qué le pertenece:

```bash
scripts/install.sh --runtime openclaw --uninstall --dry-run
scripts/install.sh --runtime openclaw --uninstall
```

Usa el runtime con el que se instaló. El comando que sí modifica valida todos los
archivos propios antes de tocar el primero, deshabilita y detiene las unidades
propias que alcance, y borra únicamente lo que quedó registrado en el manifiesto.
Deja a propósito las credenciales del buzón, `roster.md`, el repositorio, el
diario de eventos, el cursor, las bitácoras y demás estado. Si el gestor de
servicios de usuario de systemd no está disponible, la limpieza de archivos sigue
pero avisa que no pudo confirmar la desactivación del servicio. La salida `10`
significa que hubo cambios; `0` significa que no había manifiesto y no se quitó
nada. Un archivo propio que fue modificado se conserva y provoca un rechazo que
no cambia nada, con instrucciones para moverlo a un lado y reintentar.

El procedimiento manual y destructivo de abajo es para una instalación sin
manifiesto de propiedad, o para quien a propósito quiere borrar también las
credenciales, el estado y el repositorio.

---

## 0. Primero, si piensas reinstalar

**Copia tus archivos de unidad antes de tocar nada.** Son los únicos que tienes
que ya funcionan, y el paso 1 los borra.

```bash
mkdir -p ~/paynani-units-kept
cp ~/.config/systemd/user/paynani-*.service ~/paynani-units-kept/ 2>/dev/null
cp ~/.config/systemd/user/paynani-*.timer   ~/paynani-units-kept/ 2>/dev/null
ls -1 ~/paynani-units-kept/
```

**Anota también la URL del clon**, porque el paso 6 borra el repositorio y con él
cualquier registro de dónde vino:

```bash
git -C "$REPO" remote get-url origin
```

## 1. Detén y quita los servicios

### launchd en macOS

Para una instalación de OpenClaw en macOS:

```bash
scripts/install.sh --runtime openclaw --uninstall --dry-run
scripts/install.sh --runtime openclaw --uninstall
```

El equivalente manual:

```bash
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.paynani.idle.plist 2>/dev/null || true
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.paynani.dispatch.plist 2>/dev/null || true
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.paynani.logrotate.plist 2>/dev/null || true
rm -f ~/Library/LaunchAgents/com.paynani.idle.plist
rm -f ~/Library/LaunchAgents/com.paynani.dispatch.plist
rm -f ~/Library/LaunchAgents/com.paynani.logrotate.plist
```

Las credenciales, el roster, el estado, el diario, el cursor y las bitácoras se
conservan a menos que los borres explícitamente.

### systemd

**Haz un inventario primero.** Los nombres de abajo son los habituales, no
necesariamente los tuyos, y de aquí en adelante todo es destructivo:

```bash
systemctl --user list-unit-files | grep -i paynani
```

Una instalación completa tiene cuatro: `idle.service`, `dispatch.service`,
`logrotate.service` y `logrotate.timer`. El *servicio* de logrotate normalmente
es `static`: no tiene sección `[Install]`, así que `disable` no hace nada y
simplemente se borra con los demás. Eso es lo esperado, no un error.

```bash
systemctl --user stop    paynani-idle.service paynani-dispatch.service
systemctl --user disable paynani-idle.service paynani-dispatch.service
systemctl --user stop    paynani-logrotate.timer
systemctl --user disable paynani-logrotate.timer

rm -f ~/.config/systemd/user/paynani-*.service
rm -f ~/.config/systemd/user/paynani-*.timer
systemctl --user daemon-reload
```

Confirma que no quedó nada:

```bash
systemctl --user list-unit-files 'paynani-*'    # no debe salir ninguna fila
pgrep -af idle_listener.py                           # no debe salir nada
```

## 2. Quita las credenciales

Corre esto desde dentro del clon.

```bash
rm -f .env runtime.env install.manifest
rm -rf hermes
```

Si tus credenciales viven en un archivo compartido — un enlace simbólico que
apunta a otro lado — **no borres lo que apunta.** Otras cosas lo usan. Quita
únicamente las claves que agregó esta herramienta, si agregaste alguna.

## 3. Quita el estado y las bitácoras

```bash
rm -rf state/
```

Ahí están el registro de eventos, el de errores, el último UID visto y el
desplazamiento en bytes. Borrarlo es lo que hace que la siguiente instalación
empiece de verdad desde cero: sin el archivo de estado, un listener nuevo toma
como punto de partida lo que ya haya en el buzón en lugar de continuar, así que
nada se reprocesa.

## 4. Quita la cuenta de Himalaya, con cuidado

`~/.config/himalaya/config.toml` puede tener otras cuentas además de esta. **Quita
únicamente el bloque `[accounts.paynani]`**, no el archivo.

```bash
cp ~/.config/himalaya/config.toml ~/.config/himalaya/config.toml.bak.$(date +%F)
```

Después borra el bloque. Una forma reproducible, en lugar de editar a ojo; quita
desde el encabezado `[accounts.paynani]` hasta el siguiente `[` de primer nivel y
deja todo lo demás intacto:

```bash
python3 - <<'PY'
import pathlib, re
p = pathlib.Path.home() / ".config/himalaya/config.toml"
text = p.read_text()
out = re.sub(r'(?ms)^\[accounts\.paynani(?:\.[^\]]+)?\].*?(?=^\[(?!accounts\.paynani)|\Z)', '', text)
p.write_text(out)
print("removed" if out != text else "nothing matched: check the account name")
PY

himalaya account list       # todas las demás cuentas deben seguir ahí
```

Si era la única cuenta y le pusiste `default = true`, pásale el default a otra
cuenta o el siguiente `himalaya` a secas no tendrá a dónde ir.

## 5. Quita la regla permanente de las instrucciones del agente

La instalación agrega una regla a las instrucciones persistentes del agente
(normalmente su `AGENTS.md` o equivalente) que dice que el correo que venga de una
dirección en `roster.md` es trabajo que debe atender y responder.

**Quítala, y no trates este paso como opcional.** Esta regla concede algo en lugar
de restringirlo, así que una copia vieja no es inofensivamente redundante como sí
lo sería una advertencia olvidada. El `roster.md` al que se refiere ya no existe,
el listener que etiquetaba a los remitentes ya no existe, y lo que queda es una
instrucción de actuar sobre correo sin nada que defina de quién. Si el agente
tiene un buzón por otra vía, va a aplicar esta regla ahí.

**Reinstalar no es razón para dejarla.** La sección "Standing rules" de `AGENTS.md`
la vuelve a poner durante la instalación, contra el roster que sí va a existir
entonces.

## 6. Quita el repositorio

```bash
rm -rf "$REPO"   # el clon desde el que instalaste
```

**`roster.md` vive ahí dentro y no está en git**, así que esto lo borra y ningún
`git clone` lo trae de vuelta. Si armar esa lista costó trabajo, cópiala antes:

```bash
cp "$REPO/roster.md" ~/roster.md.kept
```

Haz esto **al final**. Todo lo de arriba usa rutas dentro del repositorio, y
borrarlo primero te deja trabajando de memoria.

---

## Lo que se deja en paz a propósito

**El linger.** `loginctl enable-linger` se activó durante la instalación, pero
puede que ahora otros servicios de usuario dependan de él. Apágalo solo si sabes
que nada más lo necesita:

```bash
loginctl show-user "$USER" -p Linger      # revisa primero
sudo loginctl disable-linger "$USER"      # solo si estás seguro
```

**Himalaya mismo**, si la instalación lo puso ahí. Es un cliente de correo de uso
general y puede servirte por su cuenta.

**El buzón y todo lo que hay en él.** Ve la nota del inicio.

---

## Confirma que ya no está

```bash
systemctl --user list-unit-files 'paynani-*'  # ninguna fila
pgrep -af "[i]dle_listener.py"                # nada; los corchetes evitan que
                                              # pgrep se encuentre a sí mismo
ls .env state hermes 2>&1                     # no such file or directory
himalaya account list                         # paynani ausente, las demás intactas
```

Cuatro resultados limpios y la máquina quedó como estaba.
