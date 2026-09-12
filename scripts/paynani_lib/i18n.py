"""
Language for the onboarding page. Port of webapp/lib/i18n.php.

The person filling this form is not always the person running the agent, and
is not always the person who chose the language the rest of the install
speaks. They are handing over a mailbox password, so they get to read what
they are agreeing to in their own language.

Like the PHP version's t()/th(), the current language is process-global state
rather than an object threaded through every call — validate.py and probe.py
call t()/th() directly, exactly as validate.php and probe.php do. This is safe
because the onboarding server (server.py) is deliberately single-threaded and
handles one request fully before starting the next, so "current language" for
the duration of one request is unambiguous. set_current() is called once at
the top of handling each request, mirroring how a fresh PHP process picks up
current_lang() from the session at the start of each request.
"""

from __future__ import annotations

import html

from .i18n_data import CATALOGUES

LANG_DEFAULT = "es-MX"

# Tag => the name that tag calls itself. Never translated; each is in its own
# language.
LANGUAGES = {
    "es-MX": "Español (MX)",
    "en-US": "English (US)",
    "es-ES": "Español (ES)",
    "fr-FR": "Français (FR)",
    "pt-BR": "Português (BR)",
}

_current_lang = LANG_DEFAULT


def lang_is_known(tag: str) -> bool:
    return tag in LANGUAGES


def set_current(lang: str) -> str:
    """Bind the language for the request now being handled. Returns the tag
    actually selected (LANG_DEFAULT when the argument is unknown)."""
    global _current_lang
    _current_lang = lang if lang_is_known(lang) else LANG_DEFAULT
    return _current_lang


def current_lang() -> str:
    return _current_lang


def t(key: str, **vars: object) -> str:
    """
    One string, with ``{placeholder}`` substitution.

    A key missing from the current catalogue falls back to es-MX rather than
    rendering blank, so a half-finished catalogue degrades to a mixed page
    instead of an empty one. A key missing from es-MX too returns the key
    itself — deliberately ugly, so it is obvious on the page rather than
    silently empty.
    """
    strings = CATALOGUES[_current_lang]
    fallback = CATALOGUES[LANG_DEFAULT]
    text = strings.get(key, fallback.get(key, key))
    for name, value in vars.items():
        text = text.replace("{" + name + "}", str(value))
    return text


def th(key: str, **vars: object) -> str:
    """The same string, for a template: values are HTML-escaped, the
    catalogue text itself is not (it may carry light markup)."""
    escaped = {name: html.escape(str(value), quote=True) for name, value in vars.items()}
    return t(key, **escaped)
