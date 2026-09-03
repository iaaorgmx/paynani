<?php
declare(strict_types=1);

/**
 * Language for the setup page.
 *
 * The person filling this form is not always the person who runs the agent, and
 * is not always the person who chose the language the rest of the install speaks.
 * They are handing over a mailbox password, so they get to read what they are
 * agreeing to in their own language.
 *
 * The catalogues live in webapp/i18n/<tag>.php and are plain arrays. A key that
 * a translation is missing falls back to es-MX rather than rendering blank, so a
 * half-finished catalogue degrades to a mixed page instead of an empty one.
 */

const LANG_DEFAULT = 'es-MX';

/** Tag => the name that tag calls itself. Never translated; each is in its own language. */
const LANGUAGES = [
    'es-MX' => 'Español (MX)',
    'en-US' => 'English (US)',
    'es-ES' => 'Español (ES)',
    'fr-FR' => 'Français (FR)',
    'pt-BR' => 'Português (BR)',
];

/** @var array<string, string>|null */
$GLOBALS['paynani_strings'] = null;
/** @var array<string, string>|null */
$GLOBALS['paynani_fallback'] = null;

function lang_is_known(string $tag): bool
{
    return array_key_exists($tag, LANGUAGES);
}

/**
 * The language this request renders in.
 *
 * A ?lang= or a posted lang wins and is remembered for the session, so the
 * choice survives the validation round-trips without riding in every URL.
 */
function current_lang(): string
{
    static $lang = null;
    if ($lang !== null) {
        return $lang;
    }

    $asked = trim((string) ($_POST['lang'] ?? $_GET['lang'] ?? ''));
    if ($asked !== '' && lang_is_known($asked)) {
        $_SESSION['lang'] = $asked;
        return $lang = $asked;
    }

    $held = (string) ($_SESSION['lang'] ?? '');
    if ($held !== '' && lang_is_known($held)) {
        return $lang = $held;
    }

    return $lang = LANG_DEFAULT;
}

function load_catalogue(string $tag): array
{
    $file = __DIR__ . '/../i18n/' . $tag . '.php';
    if (!is_file($file)) {
        return [];
    }
    $strings = require $file;
    return is_array($strings) ? $strings : [];
}

/**
 * One string, with {placeholders} replaced.
 *
 * Returns the key itself when nothing has it. That is deliberately ugly: a
 * missing string should be obvious on the page rather than silently empty.
 */
function t(string $key, array $vars = []): string
{
    if ($GLOBALS['paynani_strings'] === null) {
        $GLOBALS['paynani_strings']  = load_catalogue(current_lang());
        $GLOBALS['paynani_fallback'] = current_lang() === LANG_DEFAULT
            ? $GLOBALS['paynani_strings']
            : load_catalogue(LANG_DEFAULT);
    }

    $text = $GLOBALS['paynani_strings'][$key]
        ?? $GLOBALS['paynani_fallback'][$key]
        ?? $key;

    foreach ($vars as $name => $value) {
        $text = str_replace('{' . $name . '}', (string) $value, $text);
    }
    return $text;
}

/**
 * The same string, for a template.
 *
 * Catalogue text may carry light markup, so this is echoed raw; the values
 * substituted into it are escaped here, which is the half that comes from
 * outside. Use t() where the caller escapes the whole thing itself, which is
 * what the validator and the prober do.
 */
function th(string $key, array $vars = []): string
{
    $escaped = [];
    foreach ($vars as $name => $value) {
        $escaped[$name] = htmlspecialchars((string) $value, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
    }
    return t($key, $escaped);
}
