# Voxlay

**Live voice captions on your screen, fully on-device.**

Voxlay listens to your microphone, transcribes your speech in real time with Whisper, and shows the words as large animated captions in a full-screen overlay. No browser, no account, no API key, and no audio leaves your machine.

Use it for streams, talks, classrooms, video calls, or anywhere live speech should also be readable.

## Features

- **Real-time captions.** Words show up while you speak and settle when the phrase ends.
- **Local-first.** The model downloads once, then all transcription runs offline on your machine.
- **Fast on Apple Silicon.** Uses [MLX Whisper](https://github.com/ml-explore/mlx-examples) on the Apple GPU. Other platforms use [faster-whisper](https://github.com/SYSTRAN/faster-whisper) on CPU or NVIDIA CUDA.
- **7 caption themes:** Comic, Neon, Arcade, Marker, Retro, Glitch and Signage, each with its own font and glow.
- **Voice theme switch.** Say **"tweniee"** to jump to the next theme. Voxlay strips the trigger word from the caption.
- **Auto-clear.** The caption clears when its text has not changed for 4.5 seconds.
- **Remembers your setup.** Theme, size and colour mode persist between launches.

## Requirements

- Python 3.10–3.13
- macOS, Windows, or Linux with a working microphone
- 8 GB RAM recommended for the default `small` model
- Internet on first launch only, to download the speech model

## Install

Clone the repository, then set up a virtual environment.

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
| `VOXLAY_MODEL` | `small` | Whisper model: `base` (faster), `small`, `medium` (more accurate), `turbo`, or a Hugging Face repo id in the active backend's format (MLX or CTranslate2) |
| `VOXLAY_BACKEND` | unset (auto) | `mlx` or `faster-whisper`. Unset picks `mlx` on Apple Silicon and `faster-whisper` elsewhere. Any value other than `mlx` uses `faster-whisper` |
| `VOXLAY_DEVICE` | `cpu` | `cpu` or `cuda` (faster-whisper only) |
| `VOXLAY_COMPUTE` | `int8` on CPU, `float16` on GPU | CTranslate2 compute type (faster-whisper only) |

Examples:

```bash
VOXLAY_MODEL=base python main.py                            # lighter, faster
VOXLAY_DEVICE=cuda VOXLAY_COMPUTE=float16 python main.py    # NVIDIA GPU
```

CUDA needs a compatible NVIDIA driver and the CUDA/cuDNN runtime. If CUDA fails to start, use CPU mode.

## How it works

1. `voxlay/audio.py` captures 16 kHz mono audio in 100 ms blocks.
2. `voxlay/engine.py` splits speech into short utterances by loudness and silence. It re-transcribes each utterance while you speak, then commits it when you pause. Built-in guards drop decoder loops and noise that Whisper mistakes for speech.
3. `voxlay/overlay.py` renders the caption in a frameless, always-on-top PySide6 window.

## Limitations

- Voxlay is a practical live-captioning tool, not certified stenography. Accuracy and latency depend on your hardware, microphone, background noise, and model size.
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
    └── fonts/           # bundled display fonts + licenses
```

## License

Voxlay is released under the [MIT License](LICENSE).

The bundled fonts in `voxlay/fonts/` are third-party works under their own licenses. Bangers, Bungee, Monoton, Press Start 2P, Rubik Glitch and Shrikhand use the SIL Open Font License 1.1. Permanent Marker uses the Apache License 2.0. You can find each license in [`voxlay/fonts/licenses/`](voxlay/fonts/licenses/).
