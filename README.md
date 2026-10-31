# Voxlay

**Live voice captions on your screen, fully on-device.**

Voxlay listens to your microphone, transcribes English and Hindi in real time with Whisper, and shows the words as large animated captions in a full-screen overlay. Hindi comes out in Hinglish (Roman script), so every caption reads in one script. No browser, no account, no API key, and no audio leaves your machine.

Use it for streams, talks, classrooms, video calls, or anywhere live speech should also be readable.

## Features

- **Real-time captions.** Words show up while you speak and settle when the phrase ends.
- **English + Hindi.** Language detection runs per phrase, limited to the languages you expect, so short clips are not misread as other languages.
- **Hinglish output.** Devanagari is transliterated to Roman script. Mixed Hindi-English stays as natural as the recognizer returns it.
- **Local-first.** The model downloads once, then all transcription runs offline on your machine.
- **Fast on Apple Silicon.** Uses [MLX Whisper](https://github.com/ml-explore/mlx-examples) on the Apple GPU. Other platforms use [faster-whisper](https://github.com/SYSTRAN/faster-whisper) on CPU or NVIDIA CUDA.
- **7 caption themes:** Comic, Neon, Arcade, Marker, Retro, Glitch and Signage, each with its own font and glow.
- **Voice theme switch.** Say **"tweniee"** to jump to the next theme. Voxlay strips the trigger word from the caption.
- **Auto-clear.** Captions clear after 4.5 seconds without new speech.
- **Remembers your setup.** Theme, size and colour mode persist between launches.

## Requirements

- Python 3.10–3.12
- macOS, Windows, or Linux with a working microphone
- 8 GB RAM recommended for the default `small` model
- Internet on first launch only, to download the speech model

## Install

### macOS / Linux

```bash
cd voxlay
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
python main.py
```

### Windows (PowerShell)

```powershell
cd voxlay
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python main.py
```

The first run downloads the model, so keep the window open until the status bar says **Listening**. Your OS may ask for microphone permission. If you deny it, enable it in your privacy settings and relaunch.

## Controls

| Input | Action |
| --- | --- |
| `+` / `-` or scroll wheel | Caption size |
| `0` | Reset size |
| `T` or right-click | Next theme |
| `R` | Toggle colour cycling |
| `F` or double-click | Toggle fullscreen |
| `C` | Clear caption |
| `H` | Show / hide hints |
| `Esc` | Quit |
| Say "tweniee" | Next theme |

## Configuration

Set environment variables before you launch:

| Variable | Default | Purpose |
| --- | --- | --- |
| `VOXLAY_MODEL` | `small` | Whisper model: `base` (faster), `small`, `medium` (more accurate), `turbo` (MLX only), or a Hugging Face repo id |
| `VOXLAY_BACKEND` | auto | `mlx` on Apple Silicon, `faster-whisper` elsewhere |
| `VOXLAY_DEVICE` | `cpu` | `cpu` or `cuda` (faster-whisper only) |
| `VOXLAY_COMPUTE` | `int8` on CPU, `float16` on GPU | CTranslate2 compute type (faster-whisper only) |
| `VOXLAY_LANGS` | `en,hi` | Languages that auto-detection may choose from |
| `VOXLAY_LANG` | unset | Force one language and skip detection, for example `hi` |

Examples:

```bash
VOXLAY_MODEL=base python main.py                            # lighter, faster
VOXLAY_DEVICE=cuda VOXLAY_COMPUTE=float16 python main.py    # NVIDIA GPU
VOXLAY_LANG=en python main.py                               # English only
```

CUDA needs a compatible NVIDIA driver and the CUDA/cuDNN runtime. If CUDA fails to start, use CPU mode.

## How it works

1. `voxlay/audio.py` captures 16 kHz mono audio in 100 ms blocks.
2. `voxlay/engine.py` splits speech into short utterances by loudness and silence. It re-transcribes each utterance while you speak, then commits it when you pause. Built-in guards drop decoder loops and noise that Whisper mistakes for speech.
3. `voxlay/transliterate.py` converts Devanagari to Hinglish.
4. `voxlay/overlay.py` renders the caption in a frameless, always-on-top PySide6 window.

## Limitations

- Voxlay is a practical live-captioning tool, not certified stenography. Accuracy and latency depend on your hardware, microphone, background noise, and model size.
- Hindi-English code-switching can be imperfect. The model sometimes labels a mixed phrase as one language.
- The trigger word works on recognized text. If the recognizer hears a spelling it does not expect, the theme does not switch.

## Project structure

```text
voxlay/
├── main.py              # entry point
├── requirements.txt
└── voxlay/
    ├── audio.py         # microphone capture
    ├── engine.py        # segmentation + Whisper backends
    ├── overlay.py       # caption window and themes
    ├── transliterate.py # Devanagari → Hinglish
    └── fonts/           # bundled display fonts + licenses
```

## License

Voxlay is released under the [MIT License](LICENSE).

The bundled fonts in `voxlay/fonts/` are third-party works under their own licenses. Bangers, Bungee, Monoton, Press Start 2P, Rubik Glitch and Shrikhand use the SIL Open Font License 1.1. Permanent Marker uses the Apache License 2.0. You can find each license in [`voxlay/fonts/licenses/`](voxlay/fonts/licenses/).
