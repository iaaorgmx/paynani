<?php
declare(strict_types=1);

/**
 * The mark, inlined into the page.
 *
 * brand/ is the single source of truth for the logo and it lives at the top of
 * the clone, outside this docroot, so the page cannot link to it. It does not
 * want to: guard.php serves `default-src 'none'` with no `img-src`, so an
 * <img> would be blocked, and a page that collects a mail password is the wrong
 * place to widen a policy for the sake of a picture. Inline markup is not a
 * fetched resource, so it needs no directive at all.
 *
 * Inlining also buys the theme. The files carry their colours as presentation
 * attributes, which is what makes them right when opened on their own; a
 * stylesheet outranks a presentation attribute, so app.css repaints .voluta and
 * .logotipo per theme without a second copy of the artwork existing anywhere.
 */

require_once __DIR__ . '/paths.php';

/**
 * The files this page may inline, by their own names. A list rather than a
 * check: the argument never comes from a request today, and an allowlist means
 * it still cannot name a path if that ever changes.
 */
const BRAND_FILES = [
    'paynani-horizontal.svg',
    'paynani-vertical.svg',
    'voluta.svg',
    'voluta-reducida.svg',
];

/**
 * The SVG source, ready to drop into the markup, or an empty string.
 *
 * Empty rather than an error: a missing logo is a page without a logo, and this
 * form has one job that has nothing to do with the logo.
 */
function brand_svg(string $name): string
{
    if (!in_array($name, BRAND_FILES, true)) {
        return '';
    }
    $file = install_root() . '/brand/' . $name;
    if (!is_file($file)) {
        return '';
    }
    $svg = @file_get_contents($file);
    return $svg === false ? '' : trim($svg);
}
