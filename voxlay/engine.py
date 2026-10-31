import os
import re
import sys
import time
import queue
import platform
from collections import deque
import numpy as np
from PySide6.QtCore import QThread, Signal
from .transliterate import to_hinglish

TRIGGER_RE = re.compile(r"\b(?:twen(?:iee|y|ee|i)|tween(?:y|ie|ee))\b|ट्व[ीेि]न[ीि]", re.IGNORECASE)

SAMPLE_RATE = 16000
SPEECH_RMS = 0.008          # blocks louder than this count as speech
END_SILENCE = 0.5           # seconds of quiet that close an utterance
PRE_ROLL = 0.3              # audio kept before speech starts, so first syllables are not cut
SOFT_MAX = 5.0              # past this, commit the utterance at the next quiet block
HARD_MAX = 8.0              # always commit at this length to keep each pass fast
CLEAR_AFTER = 4.5           # blank the caption after this much silence
DISPLAY_CHARS = 120         # rolling caption length shown on screen (large font, ~3 lines)
DETECT_AFTER = 1.0          # seconds of speech needed for reliable language detection
MIN_VOICED = 0.2            # loud audio needed before the first partial; shorter clips hallucinate

REPEAT_WORDS_RE = re.compile(r"(?<!\S)(\S+)(?:[\s,]+\1(?![^\s,])){3,}")
REPEAT_PHRASE_RE = re.compile(r"(?<!\S)(\S+(?:\s+\S+){1,3}?)(?:[\s,]+\1(?![^\s,])){2,}")
REPEAT_CHARS_RE = re.compile(r"((?:(?!\d)\S){1,4}?)\1{3,}")   # digits excluded: 10000 is not a loop


LANGUAGES = [c.strip() for c in os.getenv("VOXLAY_LANGS", "en,hi").split(",") if c.strip()] or ["en", "hi"]
LOOP_RATIO = 2.4            # zlib ratio above this means the decoder got stuck repeating itself
NO_SPEECH_PROB = 0.6        # with LOW_LOGPROB: Whisper's own "this is not speech" rule
LOW_LOGPROB = -1.0


class _MlxBackend:
    """Whisper on the Apple GPU through MLX: one encoder pass per call, shared by detection and decoding."""
    def __init__(self, model_name):
        import mlx.core as mx
        from mlx_whisper.audio import log_mel_spectrogram, pad_or_trim, N_FRAMES, N_SAMPLES
        from mlx_whisper.decoding import DecodingOptions
        from mlx_whisper.load_models import load_model
        if "/" in model_name:
            repo = model_name
        elif model_name in ("turbo", "large-v3-turbo"):
            repo = "mlx-community/whisper-large-v3-turbo"
        else:
            repo = f"mlx-community/whisper-{model_name}-mlx"
        self._mx = mx
        # Pad the audio, not the spectrogram: zero mel frames are not silence to Whisper and cause hallucinations.
        self._mel = lambda audio, n_mels: log_mel_spectrogram(audio, n_mels=n_mels, padding=N_SAMPLES)
        self._pad = lambda mel: pad_or_trim(mel, N_FRAMES, axis=-2)
        self._options = DecodingOptions
        self._model = load_model(repo, dtype=mx.float16)

    def transcribe(self, audio, language):
        mel = self._pad(self._mel(audio, n_mels=self._model.dims.n_mels)).astype(self._mx.float16)
        features = self._model.encoder(mel[None])
        if language is None and not self._model.is_multilingual:
            language = "en"
        if language is None:
            _, probs = self._model.detect_language(features)
            language = _pick_language(probs[0])
        result = self._model.decode(features, self._options(
            language=language, without_timestamps=True, fp16=True,
            temperature=0.0, sample_len=_token_budget(audio),
        ))[0]
        if result.compression_ratio > LOOP_RATIO:
            return None, language
        if result.no_speech_prob > NO_SPEECH_PROB and result.avg_logprob < LOW_LOGPROB:
            return "", language   # noise (fan, music) mistaken for speech
        return _collapse_repeats(result.text.strip()), language


class _FasterWhisperBackend:
    """CPU / CUDA fallback through CTranslate2."""
    def __init__(self, model_name, device, compute):
        from faster_whisper import WhisperModel
        self._model = WhisperModel(model_name, device=device, compute_type=compute)

    def transcribe(self, audio, language):
        if language is None and not self._model.model.is_multilingual:
            language = "en"
        if language is None:
            _, _, probs = self._model.detect_language(audio)
            language = _pick_language(dict(probs))
        segments, _ = self._model.transcribe(
            audio, language=language, task="transcribe", beam_size=1,
            temperature=0.0, condition_on_previous_text=False,
            without_timestamps=True, vad_filter=False,
            max_new_tokens=_token_budget(audio),
        )
        segments = list(segments)
        if any(seg.compression_ratio > LOOP_RATIO for seg in segments):
            return None, language
        return _collapse_repeats(" ".join(seg.text.strip() for seg in segments).strip()), language


def _pick_language(probs):
    # Restricting to the expected languages stops short clips being heard as Spanish, Urdu, etc.
    return max(LANGUAGES, key=lambda code: probs.get(code, 0.0))


def _collapse_repeats(text):
    """Trim decoder loops such as "agara agara agara" or "chchchch" down to one copy."""
    text = REPEAT_PHRASE_RE.sub(r"\1", REPEAT_WORDS_RE.sub(r"\1", text))
    return REPEAT_CHARS_RE.sub(r"\1", text)


def _token_budget(audio):
    # Caps runaway decoder loops. Hindi runs about 14 tokens per second of speech.
    return min(160, int(len(audio) / SAMPLE_RATE * 18) + 12)


def _tail(text, limit):
    """Last `limit` characters of text, starting on a word boundary."""
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    text = text[-limit:]
    return text.split(" ", 1)[-1] if " " in text else text


def _rms(block):
    return float(np.sqrt(np.mean(np.square(block)))) if len(block) else 0.0


class TranscriptionWorker(QThread):
    """Streams partial captions: re-transcribes the current utterance as audio arrives."""
    caption = Signal(str, str)
    committed = Signal(str)
    status = Signal(str)
    theme_changed = Signal()

    def __init__(self):
        super().__init__()
        self._queue = queue.Queue(maxsize=200)
        self._stopping = False
        self._backend = None
        self._clear_requested = False
        self._language = os.getenv("VOXLAY_LANG") or None
        self._fixed_language = bool(self._language)
        self._reset_state()

    def _reset_state(self):
        self._utterance = []
        self._utterance_len = 0
        self._transcribed_len = 0
        self._voiced = 0
        self._voiced_at_pass = 0
        self._utterance_lang = self._language
        self._lang_locked = self._fixed_language
        self._in_speech = False
        self._clock = 0.0
        self._last_voice = 0.0
        self._last_text_change = 0.0
        self._pass_clock = 0.0
        self._pre_roll = deque(maxlen=max(1, int(PRE_ROLL * 10)))
        self._committed = ""
        self._partial = ""
        self._last_emitted = None

    def submit_audio(self, audio):
        try:
            self._queue.put_nowait(audio)
        except queue.Full:
            # Drop the oldest block rather than accumulating latency.
            try:
                self._queue.get_nowait()
                self._queue.put_nowait(audio)
            except queue.Empty:
                pass

    def request_clear(self):
        """Called from the GUI thread; the worker clears on its next loop."""
        self._clear_requested = True

    def stop(self):
        self._stopping = True
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass

    def _load_model(self):
        model_name = os.getenv("VOXLAY_MODEL", "small")
        backend = os.getenv("VOXLAY_BACKEND")
        if backend is None:
            apple_silicon = sys.platform == "darwin" and platform.machine() == "arm64"
            backend = "mlx" if apple_silicon else "faster-whisper"
        self.status.emit(f"Loading {model_name} speech model ({backend})… first launch downloads it")
        if backend == "mlx":
            self._backend = _MlxBackend(model_name)
        else:
            device = os.getenv("VOXLAY_DEVICE", "cpu")
            compute = os.getenv("VOXLAY_COMPUTE", "int8" if device == "cpu" else "float16")
            self._backend = _FasterWhisperBackend(model_name, device, compute)
        if self._stopping:
            return
        # Warm-up pass: the first call compiles kernels and would stall the first caption.
        self._backend.transcribe(np.zeros(SAMPLE_RATE, dtype=np.float32), self._language or "en")
        # Discard audio queued during loading; captioning it would put every caption seconds behind.
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
        self.status.emit("Listening")

    def _show(self):
        """Emit (settled text, live text) so the overlay can style words still being revised."""
        partial = _tail(to_hinglish(TRIGGER_RE.sub("", self._partial).strip(" ,")), DISPLAY_CHARS)
        committed = _tail(self._committed, DISPLAY_CHARS - len(partial) - 1)
        shown = (committed, partial)
        if shown != self._last_emitted:
            self.caption.emit(committed, partial)
            self._last_emitted = shown
            # Clearing keys off text changes, not loudness, so fans or typing cannot pin old captions.
            self._last_text_change = time.monotonic()

    def _transcribe_utterance(self):
        audio = np.concatenate(self._utterance)
        self._transcribed_len = self._utterance_len
        self._voiced_at_pass = self._voiced
        self._pass_clock = self._clock
        # Detect on every pass until enough audio exists, then lock so the script stops flipping.
        language = self._utterance_lang if self._lang_locked else None
        text, detected = self._backend.transcribe(audio, language)
        self._utterance_lang = detected
        if self._utterance_len >= DETECT_AFTER * SAMPLE_RATE:
            self._lang_locked = True
        return text

    def _commit(self):
        """Finalize the current utterance and fold it into the rolling caption."""
        try:
            # Re-run if speech arrived since the last pass, or that pass cut into the last word's tail.
            new_speech = self._voiced > self._voiced_at_pass
            cut_tail = self._pass_clock - self._last_voice < 0.3
            if (self._utterance and (new_speech or cut_tail)
                    and self._transcribed_len < self._utterance_len
                    and self._voiced >= MIN_VOICED * SAMPLE_RATE):
                text = self._transcribe_utterance()
                if text is not None:
                    self._partial = text
            text = self._partial
            romanized = to_hinglish(text)
            if TRIGGER_RE.search(text) or TRIGGER_RE.search(romanized):
                self.theme_changed.emit()
            text = re.sub(r"\s{2,}", " ", TRIGGER_RE.sub("", romanized)).strip(" ,.!?")
            if text:
                self._committed = f"{self._committed} {text}".strip()[-DISPLAY_CHARS * 2:]
                self.committed.emit(text)
        finally:
            # Always reset, or a failed pass would re-commit on every following block.
            self._partial = ""
            self._utterance = []
            self._utterance_len = 0
            self._transcribed_len = 0
            self._voiced = 0
            self._voiced_at_pass = 0
            self._utterance_lang = self._language
            self._lang_locked = self._fixed_language
        self._show()

    def _feed(self, block, now):
        # Silence is measured on the audio clock: a drained batch shares one wall-clock time.
        self._clock += len(block) / SAMPLE_RATE
        loud = _rms(block) >= SPEECH_RMS
        if loud:
            self._last_voice = self._clock
        if not self._in_speech:
            if not loud:
                self._pre_roll.append(block)
                return
            self._in_speech = True
            self._utterance = list(self._pre_roll)
            self._utterance_len = sum(len(b) for b in self._utterance)
            self._pre_roll.clear()
        self._utterance.append(block)
        self._utterance_len += len(block)
        if loud:
            self._voiced += len(block)
        seconds = self._utterance_len / SAMPLE_RATE
        if self._clock - self._last_voice >= END_SILENCE:
            self._in_speech = False
            self._commit()
        elif seconds >= HARD_MAX or (seconds >= SOFT_MAX and not loud):
            self._commit()

    def run(self):
        try:
            self._load_model()
        except Exception as exc:
            self.status.emit(f"Model error: {exc}")
            return

        while not self._stopping:
            try:
                block = self._queue.get(timeout=0.05)
            except queue.Empty:
                block = None
            # Drain everything that arrived while the last pass ran.
            blocks = [] if block is None else [block]
            while True:
                try:
                    more = self._queue.get_nowait()
                except queue.Empty:
                    break
                if more is not None:
                    blocks.append(more)
            if self._stopping:
                break

            try:
                now = time.monotonic()
                if self._clear_requested:
                    self._clear_requested = False
                    self._committed = ""
                    self._partial = ""
                for b in blocks:
                    self._feed(b, now)

                if (self._in_speech and self._voiced >= MIN_VOICED * SAMPLE_RATE
                        and self._voiced > self._voiced_at_pass
                        and self._utterance_len - self._transcribed_len >= SAMPLE_RATE * 0.1):
                    text = self._transcribe_utterance()
                    if text is not None:
                        self._partial = text
                        self._show()
                if (any(self._last_emitted or ())
                        and time.monotonic() - self._last_text_change > CLEAR_AFTER):
                    self._committed = ""
                    self._partial = ""
                    self._show()
            except Exception as exc:
                self.status.emit(f"Transcription hiccup: {exc}")
