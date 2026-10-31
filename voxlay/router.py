import random
from collections import deque
from PySide6.QtCore import QObject, QTimer, Signal

HOST = "host"            # pseudo client id for the machine running Voxlay
STAGGER_MS = (150, 250)  # pause between chunks of one phrase
MAX_PENDING = 12         # chunks waiting to be sent; the oldest are dropped beyond this
MAX_PENDING_PAIRS = 6    # pair mode: pairs waiting behind the one on screen; the oldest are dropped
PAIR_BASE_MS = 400       # pair mode: hold = base + per-word, clamped to [PAIR_MIN_MS, style hold_ms]
PAIR_WORD_MS = 300
PAIR_MIN_MS = 900
PAGE_GRACE_MS = 1000     # a remote page's own timer is only a fallback, this long after the server's clear


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
    """Splits each committed phrase into chunks. Random/loop: each chunk goes to ONE device.
    Pair: chunks go out two at a time, left = host, right = newest remote, both swapped together."""
    chunk_for_host = Signal(str)
    chunk_sent = Signal(str, str)   # (client id, chunk), HOST for the local screen
    host_clear = Signal()           # pair mode: the host half has finished its hold

    def __init__(self, server, config, rng=None, hold_ms=2500, parent=None):
        super().__init__(parent)
        self._server = server
        self._config = config
        self._hold_ms = hold_ms
        self._pairs = deque()
        self._shown = False
        self._phrase = 0
        self._rng = rng or random.Random()
        self._pending = deque()
        self._last_id = None
        self._last_pool = []
        self._seq = 0
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._tick)

    def set_config(self, config):
        self._config = config
        if config.mode != "pair":
            self._pairs.clear()
            self._shown = False

    def busy(self):
        """Pair mode: a pair is on screen or waiting."""
        return self._shown or bool(self._pairs)

    def clear(self):
        self._pending.clear()
        self._pairs.clear()
        self._shown = False
        self._timer.stop()

    def _tick(self):
        if self._config.mode == "pair":
            self._show_next()
        else:
            self._shown = False
            self._pump()

    def on_committed(self, text):
        c = self._config
        chunks = split_chunks(text, c.min_words, c.max_words, c.random_size, self._rng)
        if c.mode == "pair":
            self._queue_pairs(chunks)
            return
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

    def _queue_pairs(self, chunks):
        if not self._server.client_ids():
            return   # nobody to pair with: the host shows the full caption itself
        self._phrase += 1
        for i in range(0, len(chunks), 2):
            self._pairs.append((self._phrase, chunks[i], chunks[i + 1] if i + 1 < len(chunks) else ""))
        # Over the cap: drop whole older phrases, oldest first; the phrase just queued is never trimmed.
        while len(self._pairs) > MAX_PENDING_PAIRS and self._pairs[0][0] != self._phrase:
            old = self._pairs[0][0]
            while self._pairs and self._pairs[0][0] == old:
                self._pairs.popleft()
        if not self._timer.isActive():
            self._show_next()

    def _show_next(self):
        remote = self._server.client_ids()
        if not self._pairs or not remote:
            self._pairs.clear()
            if self._shown:
                self._shown = False
                self.host_clear.emit()
                self._server.broadcast({"type": "clear"})
            return
        _, left, right = self._pairs.popleft()
        hold = min(self._hold_ms, max(PAIR_MIN_MS, PAIR_BASE_MS + PAIR_WORD_MS * len((left + " " + right).split())))
        self._shown = True
        self.chunk_for_host.emit(left)
        self.chunk_sent.emit(HOST, left)
        target = remote[-1]   # newest join wins: a reconnect beats its half-open predecessor
        if right:
            self._seq += 1
            msg = {"type": "caption", "id": target, "seq": self._seq, "text": right,
                   "hold_ms": hold + PAGE_GRACE_MS}
            if self._server.send_to(target, msg):
                self.chunk_sent.emit(target, right)
            else:
                self._server.send_to(target, {"type": "clear"})   # don't leave an old chunk up
        else:
            self._server.send_to(target, {"type": "clear"})   # odd tail: right screen goes blank
        self._timer.start(hold)

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
