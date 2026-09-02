<?php
declare(strict_types=1);

/**
 * Writing the credentials file.
 *
 * This is the same file a power user writes by hand before running the install
 * prompt, and its absence is what tells the agent a mailbox has not been
 * configured yet. Both routes therefore end at one file, and "is this set up?"
 * stays a single question with a single answer.
 *
 * *Which* file is decided by the same rule as everywhere else, and normally not
 * decided here at all: scripts/setup_web.sh resolves it and passes it in through
 * PAYNANI_ENV, so the form and the tools it configures cannot disagree. The
 * fallback below repeats that rule for anyone serving this directory directly,
 * and the rule itself is written down once, in harness/paths.py.
 *
 * A new install keeps everything in one directory, and that directory is the
 * clone, so the credentials are `.env` at the top of it. An install that already
 * keeps its credentials somewhere else keeps them there: an existing file, or
 * the symlink older OpenClaw installs left behind, is written through rather
 * than replaced. Credentials are never copied to a second location to satisfy a
 * convention.
 */

require_once __DIR__ . '/guard.php';

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
const HARNESS_ROOTS         = ['.openclaw', '.hermes', '.claude'];
const HARNESS_ENV_RELATIVE  = 'workspace/.env';

const ENV_BASENAME = '.env';

/** The keys this form owns, in the order they are written. */
const ENV_FIELDS = [
    'AGENT_EMAIL_ACCOUNT',
    'AGENT_EMAIL_PASSWORD',
    'AGENT_EMAIL_FROM_NAME',
    'AGENT_EMAIL_INCOMING_SERVER_IMAP_HOST',
    'AGENT_EMAIL_INCOMING_SERVER_IMAP_PORT',
    'AGENT_EMAIL_OUTGOING_SERVER_SMTP_HOST',
    'AGENT_EMAIL_OUTGOING_SERVER_SMTP_PORT',
];

function env_path(): string
{
    $override = getenv('PAYNANI_ENV');
    if (is_string($override) && trim($override) !== '') {
        return trim($override);
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

function env_is_symlink(): bool
{
    clearstatcache(true, env_path());
    return is_link(env_path());
}

/**
 * Where a symlink actually points, as an absolute path.
 *
 * realpath() is not enough on its own: it returns false when the target does
 * not exist yet, and a link pointing at a file somebody has not created is
 * exactly the case where writing to the link path instead would silently
 * replace the link. readlink() answers even for a dangling one.
 */
function readlink_absolute(string $path): ?string
{
    $target = @readlink($path);
    if (!is_string($target) || $target === '') {
        return null;
    }
    if (!str_starts_with($target, '/')) {
        $target = dirname($path) . '/' . $target;
    }
    return $target;
}

/**
 * This page is for a host with no mailbox configured yet. If the file is
 * already there with mail settings in it, something is working and this form is
 * about to overwrite it; say so rather than quietly replacing a live account.
 */
function existing_config(): ?string
{
    $path = env_path();
    if (!is_file($path)) {
        return null;
    }
    $contents = @file_get_contents($path);
    if (!is_string($contents)) {
        return null;
    }
    return preg_match('/^\s*(AGENT_EMAIL|PAYNANI)_[A-Z_]*\s*=/m', $contents) === 1 ? $path : null;
}

/**
 * Values are written bare, exactly as load_env() and send.sh read them back:
 * they strip one layer of matching quotes and nothing else. So a value must not
 * carry a newline, and a leading or trailing space would be silently lost.
 */
function sanitise_value(string $value): string
{
    $value = str_replace(["\r", "\n"], '', $value);
    return trim($value);
}

function render_env(array $values): string
{
    $out  = "# Written by the paynani setup page.\n";
    $out .= '# ' . date('Y-m-d H:i:s T') . "\n";
    $out .= "#\n";
    $out .= "# Key names follow the schema in .env.example. Ports live in their own\n";
    $out .= "# keys: a port stored in a key named for a server is the one mistake\n";
    $out .= "# this file format refuses to survive.\n\n";

    foreach (ENV_FIELDS as $key) {
        $out .= $key . '=' . sanitise_value((string) ($values[$key] ?? '')) . "\n";
    }
    return $out;
}

/**
 * @return array{0: bool, 1: string} success, and a message either way
 */
function write_env(string $contents): array
{
    $path = env_path();
    $dir  = dirname($path);

    if (!is_dir($dir) && !@mkdir($dir, 0700, true) && !is_dir($dir)) {
        return [false, "No se pudo crear {$dir}."];
    }
    @chmod($dir, 0700);

    // Write beside the target and rename, so an interrupted write cannot leave a
    // half-file that the listener would read as a complete one. Create the temp
    // file at 0600 before anything goes into it, not after.
    $tmp = $path . '.tmp';
    $fh  = @fopen($tmp, 'w');
    if ($fh === false) {
        return [false, "No se pudo escribir en {$dir}."];
    }
    @chmod($tmp, 0600);

    $written = fwrite($fh, $contents);
    fclose($fh);

    if ($written === false || $written !== strlen($contents)) {
        @unlink($tmp);
        return [false, 'El archivo no se pudo escribir completo.'];
    }

    // Follow a symlink rather than replacing it: on a host where this path is
    // linked at the OpenClaw .env, renaming over it would break the link and
    // strand the listener on a file nobody updates.
    //
    // Clear the stat cache first. PHP remembers what it learned about a path,
    // and the built-in server is one long-lived process, so a page loaded
    // before the link existed leaves is_link() answering from a stale memory,
    // and the link gets replaced exactly as if this branch were not here.
    clearstatcache(true, $path);
    $target = is_link($path) ? (readlink_absolute($path) ?: $path) : $path;
    if ($target !== $path) {
        if (@file_put_contents($target, $contents) === false) {
            @unlink($tmp);
            return [false, "No se pudo escribir a través del enlace simbólico hacia {$target}."];
        }
        @chmod($target, 0600);
        @unlink($tmp);
        return [true, $target];
    }

    if (!@rename($tmp, $path)) {
        @unlink($tmp);
        return [false, "No se pudo dejar el archivo en su lugar en {$path}."];
    }
    @chmod($path, 0600);
    return [true, $path];
}
