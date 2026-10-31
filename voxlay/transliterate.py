import re
from indic_transliteration import sanscript
from indic_transliteration.sanscript import transliterate

DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]+")

def to_hinglish(text: str) -> str:
    """Romanize Devanagari spans while preserving existing English text."""
    def convert(match):
        try:
            return transliterate(match.group(0), sanscript.DEVANAGARI, sanscript.ITRANS)
        except Exception:
            return match.group(0)
    return DEVANAGARI_RE.sub(convert, text)
