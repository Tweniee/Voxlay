import os
import sys
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox
from voxlay.overlay import CaptionOverlay
from voxlay.audio import AudioCapture
from voxlay.engine import TranscriptionWorker
from voxlay.config import RouteConfig, StyleConfig
from voxlay.netserver import CaptionServer
from voxlay.router import Router

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Voxlay")

    route = RouteConfig.load()
    route.save()  # persists the generated token so devices can reconnect after a restart
    style = StyleConfig.load()

    overlay = CaptionOverlay()
    overlay.showFullScreen()

    worker = TranscriptionWorker()
    audio = AudioCapture(on_audio=worker.submit_audio,
                         on_error=worker.status.emit)  # signal: callback runs off the GUI thread

    server = CaptionServer(route.token)
    live = server.start(route.port, route.ip)
    connect_hint = ""
    if live:
        connect_hint = f"Open on other devices: {server.url()}"
        print(connect_hint, flush=True)
        server.set_style(style.to_message())
        router = Router(server, route)
        mirror = route.host_mode == "mirror"
        hold = QTimer(overlay)
        hold.setSingleShot(True)
        hold.timeout.connect(overlay.clear_caption)

        def host_chunk(chunk):
            overlay.set_caption(chunk)
            hold.start(style.hold_ms)

        def clear_all():
            router.clear()
            server.broadcast({"type": "clear"})

        def on_caption(committed, partial):
            if not (committed or partial):  # engine blanked the caption after silence
                clear_all()

        worker.committed.connect(router.on_committed)
        worker.caption.connect(on_caption)
        overlay.clear_requested.connect(clear_all)
        if mirror:
            worker.caption.connect(overlay.set_caption)
        else:
            router.chunk_for_host.connect(host_chunk)
            worker.caption.connect(lambda c, p: not (c or p) and overlay.clear_caption())
    else:
        QMessageBox.warning(None, "Multi-device unavailable",
                            f"Could not start the LAN server (ports {route.port}-{route.port + 1} "
                            "and upward are busy). Continuing on this screen only.")
        worker.caption.connect(overlay.set_caption)
        overlay.clear_requested.connect(worker.request_clear)

    def on_status(message):
        overlay.show_status(message)
        if connect_hint and message == "Listening":
            overlay.show_status(connect_hint)  # shown until the first caption replaces it

    worker.status.connect(on_status)
    worker.theme_changed.connect(overlay.next_theme)
    if live:
        overlay.clear_requested.connect(worker.request_clear)
    worker.start()

    try:
        audio.start()
    except Exception as exc:
        QMessageBox.critical(None, "Microphone error",
                             f"Could not start microphone capture:\n\n{exc}\n\n"
                             "Check your operating-system microphone permission.")
        server.stop()
        worker.stop()
        if not worker.wait(5000):
            os._exit(1)
        return 1

    def shutdown():
        audio.stop()
        server.stop()
        worker.stop()
        if not worker.wait(5000):
            # Still loading or downloading the model; it cannot be interrupted, so exit hard.
            overlay._settings.sync()
            os._exit(0)

    app.aboutToQuit.connect(shutdown)
    return app.exec()

if __name__ == "__main__":
    raise SystemExit(main())
