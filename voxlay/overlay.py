import html
import math
from pathlib import Path
from dataclasses import dataclass
from PySide6.QtCore import Qt, QTimer, QVariantAnimation, QEasingCurve, QSettings, QPointF, Signal
from PySide6.QtWidgets import (QWidget, QLabel, QFrame, QVBoxLayout, QHBoxLayout,
                               QGraphicsDropShadowEffect)
from PySide6.QtGui import (QFont, QColor, QPainter, QLinearGradient, QRadialGradient,
                           QKeySequence, QShortcut, QTextDocument, QFontDatabase)


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
CARD_MARGIN_X, CARD_MARGIN_Y = 64, 44
MAX_WORDS = 3            # never show more than this many words at once
MAX_TEXT_HEIGHT = 0.66   # share of window height the caption text may use
COLOR_EVERY_MS = 2000    # palette rotation period
COLOR_FADE_MS = 700      # blend time between palettes
HUE_STEP = 137.5         # golden angle: consecutive palettes never look alike
HINTS = "+ / −  size   ·   T  theme   ·   R  colour cycle   ·   F  fullscreen   ·   C  clear   ·   H  hide hints   ·   Esc  quit"


def _hsl(hue, sat, light):
    return QColor.fromHslF((hue % 360) / 360, sat, light)


def _luminance(color):
    def channel(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * channel(color.redF()) + 0.7152 * channel(color.greenF()) + 0.0722 * channel(color.blueF())


def _contrast(a, b):
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def rotating_palette(hue):
    """Dark background on `hue`; live words on the complementary hue, lightened until readable."""
    bg_bottom = _hsl(hue + 40, 0.75, 0.24)
    light = 0.62
    accent = _hsl(hue + 180, 1.00, light)
    # Blue and violet are dark at any saturation; lift them until they clear 4.5:1 on the background.
    while _contrast(accent, bg_bottom) < 4.5 and light < 0.86:
        light += 0.02
        accent = _hsl(hue + 180, 1.00, light)
    return {
        "bg_top": _hsl(hue, 0.70, 0.11),
        "bg_bottom": bg_bottom,
        # Near-neutral settled words, so the saturated accent alone marks the live words.
        "text": _hsl(hue + 180, 0.25, 0.94),
        "accent": accent,
    }


def _load_fonts():
    for path in sorted(FONT_DIR.glob("*.ttf")):
        QFontDatabase.addApplicationFont(str(path))


class LiveDot(QWidget):
    """Pulsing dot: bright and breathing while words are being recognised, dim when idle."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(18, 18)
        self._color = QColor("#7CC4FF")
        self._active = False
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

    def set_color(self, color):
        self._color = QColor(color)
        self.update()

    def set_active(self, active):
        if active == self._active:
            return
        self._active = active
        if active:
            self._timer.start(40)
        else:
            self._timer.stop()
        self.update()

    def _tick(self):
        self._phase = (self._phase + 0.18) % (2 * math.pi)
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        center = QPointF(self.width() / 2, self.height() / 2)
        if self._active:
            pulse = (math.sin(self._phase) + 1) / 2
            halo = QColor(self._color)
            halo.setAlpha(int(40 + 60 * pulse))
            p.setBrush(halo)
            p.drawEllipse(center, 6 + 3 * pulse, 6 + 3 * pulse)
            p.setBrush(self._color)
        else:
            p.setBrush(QColor(255, 255, 255, 70))
        p.drawEllipse(center, 4.5, 4.5)


class CaptionOverlay(QWidget):
    clear_requested = Signal()
    def __init__(self):
        super().__init__()
        _load_fonts()
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self._settings = QSettings("Voxlay", "Voxlay")
        self._scale = min(2.0, max(0.4, float(self._settings.value("scale", 1.0, type=float))))
        self._wheel = 0
        self._cycle = self._settings.value("cycle", True, type=bool)
        self._hue = 270.0
        self._hue_anim = QVariantAnimation(self)
        self._hue_anim.setDuration(COLOR_FADE_MS)
        self._hue_anim.setEasingCurve(QEasingCurve.InOutSine)
        self._hue_anim.valueChanged.connect(self._set_hue)
        self._color_timer = QTimer(self)
        self._color_timer.timeout.connect(self._next_palette)
        saved = self._settings.value("theme", "default", type=str)
        self._theme = saved if saved in THEMES else "default"
        self._committed = ""
        self._partial = ""
        self._alpha = 1.0

        self._toast_timer = QTimer(self)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.timeout.connect(lambda: self.toast.setText(""))

        self.toast = QLabel("")
        self.toast.setObjectName("toast")
        self.toast.setAlignment(Qt.AlignCenter)

        self.placeholder = QLabel("Start speaking…")
        self.placeholder.setObjectName("placeholder")
        self.placeholder.setAlignment(Qt.AlignCenter)

        self.card = QFrame()
        self.card.setObjectName("card")
        self.label = QLabel("")
        self.label.setObjectName("caption")
        self.label.setTextFormat(Qt.RichText)
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setWordWrap(True)
        self.glow = QGraphicsDropShadowEffect(self.label)
        self.glow.setOffset(0, 0)
        self.glow.setBlurRadius(42)
        self.label.setGraphicsEffect(self.glow)
        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(CARD_MARGIN_X, CARD_MARGIN_Y, CARD_MARGIN_X, CARD_MARGIN_Y)
        card_layout.addWidget(self.label)
        self.card.hide()

        # Fade animates text alpha: Qt cannot nest an opacity effect over the glow effect.
        self.fade = QVariantAnimation(self)
        self.fade.setDuration(260)
        self.fade.setStartValue(0.0)
        self.fade.setEndValue(1.0)
        self.fade.setEasingCurve(QEasingCurve.OutCubic)
        self.fade.valueChanged.connect(self._set_alpha)

        self.dot = LiveDot()
        self.status = QLabel("Starting Voxlay…")
        self.status.setObjectName("status")
        self.hints = QLabel(HINTS)
        self.hints.setObjectName("hints")
        bar = QHBoxLayout()
        bar.setContentsMargins(28, 0, 28, 18)
        bar.setSpacing(10)
        bar.addWidget(self.dot)
        bar.addWidget(self.status)
        bar.addStretch(1)
        bar.addWidget(self.hints)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 24, 0, 0)
        layout.addWidget(self.toast)
        layout.addStretch(1)
        layout.addWidget(self.placeholder)
        layout.addWidget(self.card, 0, Qt.AlignHCenter)
        layout.addStretch(1)
        layout.addLayout(bar)

        for keys, action in (
            (("Esc",), self.close),
            (("+", "=", "Shift++", "Shift+=", "Ctrl++", "Ctrl+="), lambda: self.change_scale(0.1)),
            (("-", "Ctrl+-"), lambda: self.change_scale(-0.1)),
            (("0",), lambda: self.change_scale(None)),
            (("T",), self.next_theme),
            (("F",), self.toggle_fullscreen),
            (("C",), self._clear_pressed),
            (("H",), lambda: self.hints.setVisible(not self.hints.isVisible())),
            (("R",), self.toggle_cycle),
        ):
            for key in keys:
                QShortcut(QKeySequence(key), self, activated=action)

        self.set_theme(self._theme, announce=False)
        if self._cycle:
            self._color_timer.start(COLOR_EVERY_MS)

    # ---- appearance -------------------------------------------------------

    def _font(self, theme):
        font = QFont()
        font.setFamilies(list(theme.families))
        font.setPointSizeF(theme.size * self._scale)
        font.setWeight(theme.weight)
        font.setCapitalization(QFont.AllUppercase if theme.uppercase else QFont.MixedCase)
        font.setLetterSpacing(QFont.PercentageSpacing, 102 if theme.uppercase else 100)
        return font

    def _apply_fonts(self, t):
        self.label.setFont(self._font(t))
        placeholder_font = self._font(t)
        placeholder_font.setPointSizeF(t.size * self._scale * 0.45)
        self.placeholder.setFont(placeholder_font)

    def set_theme(self, theme, announce=True):
        self._theme = theme if theme in THEMES else "default"
        self._settings.setValue("theme", self._theme)
        t = THEMES[self._theme]
        self._apply_fonts(t)
        # A neutral card sits well on every rotating background; theme tint only when cycling is off.
        card = "rgba(255,255,255,0.07)" if self._cycle else t.card
        self.setStyleSheet(f"""
            QFrame#card {{
                background: {card};
                border: 1px solid rgba(255,255,255,0.10);
                border-radius: 36px;
            }}
            QLabel#caption {{ background: transparent; }}
            QLabel#placeholder {{ color: rgba(255,255,255,0.28); background: transparent; }}
            QLabel#status {{ color: rgba(255,255,255,0.65); font-size: 13px; font-weight: 600;
                             letter-spacing: 1px; background: transparent; }}
            QLabel#hints {{ color: rgba(255,255,255,0.32); font-size: 12px; background: transparent; }}
            QLabel#toast {{ color: rgba(255,255,255,0.85); font-size: 15px; font-weight: 700;
                            letter-spacing: 2px; background: transparent; }}
        """)
        self._apply_colors()
        if announce:
            self._show_toast(f"THEME · {t.title.upper()}")

    # ---- colour rotation --------------------------------------------------

    def _colors(self):
        if self._cycle:
            return rotating_palette(self._hue)
        t = THEMES[self._theme]
        return {"bg_top": QColor(t.bg_top), "bg_bottom": QColor(t.bg_bottom),
                "text": QColor(t.text), "accent": QColor(t.accent)}

    def _apply_colors(self):
        colors = self._colors()
        glow = QColor(colors["accent"])
        # A heavy halo in an arbitrary rotating hue muddies the letter edges; cap it while cycling.
        glow.setAlpha(min(THEMES[self._theme].glow, 120) if self._cycle else THEMES[self._theme].glow)
        self.glow.setColor(glow)
        self.dot.set_color(colors["accent"])
        self._render()
        self.update()

    def _set_hue(self, value):
        self._hue = float(value) % 360
        self._apply_colors()

    def _next_palette(self):
        self._hue_anim.stop()
        self._hue_anim.setStartValue(self._hue)
        self._hue_anim.setEndValue(self._hue + HUE_STEP)
        self._hue_anim.start()

    def toggle_cycle(self):
        self._cycle = not self._cycle
        self._settings.setValue("cycle", self._cycle)
        if self._cycle:
            self._color_timer.start(COLOR_EVERY_MS)
        else:
            self._color_timer.stop()
            self._hue_anim.stop()
        self.set_theme(self._theme, announce=False)
        self._show_toast("COLOUR CYCLE · ON" if self._cycle else "COLOUR CYCLE · OFF")

    def next_theme(self):
        index = (THEME_ORDER.index(self._theme) + 1) % len(THEME_ORDER)
        self.set_theme(THEME_ORDER[index])

    def change_scale(self, delta):
        scale = 1.0 if delta is None else min(2.0, max(0.4, round(self._scale + delta, 2)))
        if scale != self._scale:
            self._scale = scale
            self._settings.setValue("scale", self._scale)
            self._apply_fonts(THEMES[self._theme])
            self._render()
        self._show_toast(f"SIZE · {round(self._scale * 100)}%")

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
            self.resize(1100, 640)
        else:
            self.showFullScreen()

    def _show_toast(self, text):
        self.toast.setText(text)
        self._toast_timer.start(1400)

    def paintEvent(self, _event):
        colors = self._colors()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        base = QLinearGradient(0, 0, self.width(), self.height())
        base.setColorAt(0, colors["bg_top"])
        base.setColorAt(1, colors["bg_bottom"])
        p.fillRect(self.rect(), base)
        # Soft accent light behind the caption area.
        spot = QRadialGradient(QPointF(self.width() / 2, self.height() * 0.48),
                               max(self.width(), self.height()) * 0.55)
        light = QColor(colors["accent"])
        light.setAlpha(34)
        spot.setColorAt(0, light)
        spot.setColorAt(1, QColor(0, 0, 0, 0))
        p.fillRect(self.rect(), spot)

    # ---- interaction ------------------------------------------------------

    def wheelEvent(self, event):
        # Trackpads send many tiny deltas; act once per full wheel notch (120).
        self._wheel += event.angleDelta().y()
        while abs(self._wheel) >= 120:
            step = 1 if self._wheel > 0 else -1
            self._wheel -= 120 * step
            self.change_scale(0.05 * step)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.toggle_fullscreen()

    def mousePressEvent(self, event):
        if event.button() == Qt.RightButton:
            self.next_theme()

    def showEvent(self, event):
        super().showEvent(event)
        if self._cycle:
            self._color_timer.start(COLOR_EVERY_MS)

    def hideEvent(self, event):
        # No point repainting colour blends nobody can see.
        self._color_timer.stop()
        self._hue_anim.stop()
        super().hideEvent(event)

    def resizeEvent(self, event):
        self.card.setMaximumWidth(int(self.width() * 0.86))
        super().resizeEvent(event)
        self._render()

    # ---- captions ---------------------------------------------------------

    def _set_alpha(self, value):
        self._alpha = float(value)
        self._render()

    def _rgba(self, color):
        c = QColor(color)
        return f"rgba({c.red()},{c.green()},{c.blue()},{self._alpha:.2f})"

    def _html(self, committed, partial):
        colors = self._colors()
        parts = []
        if committed:
            parts.append(f'<span style="color:{self._rgba(colors["text"])}">{html.escape(committed)}</span>')
        if partial:
            parts.append(f'<span style="color:{self._rgba(colors["accent"])}">{html.escape(partial)}</span>')
        return f'<p align="center" style="line-height:118%">{" ".join(parts)}</p>' if parts else ""

    def _fit(self):
        """Drop the oldest words until the caption fits on screen; returns (html, height)."""
        committed, partial = self._committed.split(), self._partial.split()
        width = max(200, int(self.width() * 0.86) - 2 * CARD_MARGIN_X - 2)   # 2 = card border
        limit = self.height() * MAX_TEXT_HEIGHT
        doc = QTextDocument()
        doc.setDocumentMargin(0)
        doc.setDefaultFont(self.label.font())
        doc.setTextWidth(width)
        while True:
            markup = self._html(" ".join(committed), " ".join(partial))
            doc.setHtml(markup)
            height = doc.size().height()
            if height <= limit or len(committed) + len(partial) <= 1:
                return markup, height
            if committed:
                committed.pop(0)
            else:
                partial.pop(0)

    def _render(self):
        markup, height = self._fit()
        self.label.setText(markup)
        self.label.setFixedHeight(int(height) + 8)
        has_text = bool(markup)
        self.card.setVisible(has_text)
        self.placeholder.setVisible(not has_text)
        self.dot.set_active(bool(self._partial))
        if has_text:
            self.status.setText("LIVE" if self._partial else "LISTENING")

    def set_caption(self, committed, partial=""):
        was_empty = not (self._committed or self._partial)
        # Keep only the newest MAX_WORDS words; the live (partial) ones keep their accent colour.
        words = committed.split() + partial.split()
        shown = words[-MAX_WORDS:]
        live = min(len(partial.split()), len(shown))
        self._committed = " ".join(shown[:len(shown) - live])
        self._partial = " ".join(shown[len(shown) - live:])
        if (committed or partial) and was_empty:
            self._alpha = 0.0   # start invisible, or the first frame flashes before the fade
        self._render()
        # Partial captions update several times a second; fade only when a new caption appears.
        # The engine owns clearing after silence, so there is no idle timer here.
        if (committed or partial) and was_empty:
            self.fade.stop()
            self.fade.start()

    def _clear_pressed(self):
        self.clear_caption()
        self.clear_requested.emit()

    def clear_caption(self):
        self._committed = self._partial = ""
        self._render()
        self.status.setText("LISTENING")

    def show_status(self, message):
        if not (self._committed or self._partial):
            self.status.setText(message)
