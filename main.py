import os
import sys
from PySide6.QtWidgets import QApplication, QMessageBox
from voxlay.overlay import CaptionOverlay
from voxlay.audio import AudioCapture
from voxlay.engine import TranscriptionWorker

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Voxlay")

    overlay = CaptionOverlay()
    overlay.showFullScreen()

    worker = TranscriptionWorker()
    audio = AudioCapture(on_audio=worker.submit_audio,
                         on_error=worker.status.emit)  # signal: callback runs off the GUI thread
    worker.caption.connect(overlay.set_caption)
    worker.status.connect(overlay.show_status)
    worker.theme_changed.connect(overlay.next_theme)
    overlay.clear_requested.connect(worker.request_clear)
    worker.start()

    try:
        audio.start()
    except Exception as exc:
        QMessageBox.critical(None, "Microphone error",
                             f"Could not start microphone capture:\n\n{exc}\n\n"
                             "Check your operating-system microphone permission.")
        worker.stop()
        if not worker.wait(5000):
            os._exit(1)
        return 1

    def shutdown():
        audio.stop()
        worker.stop()
        if not worker.wait(5000):
            # Still loading or downloading the model; it cannot be interrupted, so exit hard.
            overlay._settings.sync()
            os._exit(0)

    app.aboutToQuit.connect(shutdown)
    return app.exec()

if __name__ == "__main__":
    raise SystemExit(main())
