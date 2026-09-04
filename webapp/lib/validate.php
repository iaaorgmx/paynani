<?php
declare(strict_types=1);

require_once __DIR__ . '/i18n.php';

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
        $errors['AGENT_EMAIL_ACCOUNT'] = t('v.account_missing');
    } elseif (filter_var($account, FILTER_VALIDATE_EMAIL) === false) {
        $errors['AGENT_EMAIL_ACCOUNT'] = t('v.account_bad');
    }

    if ((string) ($in['AGENT_EMAIL_PASSWORD'] ?? '') === '') {
        $errors['AGENT_EMAIL_PASSWORD'] = t('v.password_missing');
    }

    $name = (string) ($in['AGENT_EMAIL_FROM_NAME'] ?? '');
    if (str_contains($name, "\n") || str_contains($name, "\r")) {
        $errors['AGENT_EMAIL_FROM_NAME'] = t('v.fromname_oneline');
    }

    foreach ([
        'AGENT_EMAIL_INCOMING_SERVER_IMAP_HOST' => 'IMAP',
        'AGENT_EMAIL_OUTGOING_SERVER_SMTP_HOST' => 'SMTP',
    ] as $key => $label) {
        $host = trim((string) ($in[$key] ?? ''));
        if ($host === '') {
            $errors[$key] = t('v.host_missing', ['proto' => $label]);
            continue;
        }
        // The trap this repo documents: a field named for a server holding a
        // port. Read literally it sends the listener somewhere that does not
        // exist, and the error arrives as a connection failure.
        if (ctype_digit($host)) {
            $errors[$key] = t('v.host_is_port');
            continue;
        }
        if (str_contains($host, '/') || str_contains($host, ' ') || str_contains($host, '@')) {
            $errors[$key] = t('v.host_has_junk');
            continue;
        }
        if (preg_match('/^[A-Za-z0-9.\-]+$/', $host) !== 1) {
            $errors[$key] = t('v.host_bad_chars');
        }
    }

    foreach ([
        'AGENT_EMAIL_INCOMING_SERVER_IMAP_PORT' => 'IMAP',
        'AGENT_EMAIL_OUTGOING_SERVER_SMTP_PORT' => 'SMTP',
    ] as $key => $label) {
        $port = trim((string) ($in[$key] ?? ''));
        if ($port === '') {
            $errors[$key] = t('v.port_missing', ['proto' => $label]);
            continue;
        }
        if (!ctype_digit($port) || (int) $port < 1 || (int) $port > 65535) {
            $errors[$key] = t('v.port_range');
        }
    }

    return $errors;
}
