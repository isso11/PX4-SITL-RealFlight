"""Bidirectional MAVLink UDP relay for Windows QGC across WSL2 NAT."""
import selectors
import socket
import threading


class UdpRelay:
    def __init__(self, target, listen=("0.0.0.0", 14550)):
        self.selector = selectors.DefaultSelector()
        self.local = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.remote = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self.local.bind(listen)
            self.remote.connect(target)
            self.selector.register(self.local, selectors.EVENT_READ, "px4")
            self.selector.register(self.remote, selectors.EVENT_READ, "qgc")
        except Exception:
            self.local.close()
            self.remote.close()
            self.selector.close()
            raise
        self.address = self.local.getsockname()
        self.peer = None
        self.to_qgc = 0
        self.to_px4 = 0
        self.errors = 0
        self.stopping = threading.Event()
        self.thread = None

    def start(self):
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        return self

    def _run(self):
        while not self.stopping.is_set():
            for key, _ in self.selector.select(timeout=0.2):
                try:
                    data, sender = key.fileobj.recvfrom(65535)
                    if key.data == "px4":
                        self.peer = sender
                        self.remote.send(data)
                        self.to_qgc += 1
                    elif self.peer is not None:
                        self.local.sendto(data, self.peer)
                        self.to_px4 += 1
                except OSError:
                    # UDP ICMP errors (e.g. QGC not open yet) must not kill the relay.
                    self.errors += 1

    def close(self):
        self.stopping.set()
        if self.thread:
            self.thread.join(timeout=2)
        self.selector.close()
        self.local.close()
        self.remote.close()
