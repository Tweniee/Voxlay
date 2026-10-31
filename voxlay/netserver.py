import hmac
import json
import socket
import ipaddress
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, unquote
from PySide6.QtCore import QObject, QTimer, QUrlQuery, Signal
from PySide6.QtNetwork import QAbstractSocket, QHostAddress, QNetworkInterface
from PySide6.QtWebSockets import QWebSocket, QWebSocketProtocol, QWebSocketServer
from .config import FONT_DIR

WEB_DIR = Path(__file__).parent / "web"
PING_EVERY_MS = 5000
MAX_MISSED_PONGS = 2
MAX_CLIENTS = 32
MAX_MESSAGE_BYTES = 4096        # clients only ever send tiny hello / pong frames
MAX_BACKLOG_BYTES = 64 * 1024   # skip a device whose socket is not draining
PORT_TRIES = 20


def lan_ip():
    """Address other devices on the LAN can reach; no packet is actually sent."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("10.255.255.255", 1))
        return probe.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        probe.close()


def lan_candidates():
    """[(interface name, private IPv4)] for every interface that is up, preferred address first."""
    found = []
    for iface in QNetworkInterface.allInterfaces():
        flags = iface.flags()
        if not (flags & QNetworkInterface.InterfaceFlag.IsUp
                and flags & QNetworkInterface.InterfaceFlag.IsRunning
                and not flags & QNetworkInterface.InterfaceFlag.IsLoopBack):
            continue
        for entry in iface.addressEntries():
            addr = entry.ip()
            if addr.protocol() != QAbstractSocket.NetworkLayerProtocol.IPv4Protocol:
                continue
            ip = ipaddress.ip_address(addr.toString())
            if ip.is_private and not ip.is_link_local and not ip.is_loopback:
                found.append((iface.humanReadableName(), str(ip)))
    preferred = lan_ip()
    found.sort(key=lambda item: item[1] != preferred)
    return found


def _handler(fonts):
    """Request handler serving only index.html and the whitelisted fonts; it never touches Qt."""
    class Handler(BaseHTTPRequestHandler):
        server_version = "Voxlay"

        def log_message(self, *_args):
            pass

        def _send(self, status, body=b"", content_type="text/plain; charset=utf-8", cache="no-store"):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", cache)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = unquote(urlsplit(self.path).path)
            try:
                if path in ("/", "/index.html"):
                    self._send(200, (WEB_DIR / "index.html").read_bytes(), "text/html; charset=utf-8")
                elif path.startswith("/fonts/") and path[len("/fonts/"):] in fonts:
                    # Exact match against the whitelist, so no path can climb out of the fonts folder.
                    body = (FONT_DIR / path[len("/fonts/"):]).read_bytes()
                    self._send(200, body, "font/ttf", "max-age=86400")
                else:
                    self._send(404, b"Not found")
            except OSError:
                self._send(404, b"Not found")

    return Handler


class CaptionServer(QObject):
    """HTTP page + WebSocket feed for web clients. Clients are addressed by id, in join order."""
    clients_changed = Signal(int)
    client_joined = Signal(str)
    client_left = Signal(str)

    def __init__(self, token="", parent=None):
        super().__init__(parent)
        self._token = token
        self._ws = QWebSocketServer("Voxlay", QWebSocketServer.SslMode.NonSecureMode, self)
        self._ws.newConnection.connect(self._on_connection)
        self._httpd = None
        self._thread = None
        self._clients = {}      # id -> QWebSocket, in join order
        self._missed = {}       # id -> pings without a pong
        self._counter = 0
        self._style = None
        self._ip = "127.0.0.1"
        self._port = 0
        self._ping = QTimer(self)
        self._ping.timeout.connect(self._ping_all)

    # ---- lifecycle --------------------------------------------------------

    def start(self, port, ip=""):
        """Serve the page on `port` and the socket on `port + 1`; scans upward when taken."""
        fonts = frozenset(p.name for p in FONT_DIR.glob("*.ttf"))
        for offset in range(PORT_TRIES):
            http_port = port + offset
            if http_port + 1 > 65535:
                break
            try:
                httpd = ThreadingHTTPServer(("", http_port), _handler(fonts))
            except OSError:
                continue
            if not self._ws.listen(QHostAddress.SpecialAddress.Any, http_port + 1):
                httpd.server_close()
                continue
            httpd.daemon_threads = True
            self._httpd = httpd
            self._thread = threading.Thread(target=httpd.serve_forever, name="voxlay-http", daemon=True)
            self._thread.start()
            self._port = http_port
            self._ip = ip or lan_ip()
            self._ping.start(PING_EVERY_MS)
            return True
        return False

    def stop(self):
        self._ping.stop()
        for sock in list(self._clients.values()):
            sock.close(QWebSocketProtocol.CloseCode.CloseCodeGoingAway)
        self._ws.close()
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._thread.join(2)
            self._httpd = None

    def port(self):
        return self._port

    def url(self):
        query = f"/?t={self._token}" if self._token else "/"
        return f"http://{self._ip}:{self._port}{query}"

    # ---- clients ----------------------------------------------------------

    def client_ids(self):
        return list(self._clients)

    def set_style(self, message):
        """Remember the style for devices that join later, and push it to those already here."""
        self._style = message
        self.broadcast(message)

    def send_to(self, client_id, message):
        sock = self._clients.get(client_id)
        if (sock is None or sock.state() != QAbstractSocket.SocketState.ConnectedState
                or sock.bytesToWrite() > MAX_BACKLOG_BYTES):
            return False
        sock.sendTextMessage(json.dumps(message, ensure_ascii=False))
        return True

    def broadcast(self, message):
        for client_id in self.client_ids():
            self.send_to(client_id, message)

    def _on_connection(self):
        sock = self._ws.nextPendingConnection()
        if sock is None:
            return
        given = QUrlQuery(sock.requestUrl()).queryItemValue("t")
        if (self._token and not hmac.compare_digest(given.encode(), self._token.encode())) \
                or len(self._clients) >= MAX_CLIENTS:
            sock.disconnected.connect(sock.deleteLater)
            sock.close(QWebSocketProtocol.CloseCode.CloseCodePolicyViolated, "not allowed")
            return
        sock.setMaxAllowedIncomingMessageSize(MAX_MESSAGE_BYTES)
        sock.disconnected.connect(sock.deleteLater)
        self._counter += 1
        client_id = f"c{self._counter}"
        self._clients[client_id] = sock
        self._missed[client_id] = 0
        sock.textMessageReceived.connect(lambda text, cid=client_id: self._on_message(cid, text))
        sock.disconnected.connect(lambda cid=client_id: self._drop(cid))
        self.send_to(client_id, {"type": "hello", "id": client_id, "devices": len(self._clients)})
        if self._style is not None:
            self.send_to(client_id, self._style)
        self.client_joined.emit(client_id)
        self._announce()

    def _on_message(self, client_id, text):
        try:
            message = json.loads(text)
        except ValueError:
            return
        if isinstance(message, dict) and message.get("type") == "pong":
            self._missed[client_id] = 0
        # Client "hello" carries only user-agent and screen size; nothing needs it yet.

    def _drop(self, client_id):
        sock = self._clients.pop(client_id, None)
        self._missed.pop(client_id, None)
        if sock is None:
            return
        self.client_left.emit(client_id)
        self._announce()

    def _announce(self):
        self.broadcast({"type": "devices", "n": len(self._clients)})
        self.clients_changed.emit(len(self._clients))

    def _ping_all(self):
        for client_id in self.client_ids():
            if self._missed.get(client_id, 0) >= MAX_MISSED_PONGS:
                self._clients[client_id].abort()   # fires disconnected, which drops it
                self._drop(client_id)
                continue
            self._missed[client_id] = self._missed.get(client_id, 0) + 1
            self.send_to(client_id, {"type": "ping"})
