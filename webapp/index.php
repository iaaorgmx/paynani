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

require_once __DIR__ . '/lib/i18n.php';
require_once __DIR__ . '/lib/guard.php';
require_once __DIR__ . '/lib/validate.php';
require_once __DIR__ . '/lib/probe.php';
require_once __DIR__ . '/lib/envfile.php';
require_once __DIR__ . '/lib/brand.php';

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
// What is already on disk. The form is not only a first-time setup screen: the
// fields arrive filled so that somebody can come back and change the password,
// or fix a server name, without retyping the other six.
$stored         = read_env();
$storedPassword = (string) ($stored['AGENT_EMAIL_PASSWORD'] ?? '');

$values = $_SESSION['values'] ?? [];
foreach (ENV_FIELDS as $key) {
    $postedNow = $action !== '' && array_key_exists($key, $_POST);
    if ($postedNow) {
        $posted = trim((string) $_POST[$key]);
        // The password box comes back empty on every render, because its value is
        // never written into the HTML. An empty box therefore means "unchanged",
        // not "cleared"; otherwise testing and then saving would wipe it and the
        // form would demand it again for no reason the user can see.
        if ($key !== 'AGENT_EMAIL_PASSWORD' || $posted !== '') {
            $values[$key] = $posted;
        }
    }

    // The file fills anything this request did not carry. Testing for empty and
    // not merely for absent is the whole point: the language switch posts the
    // form, so a switch on an untouched page used to store seven empty strings
    // in the session, and those then shadowed the file on every later render.
    // The fields came back blank for the rest of the session and nothing said
    // why. A blank box that was not just typed means "whatever is on disk".
    //
    // Never the stored password: it goes nowhere near anything this page renders.
    if ($key !== 'AGENT_EMAIL_PASSWORD' && !$postedNow && ($values[$key] ?? '') === '') {
        $values[$key] = (string) ($stored[$key] ?? '');
    }
    if (($values[$key] ?? '') === '') {
        $values[$key] = $key === 'AGENT_EMAIL_PASSWORD' ? '' : (PORT_HINTS[$key] ?? '');
    }
    $values[$key] ??= '';
}

// The password actually used to sign in and to write the file. An empty box with
// a password already on disk means "leave it alone", which is what makes it
// possible to come here and change only the server name.
$effective = $values;
if ($effective['AGENT_EMAIL_PASSWORD'] === '') {
    $effective['AGENT_EMAIL_PASSWORD'] = $storedPassword;
}
$hasPassword = $effective['AGENT_EMAIL_PASSWORD'] !== '';

// A language change posts the whole form so that whatever has been typed
// survives the switch. It is not an attempt to save, so it neither validates
// nor touches the servers; it re-renders the same page in the other language.
if ($action !== '') {
    check_csrf();
    if ($action !== 'lang') {
        $errors = validate($effective);
    }
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
        $effective['AGENT_EMAIL_ACCOUNT'],
        $effective['AGENT_EMAIL_PASSWORD'],
    );
    $smtp = probe_smtp(
        $values['AGENT_EMAIL_OUTGOING_SERVER_SMTP_HOST'],
        (int) $values['AGENT_EMAIL_OUTGOING_SERVER_SMTP_PORT'],
        $effective['AGENT_EMAIL_ACCOUNT'],
        $effective['AGENT_EMAIL_PASSWORD'],
    );
    $report = ['imap' => $imap, 'smtp' => $smtp, 'ok' => $imap['ok'] && $smtp['ok']];

    if ($report['ok']) {
        [$ok, $where] = write_env(render_env($effective));
        if ($ok) {
            $saved = $where;
            // Nothing keeps the password in memory once it is on disk.
            unset($_SESSION['values']);
        } else {
            $notice = $where;
        }
    }
}

?>
<!doctype html>
<html lang="<?= e(current_lang()) ?>">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title><?= th('page.title') ?></title>
<link rel="stylesheet" href="/assets/app.css">
<script src="/assets/lang.js" defer></script>
</head>
<body>
<main>

<?php /*
  El SVG va en línea, no en un <img>: guard.php sirve `default-src 'none'` sin
  `img-src`, así que una imagen enlazada quedaría bloqueada. Ver lib/brand.php.
  El logotipo trae su propio <title>, y por eso no lleva texto al lado.
*/ ?>
<div class="marca"><?= brand_svg('paynani-horizontal.svg') ?></div>

<?php if ($saved !== null): ?>

  <div class="topbar">
    <h1><?= th('saved.h1') ?></h1>
    <?php /* Nothing left to preserve on this screen, so a plain GET form is enough. */ ?>
    <form method="get" action="/" class="langpick">
      <span class="combo">
        <select id="lang" name="lang" aria-label="<?= th('lang.label') ?>">
          <?php foreach (LANGUAGES as $tag => $name): ?>
            <option value="<?= e($tag) ?>"<?= $tag === current_lang() ? ' selected' : '' ?>><?= e($name) ?></option>
          <?php endforeach; ?>
        </select>
      </span>
      <button type="submit" id="langgo"><?= th('lang.apply') ?></button>
    </form>
  </div>

  <p class="lead"><?= th('saved.lead') ?></p>

  <div class="panel ok">
    <p><?= th('saved.where', ['path' => $saved]) ?></p>
  </div>

  <h2><?= th('saved.next_h2') ?></h2>
  <p><?= th('saved.next_p1') ?></p>
  <p><?= th('saved.next_p2') ?></p>

  <p class="quiet"><?= th('saved.forgot') ?></p>

<?php else: ?>

  <div class="topbar">
    <h1><?= th('page.h1') ?></h1>
    <?php /*
      The select and its button belong to the form below through the form=
      attribute, even though they sit up here. Switching language therefore
      posts whatever has already been typed, and the fields come back filled in
      the new language instead of empty.

      No onchange, and no script anywhere: guard.php serves a
      `default-src 'none'` policy with no script-src, so an inline handler would
      be blocked and the switch would silently do nothing. A page that collects
      a mail password is the wrong place to loosen that policy for the sake of
      saving one click, so the button is real and always visible.
    */ ?>
    <div class="langpick">
      <?php /* La etiqueta visible se quitó a propósito; aria-label la conserva
           para quien navega con lector de pantalla, que si no se encontraría un
           combo sin nombre. */ ?>
      <span class="combo">
        <select id="lang" name="lang" form="setup" aria-label="<?= th('lang.label') ?>">
          <?php foreach (LANGUAGES as $tag => $name): ?>
            <option value="<?= e($tag) ?>"<?= $tag === current_lang() ? ' selected' : '' ?>><?= e($name) ?></option>
          <?php endforeach; ?>
        </select>
      </span>
      <?php /*
        Este botón se queda en el HTML y assets/lang.js lo esconde al arrancar.
        No es un noscript: un script bloqueado por la CSP cuenta como scripting
        activo, así que un noscript no renderizaría nada y el combo quedaría
        muerto. Así, si el script no corre, lo que queda en pantalla es un botón
        que sí funciona.

        formnovalidate: sin él, el navegador se niega a enviar mientras la
        contraseña esté vacía, y cambiar de idioma se vuelve imposible hasta
        haber llenado el formulario. Este envío no guarda nada, así que no tiene
        nada que validar.
      */ ?>
      <button type="submit" name="action" value="lang" form="setup" formnovalidate id="langgo"><?= th('lang.apply') ?></button>
    </div>
  </div>

  <p class="lead"><?= th('page.lead') ?></p>

  <details class="help">
    <summary><?= th('help.summary') ?></summary>

    <h3><?= th('help.cpanel_h3') ?></h3>
    <p><?= th('help.cpanel_p') ?></p>
    <ol>
      <li><?= th('help.cpanel_li1') ?></li>
      <li><?= th('help.cpanel_li2') ?></li>
      <li><?= th('help.cpanel_li3') ?></li>
      <li><?= th('help.cpanel_li4') ?></li>
    </ol>
    <p><?= th('help.cpanel_after') ?></p>

    <h3><?= th('help.gmail_h3') ?></h3>
    <p><?= th('help.gmail_p1') ?></p>
    <p><?= th('help.gmail_p2') ?></p>
    <p><?= th('help.gmail_p3') ?></p>

    <h3><?= th('help.ms_h3') ?></h3>
    <p><?= th('help.ms_p1') ?></p>
    <p><?= th('help.ms_p2') ?></p>

    <h3><?= th('help.zoho_h3') ?></h3>
    <p><?= th('help.zoho_p') ?></p>

    <h3><?= th('help.fastmail_h3') ?></h3>
    <p><?= th('help.fastmail_p') ?></p>

    <h3><?= th('help.other_h3') ?></h3>
    <p><?= th('help.other_p1') ?></p>
    <p><?= th('help.other_p2') ?></p>
  </details>

  <?php if ($notice !== null): ?>
    <div class="panel warn"><p><?= e($notice) ?></p></div>
  <?php endif; ?>

  <form method="post" action="/" id="setup" autocomplete="off">
    <input type="hidden" name="csrf" value="<?= e(csrf_token()) ?>">

    <fieldset>
      <legend><?= th('form.account_legend') ?></legend>

      <label for="account"><?= th('form.account_label') ?></label>
      <input type="email" id="account" name="AGENT_EMAIL_ACCOUNT" required
             value="<?= e($values['AGENT_EMAIL_ACCOUNT']) ?>"
             placeholder="<?= th('form.account_ph') ?>">
      <?php if (isset($errors['AGENT_EMAIL_ACCOUNT'])): ?>
        <p class="err"><?= e($errors['AGENT_EMAIL_ACCOUNT']) ?></p>
      <?php endif; ?>
      <p class="hint"><?= th('form.account_hint') ?></p>

      <label for="password"><?= th('form.password_label') ?></label>
      <input type="password" id="password" name="AGENT_EMAIL_PASSWORD"
             <?= $hasPassword ? '' : 'required' ?>
             autocomplete="new-password"
             placeholder="<?= $hasPassword ? th('form.password_kept') : '' ?>">
      <?php if (isset($errors['AGENT_EMAIL_PASSWORD'])): ?>
        <p class="err"><?= e($errors['AGENT_EMAIL_PASSWORD']) ?></p>
      <?php endif; ?>
      <p class="hint"><?= th('form.password_hint') ?></p>

      <label for="fromname"><?= th('form.fromname_label') ?> <span class="opt"><?= th('form.optional') ?></span></label>
      <input type="text" id="fromname" name="AGENT_EMAIL_FROM_NAME"
             value="<?= e($values['AGENT_EMAIL_FROM_NAME']) ?>" placeholder="<?= th('form.fromname_ph') ?>">
      <?php if (isset($errors['AGENT_EMAIL_FROM_NAME'])): ?>
        <p class="err"><?= e($errors['AGENT_EMAIL_FROM_NAME']) ?></p>
      <?php endif; ?>
      <p class="hint"><?= th('form.fromname_hint') ?></p>
    </fieldset>

    <fieldset>
      <legend><?= th('form.imap_legend') ?></legend>
      <div class="row">
        <div class="grow">
          <label for="imaphost"><?= th('form.server') ?></label>
          <input type="text" id="imaphost" name="AGENT_EMAIL_INCOMING_SERVER_IMAP_HOST" required
                 value="<?= e($values['AGENT_EMAIL_INCOMING_SERVER_IMAP_HOST']) ?>"
                 placeholder="<?= th('form.imap_host_ph') ?>">
        </div>
        <div class="narrow">
          <label for="imapport"><?= th('form.port') ?></label>
          <input type="text" id="imapport" name="AGENT_EMAIL_INCOMING_SERVER_IMAP_PORT" required
                 inputmode="numeric" value="<?= e($values['AGENT_EMAIL_INCOMING_SERVER_IMAP_PORT']) ?>">
        </div>
      </div>
      <?php foreach (['AGENT_EMAIL_INCOMING_SERVER_IMAP_HOST', 'AGENT_EMAIL_INCOMING_SERVER_IMAP_PORT'] as $k): ?>
        <?php if (isset($errors[$k])): ?><p class="err"><?= e($errors[$k]) ?></p><?php endif; ?>
      <?php endforeach; ?>
      <p class="hint"><?= th('form.imap_hint') ?></p>
    </fieldset>

    <fieldset>
      <legend><?= th('form.smtp_legend') ?></legend>
      <div class="row">
        <div class="grow">
          <label for="smtphost"><?= th('form.server') ?></label>
          <input type="text" id="smtphost" name="AGENT_EMAIL_OUTGOING_SERVER_SMTP_HOST" required
                 value="<?= e($values['AGENT_EMAIL_OUTGOING_SERVER_SMTP_HOST']) ?>"
                 placeholder="<?= th('form.smtp_host_ph') ?>">
        </div>
        <div class="narrow">
          <label for="smtpport"><?= th('form.port') ?></label>
          <input type="text" id="smtpport" name="AGENT_EMAIL_OUTGOING_SERVER_SMTP_PORT" required
                 inputmode="numeric" value="<?= e($values['AGENT_EMAIL_OUTGOING_SERVER_SMTP_PORT']) ?>">
        </div>
      </div>
      <?php foreach (['AGENT_EMAIL_OUTGOING_SERVER_SMTP_HOST', 'AGENT_EMAIL_OUTGOING_SERVER_SMTP_PORT'] as $k): ?>
        <?php if (isset($errors[$k])): ?><p class="err"><?= e($errors[$k]) ?></p><?php endif; ?>
      <?php endforeach; ?>
      <p class="hint"><?= th('form.smtp_hint') ?></p>
    </fieldset>

    <?php if ($report !== null): ?>
      <div class="panel bad">
        <h2><?= th('report.h2') ?></h2>

        <h3><?= th('report.imap_h3') ?></h3>
        <ul class="steps">
          <?php foreach ($report['imap']['steps'] as $s): ?>
            <li class="<?= $s['ok'] ? 'good' : 'fail' ?>">
              <?= e($s['text']) ?>
              <?php if ($s['detail'] !== ''): ?><span class="detail"><?= e($s['detail']) ?></span><?php endif; ?>
            </li>
          <?php endforeach; ?>
        </ul>

        <h3><?= th('report.smtp_h3') ?></h3>
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
      <button type="submit" name="action" value="setup" class="primary"><?= th('form.submit') ?></button>
    </div>

    <p class="quiet"><?= th('form.footnote') ?></p>
  </form>

<?php endif; ?>

</main>
</body>
</html>
