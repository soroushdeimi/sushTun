"""One sushTun per machine: a second launch shows the running window and exits.

Two copies share one state directory, one TUN and one resolver, so a second
copy that quits runs the first one's teardown and cuts its tunnel. Each extra
launch also asked for the admin password again, then sat hidden in the tray.

The handover used to be blind: any build answering on the socket got the
window, so opening a freshly installed version while an older one was still
running raised the *older* window and the new launch vanished. Settings then
showed the old version number and nothing said why -- and with a login item
pointing at the old copy, the new one could never get a turn to fix it. The
listener therefore advertises which version it is, and a launch that finds a
different one says so instead of disappearing.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from .. import __version__, paths

# One fixed name for every user: the elevated copy (root) listens and the
# user's unelevated launch knocks, and there is only one tunnel to own anyway.
NAME = "sushtun-single-instance"
_SHOW = b"show\n"


# Written by the listener next to the rest of the state, read by every later
# launch. A build older than this one writes none, which reads as "unknown".
IDENTITY = "instance.json"


@dataclass(frozen=True)
class Instance:
    """The copy that is already running, as it advertised itself."""

    version: str
    exe: str
    pid: int

    @property
    def is_this_build(self) -> bool:
        return self.version == __version__


def identity_path() -> Path:
    return paths.state_dir() / IDENTITY


def advertise() -> None:
    """Record who is listening. Best effort: failing to write it only costs
    a later launch the version in its message."""
    try:
        identity_path().parent.mkdir(parents=True, exist_ok=True)
        identity_path().write_text(json.dumps({
            "version": __version__, "exe": sys.executable, "pid": os.getpid(),
        }), encoding="utf-8")
    except OSError:
        pass


def withdraw() -> None:
    try:
        identity_path().unlink(missing_ok=True)
    except OSError:
        pass


def _alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # running as root, which is exactly what we expect
    except (OSError, AttributeError):
        return True  # Windows has no signal 0; assume the listener is real
    return True


def running_instance() -> Instance | None:
    """The advertised identity of the copy that is running, or None when there
    is none to read -- a crashed leftover, or a build too old to write one."""
    try:
        data = json.loads(identity_path().read_text(encoding="utf-8"))
        pid = int(data["pid"])
        version, exe = str(data["version"]), str(data.get("exe", ""))
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return Instance(version, exe, pid) if _alive(pid) else None


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


def hand_over(show: bool = True, name: str = NAME) -> bool:
    """True when a copy is already running and this launch must stop.

    Stopping silently is right only when the window that comes up is this same
    build. When it is a different one, nothing on screen would tell the user
    which version they are looking at, so say it.
    """
    if not notify_running(show=show, name=name):
        return False
    other = running_instance()
    # A login launch raises no window and must never pop a dialog behind one.
    if show and (other is None or not other.is_this_build):
        _warn_other_build(other)
    return True


def _warn_other_build(other: Instance | None) -> None:
    from PySide6.QtWidgets import QApplication, QMessageBox

    from .. import i18n
    from ..core import settings as app_settings
    from ..i18n import ltr, tr

    # Nothing has set the language yet: this runs before ui.app.run.
    try:
        i18n.set_language(app_settings.load().get("language", "en"))
    except Exception:  # a broken settings file must not cost the message
        pass
    app = QApplication.instance() or QApplication([])
    if other is None:
        text = tr("You opened sushTun {this}, but another copy is already running — the "
                  "window on screen is that one. Quit it first, then open this copy again.",
                  this=ltr(__version__))
    else:
        text = tr("You opened sushTun {this}, but sushTun {running} is already running — the "
                  "window on screen is that one. Quit it first, then open this copy again.",
                  this=ltr(__version__), running=ltr(other.version))
    QMessageBox.information(None, "sushTun", text)
    app.processEvents()


class InstanceServer(QObject):
    """Listens for later launches and emits show_requested for each one."""

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
        if self._server.isListening():
            advertise()
            self.destroyed.connect(lambda *_: withdraw())

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
