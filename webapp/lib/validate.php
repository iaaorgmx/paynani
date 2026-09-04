<?php
declare(strict_types=1);

/**
 * Form validation.
 *
 * The checks here are not generic form hygiene. Each one is a mistake this
 * project has actually seen, and every one of them produces a file that looks
 * correct and a listener that fails somewhere far away from the cause.
 */

/**
 * @return array<string, string> field name => message, empty when it all passes
 */
function validate(array $in): array
{
    $errors = [];

    $account = trim((string) ($in['AGENT_EMAIL_ACCOUNT'] ?? ''));
    if ($account === '') {
        $errors['AGENT_EMAIL_ACCOUNT'] = 'El agente necesita una dirección de correo.';
    } elseif (filter_var($account, FILTER_VALIDATE_EMAIL) === false) {
        $errors['AGENT_EMAIL_ACCOUNT'] = 'Eso no parece una dirección de correo.';
    }

    if ((string) ($in['AGENT_EMAIL_PASSWORD'] ?? '') === '') {
        $errors['AGENT_EMAIL_PASSWORD'] = 'Sin la contraseña el agente no puede abrir el buzón.';
    }

    $name = (string) ($in['AGENT_EMAIL_FROM_NAME'] ?? '');
    if (str_contains($name, "\n") || str_contains($name, "\r")) {
        $errors['AGENT_EMAIL_FROM_NAME'] = 'El nombre visible tiene que caber en una sola línea.';
    }

    foreach ([
        'AGENT_EMAIL_INCOMING_SERVER_IMAP_HOST' => 'IMAP',
        'AGENT_EMAIL_OUTGOING_SERVER_SMTP_HOST' => 'SMTP',
    ] as $key => $label) {
        $host = trim((string) ($in[$key] ?? ''));
        if ($host === '') {
            $errors[$key] = "Falta el nombre del servidor {$label}.";
            continue;
        }
        // The trap this repo documents: a field named for a server holding a
        // port. Read literally it sends the listener somewhere that does not
        // exist, and the error arrives as a connection failure.
        if (ctype_digit($host)) {
            $errors[$key] = 'Eso es un número de puerto, no un nombre de servidor. El nombre se ve así: '
                          . 'imap.tuproveedor.example.';
            continue;
        }
        if (str_contains($host, '/') || str_contains($host, ' ') || str_contains($host, '@')) {
            $errors[$key] = 'Aquí va solo el nombre del servidor: sin https://, sin espacios, sin dirección.';
            continue;
        }
        if (preg_match('/^[A-Za-z0-9.\-]+$/', $host) !== 1) {
            $errors[$key] = 'Eso trae caracteres que un nombre de servidor no puede tener.';
        }
    }

    foreach ([
        'AGENT_EMAIL_INCOMING_SERVER_IMAP_PORT' => 'IMAP',
        'AGENT_EMAIL_OUTGOING_SERVER_SMTP_PORT' => 'SMTP',
    ] as $key => $label) {
        $port = trim((string) ($in[$key] ?? ''));
        if ($port === '') {
            $errors[$key] = "Falta el puerto {$label}.";
            continue;
        }
        if (!ctype_digit($port) || (int) $port < 1 || (int) $port > 65535) {
            $errors[$key] = 'Un puerto es un número entre 1 y 65535.';
        }
    }

    return $errors;
}
