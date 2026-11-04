"""
Un emoji de reacción (PRD #685 F3): Webchat y WhatsApp aceptan cualquiera, pero uno solo.
Se compara sin el selector de variación (U+FE0F), así que «❤» y «❤️» son la misma (Iris, #685).
"""
from __future__ import annotations

_VS16 = "\ufe0f"
MAX_EMOJI = 16


def emoji_key(emoji: str) -> str:
    """El emoji sin el selector de variación (U+FE0F), para comparar «❤» con «❤️» (Iris, #685)."""
    return str(emoji or "").replace(_VS16, "")


def _clusters(emoji: str) -> int:
    """Cuántos emojis hay: un emoji sigue con el selector de variación, el tono de piel, el
    keycap, las etiquetas de una bandera, o con otro unido por ZWJ; una bandera son dos letras
    regionales."""
    count, prev, regional = 0, "", False
    for c in emoji:
        o = ord(c)
        joins = (c in (_VS16, "\u200d", "\u20e3") or 0x1F3FB <= o <= 0x1F3FF
                 or 0xE0020 <= o <= 0xE007F or prev == "\u200d")
        if 0x1F1E6 <= o <= 0x1F1FF:
            joins = joins or regional
            regional = not regional
        else:
            regional = False
        if not joins:
            count += 1
        prev = c
    return count


def valid_emoji(emoji: str) -> bool:
    """Un solo emoji: hasta 16 caracteres, sin letras, espacios ni signos ASCII (salvo las
    teclas #, * y 0-9 de un keycap). Webchat acepta cualquiera (FR-10)."""
    if not isinstance(emoji, str) or not emoji or len(emoji) > MAX_EMOJI:
        return False
    if not any(ord(c) >= 0x2000 and c not in (_VS16, "\u200d") for c in emoji):
        return False
    if not all((ord(c) >= 0x2000 and not c.isspace()) or c in "#*0123456789" for c in emoji):
        return False
    return _clusters(emoji) == 1
