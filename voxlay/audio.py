import threading
import numpy as np
import sounddevice as sd

class AudioCapture:
    """Captures mono 16 kHz audio and forwards each 100 ms block immediately."""
    def __init__(self, on_audio, on_error=None):
        self.on_audio = on_audio
        self.on_error = on_error or (lambda _msg: None)
        self.sample_rate = 16000
        self.block_samples = 1600
        self._stream = None
        self._running = False

    def _callback(self, indata, frames, time_info, status):
        if status:
            self.on_error(f"Audio input: {status}")
        self.on_audio(indata[:, 0].astype(np.float32, copy=True))

    def start(self):
        self._running = True
        self._stream = sd.InputStream(
            samplerate=self.sample_rate, channels=1, dtype="float32",
            blocksize=self.block_samples, latency="low", callback=self._callback
        )
        self._stream.start()

    def stop(self):
        self._running = False
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
