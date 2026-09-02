<?php
declare(strict_types=1);

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
        return "El servidor contestó, pero su certificado de seguridad no está emitido para “{$host}”. "
             . "Normalmente eso significa que el nombre del servidor está un poco mal; muchos proveedores "
             . "quieren algo como imap.tuproveedor.com y no mail.tudominio.com. Pídele a tu proveedor el "
             . "nombre exacto que publica.";
    }
    if (str_contains($lower, 'getaddrinfo') || str_contains($lower, 'name or service not known')
        || str_contains($lower, 'no such host')) {
        return "“{$host}” no resuelve a ninguna máquina. Revisa cómo está escrito.";
    }
    if (str_contains($lower, 'connection refused')) {
        return "Se llega a “{$host}” pero rechazó la conexión en ese puerto. Lo más probable es que el puerto esté mal.";
    }
    if (str_contains($lower, 'timed out') || str_contains($lower, 'timeout')) {
        return "“{$host}” no contestó en " . PROBE_TIMEOUT . " segundos. O el nombre del servidor o el "
             . "puerto están mal, o hay un firewall estorbando.";
    }
    return $raw !== '' ? $raw : 'La conexión falló sin decir por qué.';
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
        $steps[] = step(false, 'El puerto 143 no sirve con esta herramienta.',
            'El listener abre IMAP sobre TLS de inmediato (IMAP4_SSL), y el puerto 143 empieza sin cifrar. '
          . 'Usa el 993, que es el que ofrece casi cualquier proveedor.');
        return ['ok' => false, 'steps' => $steps];
    }

    [$stream, $error] = open_stream('ssl', $host, $port);
    if ($stream === null) {
        $steps[] = step(false, "No se pudo abrir una conexión cifrada a {$host}:{$port}.", $error);
        return ['ok' => false, 'steps' => $steps];
    }
    $steps[] = step(true, "Conectado a {$host}:{$port} por TLS, y el certificado está correcto.");

    $greeting = read_line($stream);
    if (!str_starts_with($greeting, '* OK') && !str_starts_with($greeting, '* PREAUTH')) {
        $steps[] = step(false, 'Ese puerto contestó, pero no está hablando IMAP.',
            $greeting !== '' ? "Dijo: {$greeting}" : 'No dijo absolutamente nada.');
        fclose($stream);
        return ['ok' => false, 'steps' => $steps];
    }
    $steps[] = step(true, 'El servidor se identificó como un servidor IMAP.');

    fwrite($stream, "a1 LOGIN " . imap_quote($user) . ' ' . imap_quote($pass) . "\r\n");
    $lines  = imap_read_until($stream, 'a1');
    $result = end($lines) ?: '';

    if (!str_starts_with($result, 'a1 OK')) {
        $steps[] = step(false, 'El servidor rechazó esa dirección y contraseña.',
            'Muchos proveedores piden aquí una contraseña de aplicación en lugar de la que escribes en su sitio web. '
          . 'Si el tuyo ofrece verificación en dos pasos, casi seguro es el caso.');
        fwrite($stream, "a9 LOGOUT\r\n");
        fclose($stream);
        return ['ok' => false, 'steps' => $steps];
    }
    $steps[] = step(true, 'Sesión iniciada correctamente.');

    // IDLE is the whole design. Ask after logging in; plenty of servers only
    // advertise it to an authenticated session.
    fwrite($stream, "a2 CAPABILITY\r\n");
    $caps = strtoupper(implode(' ', imap_read_until($stream, 'a2')));
    if (str_contains($caps, 'IDLE')) {
        $steps[] = step(true, 'El servidor soporta IDLE, así que el correo nuevo llega en más o menos un segundo.');
    } else {
        $steps[] = step(false, 'Este servidor no ofrece IDLE.',
            'Sin eso no hay manera de enterarse del correo nuevo cuando llega, y esta herramienta no tiene '
          . 'nada a qué recurrir. Vale la pena preguntarle a tu proveedor antes de seguir.');
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
        $steps[] = step(false, "No se pudo llegar a {$host}:{$port}.", $error);
        return ['ok' => false, 'authenticated' => false, 'steps' => $steps];
    }

    $greeting = smtp_read_reply($stream);
    if (smtp_code($greeting) !== 220) {
        $steps[] = step(false, 'Ese puerto contestó, pero no está hablando SMTP.',
            trim($greeting) !== '' ? 'Dijo: ' . trim($greeting) : 'No dijo absolutamente nada.');
        fclose($stream);
        return ['ok' => false, 'authenticated' => false, 'steps' => $steps];
    }

    $ehlo = smtp_command($stream, 'EHLO localhost');
    if (smtp_code($ehlo) !== 250) {
        $steps[] = step(false, 'El servidor no quiso iniciar una sesión.', trim($ehlo));
        fclose($stream);
        return ['ok' => false, 'authenticated' => false, 'steps' => $steps];
    }

    if ($implicit) {
        $steps[] = step(true, "Conectado a {$host}:{$port} por TLS, y el certificado está correcto.");
    } else {
        if (!str_contains(strtoupper($ehlo), 'STARTTLS')) {
            $steps[] = step(false, 'Este servidor no cifra la conexión en ese puerto.',
                'Mandar una contraseña por un enlace sin cifrar no es algo que esta herramienta vaya a configurar. '
              . 'Prueba el puerto 465, o el 587 si tu proveedor soporta STARTTLS.');
            fclose($stream);
            return ['ok' => false, 'authenticated' => false, 'steps' => $steps];
        }
        $start = smtp_command($stream, 'STARTTLS');
        if (smtp_code($start) !== 220) {
            $steps[] = step(false, 'El servidor se negó a cambiar a una conexión cifrada.', trim($start));
            fclose($stream);
            return ['ok' => false, 'authenticated' => false, 'steps' => $steps];
        }
        [$crypto, $warnings] = collect_warnings(
            static fn () => stream_socket_enable_crypto($stream, true, STREAM_CRYPTO_METHOD_TLS_CLIENT)
        );
        if ($crypto !== true) {
            // Same trap as the implicit-TLS path: the certificate complaint is in
            // a warning, not in the return value.
            $steps[] = step(false, 'No se pudo establecer la conexión cifrada.',
                explain_connect_error($warnings, $host));
            fclose($stream);
            return ['ok' => false, 'authenticated' => false, 'steps' => $steps];
        }
        $steps[] = step(true, "Conectado a {$host}:{$port} y elevado a TLS; el certificado está correcto.");
        $ehlo = smtp_command($stream, 'EHLO localhost');
    }

    if (!str_contains(strtoupper($ehlo), 'AUTH')) {
        $steps[] = step(false, 'El servidor no ofrece manera de iniciar sesión en ese puerto.',
            'Normalmente eso significa que el puerto es para otra cosa. El 465 y el 587 son los dos que hay que probar.');
        smtp_command($stream, 'QUIT');
        fclose($stream);
        return ['ok' => false, 'authenticated' => false, 'steps' => $steps];
    }

    $auth = smtp_command($stream, 'AUTH LOGIN');
    if (smtp_code($auth) !== 334) {
        $steps[] = step(false, 'El servidor no aceptó esta forma de iniciar sesión.', trim($auth));
        smtp_command($stream, 'QUIT');
        fclose($stream);
        return ['ok' => false, 'authenticated' => false, 'steps' => $steps];
    }

    $sentUser = smtp_command($stream, base64_encode($user));
    if (smtp_code($sentUser) !== 334) {
        $steps[] = step(false, 'El servidor rechazó la dirección.', trim($sentUser));
        smtp_command($stream, 'QUIT');
        fclose($stream);
        return ['ok' => false, 'authenticated' => false, 'steps' => $steps];
    }

    $sentPass = smtp_command($stream, base64_encode($pass));
    if (smtp_code($sentPass) !== 235) {
        $steps[] = step(false, 'El servidor rechazó esa dirección y contraseña para enviar.',
            'If signing in for reading worked, some providers still want a separate app password for '
          . 'sending, or need SMTP switched on in your account settings.');
        smtp_command($stream, 'QUIT');
        fclose($stream);
        return ['ok' => false, 'authenticated' => false, 'steps' => $steps];
    }
    $steps[] = step(true, 'Sesión iniciada correctamente, así que el agente va a poder responder.');

    smtp_command($stream, 'QUIT');
    fclose($stream);
    return ['ok' => true, 'authenticated' => true, 'steps' => $steps];
}
