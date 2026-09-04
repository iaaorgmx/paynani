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

require_once __DIR__ . '/paths.php';
require_once __DIR__ . '/i18n.php';

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
/**
 * Everything currently in the credentials file, as key => value.
 *
 * Quotes are stripped exactly one layer deep, which is what load_env() and
 * send.sh do when they read the same file back. Anything that is not a
 * KEY=value line is ignored here; render_env() is the half that preserves it.
 *
 * @return array<string, string>
 */
function read_env(): array
{
    $path = env_path();
    if (!is_file($path)) {
        return [];
    }
    $raw = @file_get_contents($path);
    if (!is_string($raw)) {
        return [];
    }

    $out = [];
    foreach (preg_split("/\r\n|\n|\r/", $raw) as $line) {
        if (preg_match('/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$/', $line, $m) !== 1) {
            continue;
        }
        $value = trim($m[2]);
        $len   = strlen($value);
        if ($len >= 2
            && (($value[0] === '"' && $value[$len - 1] === '"')
             || ($value[0] === "'" && $value[$len - 1] === "'"))) {
            $value = substr($value, 1, -1);
        }
        $out[$m[1]] = $value;
    }
    return $out;
}

function sanitise_value(string $value): string
{
    $value = str_replace(["\r", "\n"], '', $value);
    return trim($value);
}

/**
 * The file to write.
 *
 * **Only the seven keys this form owns are touched.** A real installation keeps
 * more than mail settings in here, tokens for other services among them, and
 * this page has no idea what any of it is. Rewriting the file from scratch would
 * delete all of it, which stayed harmless only while the form was something you
 * ran once at install time. It is not that any more: the fields arrive filled so
 * that a password can be changed later, and changing a password must not cost
 * somebody every other secret in the file.
 *
 * So an existing file is edited in place, line by line. Comments, blank lines,
 * key order and unknown keys all survive; a key the form owns but the file lacks
 * is appended. Only an absent or empty file gets the generated header.
 */
function render_env(array $values): string
{
    $path     = env_path();
    $existing = is_file($path) ? @file_get_contents($path) : false;

    if (!is_string($existing) || trim($existing) === '') {
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

    $lines = preg_split("/\r\n|\n|\r/", rtrim($existing, "\r\n"));
    $seen  = [];
    foreach ($lines as $i => $line) {
        if (preg_match('/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=/', $line, $m) !== 1) {
            continue;
        }
        if (!in_array($m[1], ENV_FIELDS, true)) {
            continue;
        }
        $lines[$i] = $m[1] . '=' . sanitise_value((string) ($values[$m[1]] ?? ''));
        $seen[$m[1]] = true;
    }
    foreach (ENV_FIELDS as $key) {
        if (!isset($seen[$key])) {
            $lines[] = $key . '=' . sanitise_value((string) ($values[$key] ?? ''));
        }
    }
    return implode("\n", $lines) . "\n";
}

/**
 * @return array{0: bool, 1: string} success, and a message either way
 */
function write_env(string $contents): array
{
    $path = env_path();
    $dir  = dirname($path);

    if (!is_dir($dir) && !@mkdir($dir, 0700, true) && !is_dir($dir)) {
        return [false, t('f.mkdir_failed', ['dir' => $dir])];
    }
    @chmod($dir, 0700);

    // Write beside the target and rename, so an interrupted write cannot leave a
    // half-file that the listener would read as a complete one. Create the temp
    // file at 0600 before anything goes into it, not after.
    $tmp = $path . '.tmp';
    $fh  = @fopen($tmp, 'w');
    if ($fh === false) {
        return [false, t('f.write_failed', ['dir' => $dir])];
    }
    @chmod($tmp, 0600);

    $written = fwrite($fh, $contents);
    fclose($fh);

    if ($written === false || $written !== strlen($contents)) {
        @unlink($tmp);
        return [false, t('f.incomplete')];
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
            return [false, t('f.symlink_failed', ['target' => $target])];
        }
        @chmod($target, 0600);
        @unlink($tmp);
        return [true, $target];
    }

    if (!@rename($tmp, $path)) {
        @unlink($tmp);
        return [false, t('f.rename_failed', ['path' => $path])];
    }
    @chmod($path, 0600);
    return [true, $path];
}
