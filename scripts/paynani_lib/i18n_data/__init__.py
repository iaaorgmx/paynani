"""
One flat ``STRINGS`` dict per language, ported 1:1 from webapp/i18n/*.php.

Content, not structure, is the source of truth here: these are the same keys
and the same human-authored text as the PHP catalogues, generated once from
them (see the PR that added this file) rather than retyped by hand, so a
validation message or a probe error reads identically whichever setup path
produced it. Keep them in sync by hand from here on — issue #114's PRD chose
not to share a single data file between PHP and Python for this first phase,
to avoid a fourth path-resolution-style drift problem while webapp/ still
exists (see scripts/test_paths.sh's history for why that's worth avoiding).
"""

from . import es_MX, en_US, es_ES, fr_FR, pt_BR

CATALOGUES = {
    "es-MX": es_MX.STRINGS,
    "en-US": en_US.STRINGS,
    "es-ES": es_ES.STRINGS,
    "fr-FR": fr_FR.STRINGS,
    "pt-BR": pt_BR.STRINGS,
}
