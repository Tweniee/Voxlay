import random
from collections import deque
from PySide6.QtCore import QObject, QTimer, Signal

HOST = "host"            # pseudo client id for the machine running Tweniee
STAGGER_MS = (150, 250)  # pause between chunks of one phrase
MAX_PENDING = 12         # chunks waiting to be sent; the oldest are dropped beyond this


def split_chunks(words, min_w, max_w, random_size, rng):
    """Split words into chunks of min_w..max_w words; punctuation stays with its word."""
    words = words.split() if isinstance(words, str) else list(words)
    min_w = max(1, min_w)
    max_w = max(min_w, max_w)
    chunks = []
    i = 0
    while i < len(words):
        left = len(words) - i
        size = rng.randint(min_w, max_w) if random_size else max_w
        size = min(size, left)
        rest = left - size
        if 0 < rest < min_w:
            # Taking `size` would strand a too-short tail: finish here, or leave enough for a full chunk.
            size = left if left <= max_w else max(min_w, left - min_w)
        chunks.append(words[i:i + size])
        i += size
    # Last resort for a stranded tail the loop could not avoid: fold it back if it still fits.
    if len(chunks) > 1 and len(chunks[-1]) < min_w and len(chunks[-2]) + len(chunks[-1]) <= max_w:
        chunks[-2] += chunks.pop()
    return [" ".join(chunk) for chunk in chunks]


class Router(QObject):
    """Splits each committed phrase into chunks and hands every chunk to ONE device."""
    chunk_for_host = Signal(str)
    chunk_sent = Signal(str, str)   # (client id, chunk), HOST for the local screen

    def __init__(self, server, config, rng=None, parent=None):
        super().__init__(parent)
        self._server = server
        self._config = config
        self._rng = rng or random.Random()
        self._pending = deque()
        self._last_id = None
        self._last_pool = []
        self._seq = 0
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._pump)

    def set_config(self, config):
        self._config = config

    def clear(self):
        self._pending.clear()
        self._timer.stop()

    def on_committed(self, text):
        c = self._config
        chunks = split_chunks(text, c.min_words, c.max_words, c.random_size, self._rng)
        self._pending.extend(chunks)
        while len(self._pending) > MAX_PENDING:
            self._pending.popleft()
        if not self._timer.isActive():
            self._pump()

    def _pump(self):
        if not self._pending:
            return
        self._dispatch(self._pending.popleft())
        if self._pending:
            self._timer.start(self._rng.randint(*STAGGER_MS))

    def _pool(self):
        remote = list(self._server.client_ids())
        if not remote:
            return [HOST]   # nobody connected: the host screen shows the captions itself
        return [HOST] + remote if self._config.host_mode == "screen" else remote

    def _pick(self, pool):
        if self._config.mode == "loop":
            chosen = self._next_in_loop(pool)
        else:
            others = [p for p in pool if p != self._last_id]
            chosen = self._rng.choice(others if len(pool) >= 2 and others else pool)
        self._last_id = chosen
        self._last_pool = list(pool)
        return chosen

    def _next_in_loop(self, pool):
        if self._last_id in pool:
            return pool[(pool.index(self._last_id) + 1) % len(pool)]
        # The previous device left: carry on with whoever followed it in the old order.
        if self._last_id in self._last_pool:
            old = self._last_pool
            start = old.index(self._last_id)
            for step in range(1, len(old) + 1):
                candidate = old[(start + step) % len(old)]
                if candidate in pool:
                    return candidate
        return pool[0]

    def _dispatch(self, chunk):
        pool = self._pool()
        while pool:
            target = self._pick(pool)
            if target == HOST:
                self.chunk_for_host.emit(chunk)
                self.chunk_sent.emit(HOST, chunk)
                return
            self._seq += 1
            if self._server.send_to(target, {"type": "caption", "id": target,
                                             "seq": self._seq, "text": chunk}):
                self.chunk_sent.emit(target, chunk)
                return
            pool = [p for p in pool if p != target]   # socket gone: pick someone else
        self.chunk_for_host.emit(chunk)
        self.chunk_sent.emit(HOST, chunk)
