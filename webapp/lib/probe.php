<?php
declare(strict_types=1);

require_once __DIR__ . '/i18n.php';

/**
 * Live checks against the mail server, before anything is written to disk.
 *
 * This is the reason the form is worth more than a text editor. The failures
 * this project sees are not typos in a key name; they are a hostname that
 * resolves but is not on the server's TLS certificate, a port that belongs to
 * the other protocol, or a password that works in a webmail login and not over
 * IMAP. Every one of those produces a file that looks perfect.
 *
 * Worse, a certificate mismatch reaches the listener as a network error, so it
 * retries forever with "connection lost" and nothing that names the cause. That
 * is a bad afternoon. Ten seconds here removes it.
 *
 * Nothing in this file ever puts the password into a message, a log, or a
 * returned value.
 */

const PROBE_TIMEOUT = 10;

/** One line of the report shown to the user. */
function step(bool $ok, string $text, string $detail = ''): array
{
    return ['ok' => $ok, 'text' => $text, 'detail' => $detail];
}

/**
 * Turn PHP's stream errors into something a non-technical reader can act on.
 * The certificate case is singled out because it is both the most common and
 * the least self-explanatory.
 */
function explain_connect_error(string $raw, string $host): string
{
    $lower = strtolower($raw);

    if (str_contains($lower, 'did not match') || str_contains($lower, 'certificate verify failed')
        || str_contains($lower, 'certificate_verify_failed')) {
        return t('p.cert_mismatch', ['host' => $host]);
    }
    if (str_contains($lower, 'getaddrinfo') || str_contains($lower, 'name or service not known')
        || str_contains($lower, 'no such host')) {
        return t('p.no_dns', ['host' => $host]);
    }
    if (str_contains($lower, 'connection refused')) {
        return t('p.refused', ['host' => $host]);
    }
    if (str_contains($lower, 'timed out') || str_contains($lower, 'timeout')) {
        return t('p.timed_out', ['host' => $host, 'seconds' => PROBE_TIMEOUT]);
    }
    return $raw !== '' ? $raw : t('p.failed_silent');
}

function tls_context(): mixed
{
    // Verification on, deliberately. Turning it off here would let the form
    // certify a configuration the listener will then refuse to use.
    return stream_context_create(['ssl' => [
        'verify_peer'       => true,
        'verify_peer_name'  => true,
        'SNI_enabled'       => true,
        'disable_compression' => true,
    ]]);
}

/**
 * Run something that may emit warnings, and hand back every one of them.
 *
 * A failed TLS connect emits several warnings and then sets $errstr to
 * "Unable to connect to ssl://host:port (Unknown error)". The useful sentence,
 * *Peer certificate CN did not match expected CN*, is in one of the earlier
 * warnings, so `error_get_last()` alone returns the least informative of the
 * set. Collecting all of them is the only way to see the actual cause.
 *
 * @return array{0: mixed, 1: string} the return value, and the warnings joined
 */
function collect_warnings(callable $fn): array
{
    $messages = [];
    set_error_handler(static function (int $errno, string $message) use (&$messages): bool {
        $messages[] = $message;
        return true;   // handled: keep it out of the page and the log
    });
    try {
        $result = $fn();
    } finally {
        restore_error_handler();
    }
    return [$result, implode(' ', $messages)];
}

/** @return array{0: ?resource, 1: string} the stream, or null and an explanation */
function open_stream(string $scheme, string $host, int $port): array
{
    $errno  = 0;
    $errstr = '';

    [$stream, $warnings] = collect_warnings(
        static function () use ($scheme, $host, $port, &$errno, &$errstr) {
            return stream_socket_client(
                "{$scheme}://{$host}:{$port}",
                $errno,
                $errstr,
                PROBE_TIMEOUT,
                STREAM_CLIENT_CONNECT,
                tls_context()
            );
        }
    );

    if ($stream === false) {
        return [null, explain_connect_error(trim($warnings . ' ' . $errstr), $host)];
    }

    stream_set_timeout($stream, PROBE_TIMEOUT);
    return [$stream, ''];
}

function read_line(mixed $stream): string
{
    $line = fgets($stream);
    return is_string($line) ? rtrim($line, "\r\n") : '';
}

/** IMAP responses run until the tagged line comes back. */
function imap_read_until(mixed $stream, string $tag): array
{
    $lines = [];
    $limit = 200;
    while ($limit-- > 0) {
        $line = read_line($stream);
        if ($line === '') {
            break;
        }
        $lines[] = $line;
        if (str_starts_with($line, $tag . ' ')) {
            break;
        }
    }
    return $lines;
}

/** IMAP quoted string: backslash and quote are the only two that matter. */
function imap_quote(string $value): string
{
    return '"' . str_replace(['\\', '"'], ['\\\\', '\\"'], $value) . '"';
}

/**
 * @return array{ok: bool, steps: array<int, array>}
 */
function probe_imap(string $host, int $port, string $user, string $pass): array
{
    $steps = [];

    if ($port === 143) {
        $steps[] = step(false, t('p.imap143'),
            t('p.imap143_detail'));
        return ['ok' => false, 'steps' => $steps];
    }

    [$stream, $error] = open_stream('ssl', $host, $port);
    if ($stream === null) {
        $steps[] = step(false, t('p.no_tls', ['host' => $host, 'port' => $port]), $error);
        return ['ok' => false, 'steps' => $steps];
    }
    $steps[] = step(true, t('p.tls_ok', ['host' => $host, 'port' => $port]));

    $greeting = read_line($stream);
    if (!str_starts_with($greeting, '* OK') && !str_starts_with($greeting, '* PREAUTH')) {
        $steps[] = step(false, t('p.not_imap'),
            $greeting !== '' ? t('p.said', ['greeting' => $greeting]) : t('p.said_nothing'));
        fclose($stream);
        return ['ok' => false, 'steps' => $steps];
    }
    $steps[] = step(true, t('p.is_imap'));

    fwrite($stream, "a1 LOGIN " . imap_quote($user) . ' ' . imap_quote($pass) . "\r\n");
    $lines  = imap_read_until($stream, 'a1');
    $result = end($lines) ?: '';

    if (!str_starts_with($result, 'a1 OK')) {
        $steps[] = step(false, t('p.auth_rejected'),
            t('p.auth_rejected_d'));
        fwrite($stream, "a9 LOGOUT\r\n");
        fclose($stream);
        return ['ok' => false, 'steps' => $steps];
    }
    $steps[] = step(true, t('p.signed_in'));

    // IDLE is the whole design. Ask after logging in; plenty of servers only
    // advertise it to an authenticated session.
    fwrite($stream, "a2 CAPABILITY\r\n");
    $caps = strtoupper(implode(' ', imap_read_until($stream, 'a2')));
    if (str_contains($caps, 'IDLE')) {
        $steps[] = step(true, t('p.idle_yes'));
    } else {
        $steps[] = step(false, t('p.idle_no'),
            t('p.idle_no_detail'));
        fwrite($stream, "a9 LOGOUT\r\n");
        fclose($stream);
        return ['ok' => false, 'steps' => $steps];
    }

    fwrite($stream, "a9 LOGOUT\r\n");
    fclose($stream);
    return ['ok' => true, 'steps' => $steps];
}

/** SMTP replies fold over several lines; the last one has a space after the code. */
function smtp_read_reply(mixed $stream): string
{
    $all   = '';
    $limit = 100;
    while ($limit-- > 0) {
        $line = read_line($stream);
        if ($line === '') {
            break;
        }
        $all .= $line . "\n";
        if (strlen($line) >= 4 && $line[3] === ' ') {
            break;
        }
    }
    return $all;
}

function smtp_code(string $reply): int
{
    return (int) substr(ltrim($reply), 0, 3);
}

function smtp_command(mixed $stream, string $command): string
{
    fwrite($stream, $command . "\r\n");
    return smtp_read_reply($stream);
}

/**
 * Try the encryption style the port suggests, and if the server turns out to
 * speak the other one, try that before giving up.
 *
 * 465 means TLS from the first byte and 587 means STARTTLS, by convention, but
 * it is only a convention. Hosts do offer implicit TLS on other ports, and a
 * mismatch here looks exactly like "that port is not speaking SMTP", which
 * would send someone off to check a setting that was right all along.
 *
 * @return array{ok: bool, steps: array<int, array>}
 */
function probe_smtp(string $host, int $port, string $user, string $pass): array
{
    $preferred = ($port !== 587 && $port !== 25 && $port !== 2525);

    $result = probe_smtp_mode($host, $port, $user, $pass, $preferred);
    if ($result['ok'] || $result['authenticated']) {
        return $result;   // it spoke SMTP; the other mode will not help
    }

    $fallback = probe_smtp_mode($host, $port, $user, $pass, !$preferred);
    return $fallback['ok'] ? $fallback : $result;
}

/**
 * @return array{ok: bool, authenticated: bool, steps: array<int, array>}
 */
function probe_smtp_mode(string $host, int $port, string $user, string $pass, bool $implicit): array
{
    $steps = [];

    [$stream, $error] = open_stream($implicit ? 'ssl' : 'tcp', $host, $port);
    if ($stream === null) {
        $steps[] = step(false, t('p.no_reach', ['host' => $host, 'port' => $port]), $error);
        return ['ok' => false, 'authenticated' => false, 'steps' => $steps];
    }

    $greeting = smtp_read_reply($stream);
    if (smtp_code($greeting) !== 220) {
        $steps[] = step(false, t('p.not_smtp'),
            trim($greeting) !== '' ? t('p.said', ['greeting' => trim($greeting)]) : t('p.said_nothing'));
        fclose($stream);
        return ['ok' => false, 'authenticated' => false, 'steps' => $steps];
    }

    $ehlo = smtp_command($stream, 'EHLO localhost');
    if (smtp_code($ehlo) !== 250) {
        $steps[] = step(false, t('p.no_session'), trim($ehlo));
        fclose($stream);
        return ['ok' => false, 'authenticated' => false, 'steps' => $steps];
    }

    if ($implicit) {
        $steps[] = step(true, t('p.tls_ok', ['host' => $host, 'port' => $port]));
    } else {
        if (!str_contains(strtoupper($ehlo), 'STARTTLS')) {
            $steps[] = step(false, t('p.no_encryption'),
                t('p.no_encryption_d'));
            fclose($stream);
            return ['ok' => false, 'authenticated' => false, 'steps' => $steps];
        }
        $start = smtp_command($stream, 'STARTTLS');
        if (smtp_code($start) !== 220) {
            $steps[] = step(false, t('p.starttls_refused'), trim($start));
            fclose($stream);
            return ['ok' => false, 'authenticated' => false, 'steps' => $steps];
        }
        [$crypto, $warnings] = collect_warnings(
            static fn () => stream_socket_enable_crypto($stream, true, STREAM_CRYPTO_METHOD_TLS_CLIENT)
        );
        if ($crypto !== true) {
            // Same trap as the implicit-TLS path: the certificate complaint is in
            // a warning, not in the return value.
            $steps[] = step(false, t('p.tls_failed'),
                explain_connect_error($warnings, $host));
            fclose($stream);
            return ['ok' => false, 'authenticated' => false, 'steps' => $steps];
        }
        $steps[] = step(true, t('p.tls_upgraded', ['host' => $host, 'port' => $port]));
        $ehlo = smtp_command($stream, 'EHLO localhost');
    }

    if (!str_contains(strtoupper($ehlo), 'AUTH')) {
        $steps[] = step(false, t('p.no_auth_offered'),
            t('p.no_auth_offered_d'));
        smtp_command($stream, 'QUIT');
        fclose($stream);
        return ['ok' => false, 'authenticated' => false, 'steps' => $steps];
    }

    $auth = smtp_command($stream, 'AUTH LOGIN');
    if (smtp_code($auth) !== 334) {
        $steps[] = step(false, t('p.auth_method_bad'), trim($auth));
        smtp_command($stream, 'QUIT');
        fclose($stream);
        return ['ok' => false, 'authenticated' => false, 'steps' => $steps];
    }

    $sentUser = smtp_command($stream, base64_encode($user));
    if (smtp_code($sentUser) !== 334) {
        $steps[] = step(false, t('p.address_rejected'), trim($sentUser));
        smtp_command($stream, 'QUIT');
        fclose($stream);
        return ['ok' => false, 'authenticated' => false, 'steps' => $steps];
    }

    $sentPass = smtp_command($stream, base64_encode($pass));
    if (smtp_code($sentPass) !== 235) {
        $steps[] = step(false, t('p.send_auth_bad'),
            t('p.send_auth_bad_d'));
        smtp_command($stream, 'QUIT');
        fclose($stream);
        return ['ok' => false, 'authenticated' => false, 'steps' => $steps];
    }
    $steps[] = step(true, t('p.signed_in_smtp'));

    smtp_command($stream, 'QUIT');
    fclose($stream);
    return ['ok' => true, 'authenticated' => true, 'steps' => $steps];
}
