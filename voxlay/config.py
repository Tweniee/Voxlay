import secrets
from pathlib import Path
from dataclasses import dataclass
from PySide6.QtCore import QSettings
from PySide6.QtGui import QFont, QFontDatabase


@dataclass(frozen=True)
class Theme:
    title: str
    bg_top: str
    bg_bottom: str
    text: str          # settled words
    accent: str        # live words still being revised, glow, live dot
    card: str          # caption card fill (rgba)
    families: tuple
    size: int          # points at 100% scale
    weight: QFont.Weight
    uppercase: bool = False
    glow: int = 90     # accent glow alpha behind the text


FONT_DIR = Path(__file__).parent / "fonts"   # bundled Google Fonts (OFL / Apache licensed)
N = QFont.Weight.Normal                      # display fonts ship one weight; faux bold looks smeared

THEMES = {
    "default": Theme("Comic", "#1A0B2E", "#3B0A45", "#FFFFFF", "#FFD23F",
                     "rgba(255,210,63,0.08)", ("Bangers", "Impact"), 120, N,
                     uppercase=True, glow=120),
    "neon": Theme("Neon", "#05030D", "#1A0633", "#FFE6FF", "#FF2BD6",
                  "rgba(255,43,214,0.05)", ("Monoton", "Futura"), 84, N,
                  uppercase=True, glow=230),
    "arcade": Theme("Arcade", "#030712", "#0B1E3A", "#E0F2FF", "#39FF14",
                    "rgba(57,255,20,0.05)", ("Press Start 2P", "Menlo"), 66, N,
                    uppercase=True, glow=170),
    "marker": Theme("Marker", "#141414", "#2E2A26", "#FFFFFF", "#FF5E3A",
                    "rgba(255,255,255,0.04)", ("Permanent Marker", "Marker Felt"), 100, N,
                    glow=90),
    "retro": Theme("Retro", "#2B0F0F", "#5A1E0E", "#FFE8C2", "#FF8A3D",
                   "rgba(255,138,61,0.08)", ("Shrikhand", "Cooper Black", "Georgia"), 96, N,
                   glow=110),
    "glitch": Theme("Glitch", "#050505", "#0C1A22", "#E8FFFF", "#00F0FF",
                    "rgba(0,240,255,0.05)", ("Rubik Glitch", "Impact"), 100, N,
                    uppercase=True, glow=150),
    "signage": Theme("Signage", "#0D0D0D", "#2A1B00", "#FFFFFF", "#FFB000",
                     "rgba(255,176,0,0.07)", ("Bungee", "Impact"), 88, N,
                     uppercase=True, glow=120),
}
THEME_ORDER = list(THEMES)

# Family name -> bundled file, so web clients can fetch the same font the host uses.
FONT_FILES = {
    "Bangers": "Bangers-Regular.ttf",
    "Bungee": "Bungee-Regular.ttf",
    "Monoton": "Monoton-Regular.ttf",
    "Permanent Marker": "PermanentMarker-Regular.ttf",
    "Press Start 2P": "PressStart2P-Regular.ttf",
    "Rubik Glitch": "RubikGlitch-Regular.ttf",
    "Shrikhand": "Shrikhand-Regular.ttf",
}
# Fallback families per bundled family, taken from the themes so there is one source of truth.
FALLBACKS = {t.families[0]: t.families[1:] for t in THEMES.values()}

DEFAULT_HOLD_MS = 2500
MAX_CHUNK_WORDS = 6
ROUTE_MODES = ("random", "loop")
HOST_MODES = ("screen", "mirror", "hidden")

_fonts_loaded = False


def load_fonts():
    global _fonts_loaded
    if _fonts_loaded:
        return
    _fonts_loaded = True
    for path in sorted(FONT_DIR.glob("*.ttf")):
        QFontDatabase.addApplicationFont(str(path))


def bundled_families():
    return [name for name, file in FONT_FILES.items() if (FONT_DIR / file).is_file()]


def font_file(family):
    file = FONT_FILES.get(family, "")
    return file if file and (FONT_DIR / file).is_file() else ""


def families_css(family):
    """CSS font-family stack: the family, its fallbacks, then a generic sans-serif."""
    names = (family, *FALLBACKS.get(family, ()))
    return ", ".join([f'"{n.replace(chr(34), "")}"' for n in names if n] + ["sans-serif"])


def _rgba(color, alpha):
    c = color.lstrip("#")
    return f"rgba({int(c[0:2], 16)},{int(c[2:4], 16)},{int(c[4:6], 16)},{alpha})"


def _clamp(value, low, high):
    return max(low, min(high, value))


def _settings():
    return QSettings("Voxlay", "Voxlay")


@dataclass(frozen=True)
class StyleConfig:
    theme: str            # preset key, or "custom" once any field was edited
    family: str
    text: str
    bg_top: str
    bg_bottom: str
    accent: str
    size: int             # points at 100% scale
    uppercase: bool
    glow: int             # accent glow alpha, 0-255
    cycle: bool
    hold_ms: int          # how long a chunk stays up on one device

    @classmethod
    def from_preset(cls, key, cycle=True, hold_ms=DEFAULT_HOLD_MS):
        key = key if key in THEMES else "default"
        t = THEMES[key]
        return cls(key, t.families[0], t.text, t.bg_top, t.bg_bottom, t.accent,
                   t.size, t.uppercase, t.glow, cycle, hold_ms)

    def with_preset(self, key):
        return StyleConfig.from_preset(key, self.cycle, self.hold_ms)

    def to_theme(self):
        """Resolved Theme the overlay draws with."""
        preset = THEMES.get(self.theme)
        return Theme(preset.title if preset else "Custom", self.bg_top, self.bg_bottom, self.text,
                     self.accent, preset.card if preset else _rgba(self.accent, 0.07),
                     (self.family, *FALLBACKS.get(self.family, ())), self.size, N,
                     self.uppercase, self.glow)

    def to_message(self):
        """The `style` frame web clients receive."""
        return {"type": "style", "font": {"family": self.family, "file": font_file(self.family)},
                "families_css": families_css(self.family), "text": self.text, "accent": self.accent,
                "bg_top": self.bg_top, "bg_bottom": self.bg_bottom, "size": self.size,
                "uppercase": self.uppercase, "glow": self.glow, "cycle": self.cycle,
                "hold_ms": self.hold_ms}

    @classmethod
    def load(cls):
        s = _settings()
        # The overlay used to store a bare `theme` / `cycle`; honour them until the new keys exist.
        key = s.value("style/theme", s.value("theme", "default", type=str), type=str)
        base = cls.from_preset(key, s.value("cycle", True, type=bool))
        return cls(
            base.theme,
            s.value("style/family", base.family, type=str),
            s.value("style/text", base.text, type=str),
            s.value("style/bg_top", base.bg_top, type=str),
            s.value("style/bg_bottom", base.bg_bottom, type=str),
            s.value("style/accent", base.accent, type=str),
            _clamp(s.value("style/size", base.size, type=int), 30, 300),
            s.value("style/uppercase", base.uppercase, type=bool),
            _clamp(s.value("style/glow", base.glow, type=int), 0, 255),
            s.value("style/cycle", base.cycle, type=bool),
            _clamp(s.value("style/hold_ms", base.hold_ms, type=int), 1000, 8000),
        )

    def save(self):
        s = _settings()
        for name, value in vars(self).items():
            s.setValue(f"style/{name}", value)
        s.sync()


@dataclass(frozen=True)
class RouteConfig:
    mode: str = "random"          # "random" | "loop"
    min_words: int = 1
    max_words: int = 3
    random_size: bool = True
    host_mode: str = "screen"     # "screen" | "mirror" | "hidden"
    port: int = 8765              # web page; WebSocket listens on port + 1
    token: str = ""               # empty = no token required
    ip: str = ""                  # advertised interface address; empty = auto-detect

    @classmethod
    def load(cls):
        s = _settings()
        mode = s.value("route/mode", "random", type=str)
        host_mode = s.value("route/host_mode", "screen", type=str)
        min_words = _clamp(s.value("route/min_words", 1, type=int), 1, MAX_CHUNK_WORDS)
        max_words = _clamp(s.value("route/max_words", 3, type=int), min_words, MAX_CHUNK_WORDS)
        # A random token by default; it is stored so devices can reconnect after a restart.
        token = s.value("route/token", secrets.token_urlsafe(6), type=str)
        return cls(
            mode if mode in ROUTE_MODES else "random",
            min_words, max_words,
            s.value("route/random_size", True, type=bool),
            host_mode if host_mode in HOST_MODES else "screen",
            _clamp(s.value("route/port", 8765, type=int), 1024, 65000),
            token,
            s.value("route/ip", "", type=str),
        )

    def save(self):
        s = _settings()
        for name, value in vars(self).items():
            s.setValue(f"route/{name}", value)
        s.sync()
