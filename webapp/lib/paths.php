<?php
declare(strict_types=1);

/**
 * Where everything lives, for PHP.
 *
 * One rule, three implementations: harness/paths.py, scripts/envpath.sh and
 * this file. scripts/test_paths.sh asserts they answer identically, because
 * they have drifted before and the drift is invisible until it matters — the
 * form writes credentials to one path while the listener reads another, which
 * looks exactly like a mailbox that never gets mail.
 *
 * This file requires nothing. That is the point, not an accident: it is the
 * third of a cross-language contract, so it has to be comparable on its own,
 * and anything it pulled in could break underneath it. It carries resolution
 * and only resolution — reading and writing the credentials file is
 * envfile.php's job, and guarding the form is guard.php's.
 */

/**
 * Every harness keeps its agent's mail credentials in the workspace folder of
 * its own installation directory. One pattern rather than a list of special
 * cases: a new runtime is a new root here and nothing else. Keep in step with
 * HARNESS_ROOTS / HARNESS_ENV_RELATIVE in harness/paths.py and the same pair in
 * scripts/envpath.sh; scripts/test_paths.sh asserts all three agree.
 *
 * The OpenClaw root is listed because it is an instance of the rule rather than
 * an exception to it.
 */
const HARNESS_ROOTS         = ['.openclaw', '.hermes', '.claude', '.codex'];
const HARNESS_ENV_RELATIVE  = 'workspace/.env';

const ENV_BASENAME = '.env';

/**
 * The clone, which is also the install root.
 *
 * Found from this file, not from $PWD or $HOME, so serving this directory from
 * anywhere still resolves to the install it belongs to. The rule is written
 * down in harness/paths.py and the three languages are asserted to agree in
 * scripts/test_paths.sh; change all of them or none.
 */
function install_root(): string
{
    return dirname(__DIR__, 2);
}

/** The queue state, cursors and logs. */
function state_dir(): string
{
    $override = getenv('PAYNANI_STATE');
    if (is_string($override) && trim($override) !== '') {
        return rtrim(trim($override), '/');
    }
    return install_root() . '/state';
}

function home_dir(): string
{
    $home = getenv('HOME');
    if (is_string($home) && $home !== '') {
        return $home;
    }
    $info = posix_getpwuid(posix_geteuid());
    return is_array($info) && isset($info['dir']) ? (string) $info['dir'] : '/tmp';
}

/**
 * The credentials file the installer recorded in runtime.env, or null.
 *
 * Kept deliberately identical to recorded_env() in harness/paths.py and
 * paynani_recorded_env() in scripts/envpath.sh. Three implementations of one
 * rule; scripts/test_paths.sh cross-checks them because they have drifted before.
 */
function recorded_env(): ?string
{
    $file = install_root() . '/runtime.env';
    clearstatcache(true, $file);
    if (!is_file($file)) {
        return null;
    }
    $text = @file_get_contents($file);
    if ($text === false) {
        return null;
    }
    foreach (preg_split('/\r\n|\r|\n/', $text) as $line) {
        $line = trim($line);
        if (strpos($line, 'PAYNANI_ENV=') === 0) {
            $value = trim(substr($line, strlen('PAYNANI_ENV=')), " \t\"'");
            return $value !== '' ? $value : null;
        }
    }
    return null;
}

function env_path(): string
{
    $override = getenv('PAYNANI_ENV');
    if (is_string($override) && trim($override) !== '') {
        return trim($override);
    }

    $recorded = recorded_env();
    if ($recorded !== null) {
        return $recorded;
    }

    // Read the harness's file where it lies. Everything else still hangs off
    // the clone; that split is deliberate and is explained in harness/paths.py.
    // Two harness files means two agents share this host, either could be the
    // wrong mailbox, and a listener on the wrong mailbox is indistinguishable
    // from a quiet one — so neither is adopted.
    $harness = [];
    foreach (HARNESS_ROOTS as $root) {
        $candidate = rtrim(home_dir(), '/') . '/' . $root . '/' . HARNESS_ENV_RELATIVE;
        clearstatcache(true, $candidate);
        if (is_file($candidate) || is_link($candidate)) {
            $harness[] = $candidate;
        }
    }
    if (count($harness) === 1) {
        return $harness[0];
    }
    return install_root() . '/' . ENV_BASENAME;
}
