# Tweniee — live voice captions

A local-first Python desktop caption overlay. It listens to the microphone, transcribes English and Hindi, transliterates Hindi into Hinglish (Roman script), and clears the display after 4.5 seconds of silence. Saying **“tweniee”** switches the caption theme.

## What it does

- Starts microphone capture when the app launches (the OS may ask for microphone permission).
- English stays in English.
- Hindi is rendered in Roman Hindi/Hinglish.
- Mixed Hindi-English is kept as naturally as the recognizer returns it, with Devanagari words transliterated.
- Caption themes animate in; the spoken trigger `tweniee` switches the visual theme.
- Captions clear after 4.5 seconds without speech.
- No browser, account, or API key required.

## Requirements

- Python 3.10–3.12 recommended.
- Windows, macOS, or Linux with a working microphone.
- Internet is needed on first launch to download the Whisper model. Transcription itself runs locally after that.
- 8 GB RAM recommended. The default `small` model is a reasonable CPU starting point. `Tweniee` can be configured to use `base`, `small`, or `medium`.

## Install

### macOS / Linux

```bash
cd tweniee
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
python main.py
```

### Windows PowerShell

```powershell
cd tweniee
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python main.py
```

The first run downloads the model automatically. Keep the app open while the model loads.

## Performance tuning

Set environment variables before launching:

```bash
TWENIEE_MODEL=base python main.py       # faster, less accurate
TWENIEE_MODEL=small python main.py      # default balance
TWENIEE_MODEL=medium python main.py     # slower, potentially more accurate
TWENIEE_DEVICE=cpu python main.py
TWENIEE_COMPUTE=int8 python main.py
```

For a supported NVIDIA GPU, try:

```bash
TWENIEE_DEVICE=cuda TWENIEE_COMPUTE=float16 python main.py
```

CUDA requires a compatible NVIDIA driver and CUDA/cuDNN runtime. If CUDA initialization fails, use CPU mode.

## Notes / limitations

- This is a practical local MVP, not a certified stenography system. Recognition latency and accuracy depend on hardware, microphone quality, noise, and model size.
- Hindi/English code-switching can be imperfect because speech models sometimes classify a mixed phrase as one language.
- The trigger is detected from recognized text. If the recognizer hears a different spelling, the trigger may not fire.
- The app uses a native desktop window rather than a browser. The window is frameless and stays on top; press `Esc` to quit.
- Microphone permission is controlled by your operating system. If permission is denied, enable it in OS privacy settings and relaunch.

## Project structure

```text
tweniee/
├── main.py
├── requirements.txt
└── tweniee/
    ├── audio.py
    ├── engine.py
    ├── overlay.py
    └── transliterate.py
```
