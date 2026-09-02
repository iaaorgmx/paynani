<?php
declare(strict_types=1);

/**
 * paynani setup page.
 *
 * A form that collects the mailbox settings, checks them against the real
 * server, and writes the install's .env. It exists so that giving an agent a
 * mailbox does not require a terminal.
 *
 * Started by scripts/setup_web.sh, which binds it to 127.0.0.1 and prints a
 * one-time link. See webapp/README.md.
 */

require_once __DIR__ . '/lib/guard.php';
require_once __DIR__ . '/lib/validate.php';
require_once __DIR__ . '/lib/probe.php';
require_once __DIR__ . '/lib/envfile.php';

require_loopback();
start_session();
require_token();
send_security_headers();

const PORT_HINTS = [
    'AGENT_EMAIL_INCOMING_SERVER_IMAP_PORT' => '993',
    'AGENT_EMAIL_OUTGOING_SERVER_SMTP_PORT' => '465',
];

/** htmlspecialchars, but short enough to use everywhere it is needed. */
function e(?string $value): string
{
    return htmlspecialchars((string) $value, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
}


$action  = (string) ($_POST['action'] ?? '');
$errors      = [];
$report      = null;
$saved       = null;
$notice      = null;

// The password lives in the session between the test and the save, never in a
// value attribute. Re-rendering it into the HTML would put it in the page
// source, in the browser cache, and in any screenshot of this screen.
$values = $_SESSION['values'] ?? [];
foreach (ENV_FIELDS as $key) {
    if ($action !== '' && array_key_exists($key, $_POST)) {
        $posted = trim((string) $_POST[$key]);
        // The password box comes back empty on every render, because its value is
        // never written into the HTML. An empty box therefore means "unchanged",
        // not "cleared"; otherwise testing and then saving would wipe it and the
        // form would demand it again for no reason the user can see.
        if ($key !== 'AGENT_EMAIL_PASSWORD' || $posted !== '') {
            $values[$key] = $posted;
        }
    }
    $values[$key] ??= PORT_HINTS[$key] ?? '';
}

if ($action !== '') {
    check_csrf();
    $errors = validate($values);
    $_SESSION['values'] = $values;
}

// One action, in one order: check the settings against the real servers, and
// write the file only if both of them accepted the account. A configuration
// that does not authenticate is not a configuration; writing it would leave
// the agent with a file that looks finished and a mailbox it cannot open.
if ($action === 'setup' && $errors === []) {
    $imap = probe_imap(
        $values['AGENT_EMAIL_INCOMING_SERVER_IMAP_HOST'],
        (int) $values['AGENT_EMAIL_INCOMING_SERVER_IMAP_PORT'],
        $values['AGENT_EMAIL_ACCOUNT'],
        $values['AGENT_EMAIL_PASSWORD'],
    );
    $smtp = probe_smtp(
        $values['AGENT_EMAIL_OUTGOING_SERVER_SMTP_HOST'],
        (int) $values['AGENT_EMAIL_OUTGOING_SERVER_SMTP_PORT'],
        $values['AGENT_EMAIL_ACCOUNT'],
        $values['AGENT_EMAIL_PASSWORD'],
    );
    $report = ['imap' => $imap, 'smtp' => $smtp, 'ok' => $imap['ok'] && $smtp['ok']];

    if ($report['ok']) {
        [$ok, $where] = write_env(render_env($values));
        if ($ok) {
            $saved = $where;
            // Nothing keeps the password in memory once it is on disk.
            unset($_SESSION['values']);
        } else {
            $notice = $where;
        }
    }
}

$existing = existing_config();
?>
<!doctype html>
<html lang="es-MX">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>paynani: configuración del buzón</title>
<link rel="stylesheet" href="/assets/app.css">
</head>
<body>
<main>

<?php if ($saved !== null): ?>

  <h1>Listo</h1>
  <p class="lead">Tu servidor de correo aceptó la cuenta y la configuración quedó
     guardada. Ya puedes cerrar esta página.</p>

  <div class="panel ok">
    <p>Se guardó en <code><?= e($saved) ?></code>, y solo esta cuenta puede leerlo.</p>
  </div>

  <h2>Qué sigue</h2>
  <p>Avísale al agente que la configuración ya está. Él instala el resto y verifica
     que el correo llegue; esa parte es su trabajo, no el tuyo.</p>
  <p>Lo único que vale la pena hacer tú: mándale un correo al agente y pregúntale qué
     acaba de llegar. Si te contesta en un par de segundos, todo funciona.</p>

  <p class="quiet">Esta página ya olvidó la contraseña. Volver a abrirla no la muestra otra vez.</p>

<?php else: ?>

  <h1>Dale un buzón al agente</h1>
  <p class="lead">Siete datos de tu proveedor de correo. Todo se queda en esta
     computadora. Esta página no es accesible desde internet.</p>

  <?php if ($existing !== null): ?>
    <div class="panel warn">
      <p><strong>Aguas.</strong> Ya hay configuración de correo en
         <code><?= e($existing) ?></code>. Si terminas este formulario, la reemplaza.</p>
      <p>Si el agente ya está atendiendo correo, cierra esta página y confirma con quien
         lo configuró antes de seguir.</p>
    </div>
  <?php endif; ?>

  <details class="help">
    <summary>¿Dónde encuentro estos datos?</summary>

    <h3>Si tu correo vino con tu hosting web (cPanel)</h3>
    <p>Es el caso más común, y los datos ya están escritos ahí para ti.</p>
    <ol>
      <li>Entra a cPanel, normalmente <code>tudominio.com/cpanel</code>, o el enlace que te mandó tu proveedor.</li>
      <li>Abre <strong>Email Accounts</strong> (Cuentas de correo).</li>
      <li>Busca la dirección que va a usar el agente y haz clic en <strong>Connect Devices</strong>
          (en versiones viejas se llama <em>Set Up Mail Client</em>).</li>
      <li>Busca <strong>Mail Client Manual Settings</strong> y usa la columna
          <strong>Secure SSL/TLS Settings</strong>, no la que no lleva SSL.</li>
    </ol>
    <p>Copia <em>Incoming Server</em> y su puerto IMAP a la sección de lectura de abajo, y
       <em>Outgoing Server</em> con su puerto SMTP a la de envío. El usuario es la dirección
       de correo completa, y la contraseña es la que le pusiste a ese buzón cuando lo
       creaste. Si no la recuerdas, cPanel te deja cambiarla en esa misma página.</p>

    <h3>Gmail o Google Workspace</h3>
    <p>Los nombres de servidor siempre son los mismos: <code>imap.gmail.com</code> puerto
       <code>993</code> para leer, <code>smtp.gmail.com</code> puerto <code>465</code> para enviar.</p>
    <p>La contraseña es donde se atora la gente. Google no acepta aquí la normal. Necesitas
       una <strong>contraseña de aplicación</strong>, que requiere tener activada primero la
       verificación en dos pasos. Créala en <code>myaccount.google.com</code> → Seguridad →
       Contraseñas de aplicaciones, y pega el código de 16 caracteres que te dé.</p>
    <p>Revisa también que IMAP esté activado: Gmail → Configuración → Reenvío y correo POP/IMAP.</p>

    <h3>Outlook.com, Hotmail o Microsoft 365</h3>
    <p><code>outlook.office365.com</code> puerto <code>993</code> para leer,
       <code>smtp.office365.com</code> puerto <code>587</code> para enviar.</p>
    <p>Muchas cuentas empresariales de Microsoft ya bloquean por política los inicios de
       sesión como este. Si la verificación de abajo rechaza la contraseña aunque esté bien,
       normalmente es por eso, y tu administrador tiene que permitirlo.</p>

    <h3>Zoho</h3>
    <p><code>imappro.zoho.com</code> puerto <code>993</code>, <code>smtp.zoho.com</code>
       puerto <code>465</code>. Zoho también pide una contraseña de aplicación, no la normal.</p>

    <h3>Fastmail</h3>
    <p><code>imap.fastmail.com</code> puerto <code>993</code>,
       <code>smtp.fastmail.com</code> puerto <code>465</code>, con contraseña de aplicación.</p>

    <h3>Cualquier otro</h3>
    <p>Pregúntale a tu proveedor, o busca su nombre más <em>configuración IMAP y SMTP</em>.
       Buscas cuatro cosas: el nombre del servidor de entrada, el de salida, y un puerto
       para cada uno. Prefiere los puertos marcados como SSL o TLS.</p>
    <p>Una advertencia que vale la pena repetir: no adivines el nombre del servidor
       poniéndole <code>mail.</code> enfrente a tu dominio. Seguido funciona lo suficiente
       para parecer correcto y luego falla en el certificado de seguridad, que es horrible
       de diagnosticar después. La verificación de abajo lo detecta y te lo dice claro.</p>
  </details>

  <?php if ($notice !== null): ?>
    <div class="panel warn"><p><?= e($notice) ?></p></div>
  <?php endif; ?>

  <form method="post" action="/" autocomplete="off">
    <input type="hidden" name="csrf" value="<?= e(csrf_token()) ?>">

    <fieldset>
      <legend>La cuenta</legend>

      <label for="account">Dirección de correo</label>
      <input type="email" id="account" name="AGENT_EMAIL_ACCOUNT" required
             value="<?= e($values['AGENT_EMAIL_ACCOUNT']) ?>"
             placeholder="agente@tudominio.com">
      <?php if (isset($errors['AGENT_EMAIL_ACCOUNT'])): ?>
        <p class="err"><?= e($errors['AGENT_EMAIL_ACCOUNT']) ?></p>
      <?php endif; ?>
      <p class="hint">El buzón propio del agente, no el tuyo.</p>

      <label for="password">Contraseña</label>
      <input type="password" id="password" name="AGENT_EMAIL_PASSWORD"
             <?= $values['AGENT_EMAIL_PASSWORD'] === '' ? 'required' : '' ?>
             autocomplete="new-password"
             placeholder="<?= $values['AGENT_EMAIL_PASSWORD'] !== '' ? '••••••••  se conservó la anterior' : '' ?>">
      <?php if (isset($errors['AGENT_EMAIL_PASSWORD'])): ?>
        <p class="err"><?= e($errors['AGENT_EMAIL_PASSWORD']) ?></p>
      <?php endif; ?>
      <p class="hint">Si tu proveedor ofrece <em>contraseñas de aplicación</em>, usa una de
         esas. Es el dato que más seguido termina rechazado si no.</p>

      <label for="fromname">Nombre visible <span class="opt">opcional</span></label>
      <input type="text" id="fromname" name="AGENT_EMAIL_FROM_NAME"
             value="<?= e($values['AGENT_EMAIL_FROM_NAME']) ?>" placeholder="Atenea">
      <?php if (isset($errors['AGENT_EMAIL_FROM_NAME'])): ?>
        <p class="err"><?= e($errors['AGENT_EMAIL_FROM_NAME']) ?></p>
      <?php endif; ?>
      <p class="hint">El nombre que ve la gente cuando el agente les escribe.</p>
    </fieldset>

    <fieldset>
      <legend>Lectura de correo (IMAP)</legend>
      <div class="row">
        <div class="grow">
          <label for="imaphost">Servidor</label>
          <input type="text" id="imaphost" name="AGENT_EMAIL_INCOMING_SERVER_IMAP_HOST" required
                 value="<?= e($values['AGENT_EMAIL_INCOMING_SERVER_IMAP_HOST']) ?>"
                 placeholder="imap.tuproveedor.com">
        </div>
        <div class="narrow">
          <label for="imapport">Puerto</label>
          <input type="text" id="imapport" name="AGENT_EMAIL_INCOMING_SERVER_IMAP_PORT" required
                 inputmode="numeric" value="<?= e($values['AGENT_EMAIL_INCOMING_SERVER_IMAP_PORT']) ?>">
        </div>
      </div>
      <?php foreach (['AGENT_EMAIL_INCOMING_SERVER_IMAP_HOST', 'AGENT_EMAIL_INCOMING_SERVER_IMAP_PORT'] as $k): ?>
        <?php if (isset($errors[$k])): ?><p class="err"><?= e($errors[$k]) ?></p><?php endif; ?>
      <?php endforeach; ?>
      <p class="hint">Pídele a tu proveedor el nombre exacto del servidor. Adivinarlo
         poniendo <code>imap.</code> enfrente de tu dominio seguido produce un nombre que
         funciona en todo menos en el certificado de seguridad, y ese falla es difícil de
         diagnosticar después.</p>
    </fieldset>

    <fieldset>
      <legend>Envío de correo (SMTP)</legend>
      <div class="row">
        <div class="grow">
          <label for="smtphost">Servidor</label>
          <input type="text" id="smtphost" name="AGENT_EMAIL_OUTGOING_SERVER_SMTP_HOST" required
                 value="<?= e($values['AGENT_EMAIL_OUTGOING_SERVER_SMTP_HOST']) ?>"
                 placeholder="smtp.tuproveedor.com">
        </div>
        <div class="narrow">
          <label for="smtpport">Puerto</label>
          <input type="text" id="smtpport" name="AGENT_EMAIL_OUTGOING_SERVER_SMTP_PORT" required
                 inputmode="numeric" value="<?= e($values['AGENT_EMAIL_OUTGOING_SERVER_SMTP_PORT']) ?>">
        </div>
      </div>
      <?php foreach (['AGENT_EMAIL_OUTGOING_SERVER_SMTP_HOST', 'AGENT_EMAIL_OUTGOING_SERVER_SMTP_PORT'] as $k): ?>
        <?php if (isset($errors[$k])): ?><p class="err"><?= e($errors[$k]) ?></p><?php endif; ?>
      <?php endforeach; ?>
      <p class="hint">465 o 587. Los dos se verifican igual.</p>
    </fieldset>

    <?php if ($report !== null): ?>
      <div class="panel bad">
        <h2>Todavía no se guarda: algo aquí no está bien</h2>

        <h3>Lectura de correo</h3>
        <ul class="steps">
          <?php foreach ($report['imap']['steps'] as $s): ?>
            <li class="<?= $s['ok'] ? 'good' : 'fail' ?>">
              <?= e($s['text']) ?>
              <?php if ($s['detail'] !== ''): ?><span class="detail"><?= e($s['detail']) ?></span><?php endif; ?>
            </li>
          <?php endforeach; ?>
        </ul>

        <h3>Envío de correo</h3>
        <ul class="steps">
          <?php foreach ($report['smtp']['steps'] as $s): ?>
            <li class="<?= $s['ok'] ? 'good' : 'fail' ?>">
              <?= e($s['text']) ?>
              <?php if ($s['detail'] !== ''): ?><span class="detail"><?= e($s['detail']) ?></span><?php endif; ?>
            </li>
          <?php endforeach; ?>
        </ul>
      </div>
    <?php endif; ?>

    <div class="actions">
      <button type="submit" name="action" value="setup" class="primary">Verificar y guardar</button>
    </div>

    <p class="quiet">Esto entra a tu buzón y sale de inmediato; no lee, no envía ni cambia
       nada. La configuración se guarda solo si tu servidor de correo la acepta, así que no
       hay nada que deshacer si algo aquí está mal.</p>
  </form>

<?php endif; ?>

</main>
</body>
</html>
