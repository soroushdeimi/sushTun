"""One sushTun per machine: a second launch shows the running window instead of starting another copy.

Two copies share one state directory, one TUN and one resolver, so a second
copy that quits runs the first one's teardown and cuts its tunnel. Each extra
launch also asked for the admin password again, then sat hidden in the tray.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

# One fixed name for every user: the elevated copy (root) listens and the
# user's own unelevated launch knocks, and there is only one tunnel to own anyway.
NAME = "sushtun-single-instance"
_SHOW = b"show\n"


def notify_running(show: bool = True, name: str = NAME) -> bool:
    """True if a copy is already running; asks it to show its window unless
    show is False. Works before any QApplication exists."""
    sock = QLocalSocket()
    sock.connectToServer(name)
    if not sock.waitForConnected(500):
        return False
    if show:
        sock.write(_SHOW)
        sock.waitForBytesWritten(500)
    sock.disconnectFromServer()
    return True


class InstanceServer(QObject):
    show_requested = Signal()

    def __init__(self, name: str = NAME, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._server = QLocalServer(self)
        # The listener runs as root; the user's own launch must still get in.
        self._server.setSocketOptions(QLocalServer.WorldAccessOption)
        if not self._server.listen(name):
            # A crash leaves the socket file behind; nobody answered on it
            # (notify_running ran first), so it is stale.
            QLocalServer.removeServer(name)
            self._server.listen(name)
        self._server.newConnection.connect(self._accept)

    def is_listening(self) -> bool:
        return self._server.isListening()

    def _accept(self) -> None:
        while (sock := self._server.nextPendingConnection()) is not None:
            # No deleteLater: the lambda keeps a Python reference, and Qt
            # freeing the socket under it crashed. The server owns it; one tiny
            # object per launch is fine.
            sock.readyRead.connect(lambda s=sock: self._read(s))
            if sock.bytesAvailable():
                self._read(sock)

    def _read(self, sock: QLocalSocket) -> None:
        if bytes(sock.readAll().data()).startswith(_SHOW.strip()):
            self.show_requested.emit()
