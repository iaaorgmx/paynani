"""
One flat ``STRINGS`` dict per language, ported 1:1 from webapp/i18n/*.php.

Content, not structure, is the source of truth here: these were generated
once from the now-retired PHP catalogues (`webapp/i18n/*.php`, see
CHANGELOG.md) rather than retyped by hand, so a validation message or a probe
error read identically whichever setup path produced it at the time. Keep
them in sync by hand from here on — this is now the only catalogue.
"""

from . import es_MX, en_US, es_ES, fr_FR, pt_BR

CATALOGUES = {
    "es-MX": es_MX.STRINGS,
    "en-US": en_US.STRINGS,
    "es-ES": es_ES.STRINGS,
    "fr-FR": fr_FR.STRINGS,
    "pt-BR": pt_BR.STRINGS,
}
