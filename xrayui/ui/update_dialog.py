"""The one screen a user sees to move to a new version.

Three states in one dialog, because an update is one errand and bouncing
between windows for it is how people end up on an old build: what is new ->
downloading -> ready to restart. The download runs off the UI thread and can
be called off at any point; nothing on disk changes until it has arrived
whole and matched the checksum published with the release.

Builds that cannot replace themselves (a source checkout, the macOS .app)
get the same dialog with the release page as the button instead, so the
answer to "there is an update" is never just a version number.
"""
from __future__ import annotations

import re
import threading

from PySide6.QtCore import Qt, QThreadPool, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QTextCursor
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
)

from .. import __version__, i18n
from ..core import desktop, release_notes
from ..core import updates as updates_mod
from ..i18n import ltr, tr
from .workers import Worker

# Qt's rich text subset: no blue underline on links, air between bullets.
_NOTES_CSS = """
body { line-height: 140%; }
h1, h2 { font-size: 15pt; margin-top: 14px; margin-bottom: 4px; }
h3, h4 { font-size: 12pt; margin-top: 12px; margin-bottom: 4px; }
li { margin-bottom: 6px; }
p { margin-top: 4px; margin-bottom: 6px; }
a { text-decoration: none; }
"""




def _mb(count: int) -> str:
    return f"{count / (1024 * 1024):.1f} MB"


class UpdateDialog(QDialog):
    """Ask, download, install. `release` is a core.updates.Release."""

    # Emitted from the download thread; Qt hands it to the UI thread for us.
    progressed = Signal(int, int)

    def __init__(self, release, parent=None) -> None:
        super().__init__(parent)
        self._release = release
        self._asset = updates_mod.asset_for_this_build(release)
        self._cancel = threading.Event()
        self._downloaded = None
        self._pool = QThreadPool.globalInstance()
        self._worker = None
        self.setWindowTitle(tr("Update sushTun"))
        self.resize(520, 460)
        self._build_ui()
        self.progressed.connect(self._on_progress)

    # -- construction ------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 14)
        layout.setSpacing(10)

        heading = QLabel(tr("sushTun {tag} is available", tag=ltr(self._release.tag)))
        heading.setObjectName("H1")
        heading.setWordWrap(True)
        layout.addWidget(heading)

        self.subtitle = QLabel(tr("You have version {version}.",
                                  version=ltr(__version__)))
        self.subtitle.setObjectName("Muted")
        self.subtitle.setWordWrap(True)
        layout.addWidget(self.subtitle)

        self.notes = QTextBrowser()
        # Not setOpenExternalLinks: that hands the link to Qt, which cannot
        # reach the user's browser from this elevated process (core/desktop.py).
        self.notes.setOpenExternalLinks(False)
        self.notes.anchorClicked.connect(lambda link: self._open(link.toString()))
        self._show_notes()
        self.notes.setAccessibleName(tr("What's new"))
        layout.addWidget(self.notes, 1)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setVisible(False)
        self.progress.setAccessibleName(tr("Download progress"))
        layout.addWidget(self.progress)

        self.status = QLabel("")
        self.status.setObjectName("Muted")
        self.status.setWordWrap(True)
        # A link this dialog could not open is shown here instead, and a URL
        # is only useful if it can be selected and copied.
        self.status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.status.setVisible(False)
        layout.addWidget(self.status)

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addStretch(1)
        self.btn_secondary = QPushButton(tr("Later"))
        self.btn_secondary.setAutoDefault(False)
        self.btn_secondary.clicked.connect(self._on_secondary)
        row.addWidget(self.btn_secondary)
        self.btn_primary = QPushButton()
        self.btn_primary.setDefault(True)
        self.btn_primary.clicked.connect(self._on_primary)
        row.addWidget(self.btn_primary)
        layout.addLayout(row)

        if self._asset:
            self.btn_primary.setText(tr("Download and install"))
        else:
            # Nothing here can be installed in place, so the honest primary
            # action is the download page rather than a button that explains
            # itself only after being pressed.
            self.btn_primary.setText(tr("Open the download page"))
            self.subtitle.setText(self._why_not_automatic())

    def _show_notes(self) -> None:
        lang = i18n.current()
        text = release_notes.clean(release_notes.pick_language(self._release.notes, lang))
        rtl = lang == "fa"
        self.notes.setLayoutDirection(Qt.RightToLeft if rtl else Qt.LeftToRight)
        self.notes.document().setDefaultStyleSheet(_NOTES_CSS)
        if rtl and text:
            # Markdown lists lay their bullets out left-to-right in Qt whatever
            # the block direction; plain paragraphs lead with the bullet instead.
            text = re.sub(r"^[-*+] ", "\n\u2022 ", release_notes.isolate_latin(text),
                          flags=re.M)
        self.notes.setMarkdown(text or tr("No release notes."))
        if rtl:
            self._right_to_left_blocks()
        option = self.notes.document().defaultTextOption()
        option.setTextDirection(Qt.RightToLeft if rtl else Qt.LeftToRight)
        option.setAlignment(Qt.AlignRight if rtl else Qt.AlignLeft)
        self.notes.document().setDefaultTextOption(option)

    def _right_to_left_blocks(self) -> None:
        """Bullets sit on the side the block's own direction says, and Qt
        takes that from the first strong character -- a Latin word first would
        put the bullet mid-line."""
        doc = self.notes.document()
        cursor = QTextCursor(doc)
        cursor.beginEditBlock()
        block = doc.begin()
        while block.isValid():
            cursor.setPosition(block.position())
            fmt = block.blockFormat()
            fmt.setLayoutDirection(Qt.RightToLeft)
            fmt.setAlignment(Qt.AlignRight)
            cursor.setBlockFormat(fmt)
            block = block.next()
        cursor.endEditBlock()

    def _why_not_automatic(self) -> str:
        return tr("This copy can't update itself. Download {version} and replace "
                  "it by hand.", version=ltr(self._release.version))

    # -- state -------------------------------------------------------------

    def _set_busy(self, busy: bool) -> None:
        self.btn_primary.setEnabled(not busy)
        self.progress.setVisible(busy)
        self.status.setVisible(busy or bool(self.status.text()))

    def _on_secondary(self) -> None:
        """Later, or Cancel while a download is running."""
        if self._worker is not None:
            self._cancel.set()
            self.status.setText(tr("Stopping…"))
            return
        self.reject()

    def _open(self, url: str) -> bool:
        """Open a link, from a process the desktop will not talk to.

        Elevated on Linux, Qt reaches neither the portal nor xdg-open, and its
        failure is silent -- the button looked dead. Try the user's own session
        first, and when nothing works say so instead of closing on a no-op.
        """
        if desktop.open_url(url) or QDesktopServices.openUrl(QUrl(url)):
            return True
        self.status.setText(tr("Couldn't open a browser. The page is {url}",
                               url=ltr(url)))
        self.status.setVisible(True)
        return False

    def _on_primary(self) -> None:
        if not self._asset:
            if self._open(self._release.url):
                self.accept()
            return
        if self._downloaded is not None:
            self._install()
            return
        self._start_download()

    # -- downloading -------------------------------------------------------

    def _start_download(self) -> None:
        self._cancel.clear()
        self._set_busy(True)
        self.progress.setValue(0)
        self.status.setText(tr("Downloading {name}…", name=ltr(self._asset)))
        self.btn_secondary.setText(tr("Cancel"))

        def work():
            return updates_mod.download(
                self._release,
                on_progress=lambda done, total: self.progressed.emit(done, total),
                cancelled=self._cancel.is_set)

        worker = Worker(work)
        worker.signals.finished.connect(lambda path: self._on_downloaded(path=path))
        worker.signals.error.connect(lambda msg: self._on_downloaded(error=msg))
        self._worker = worker
        self._pool.start(worker)

    def _on_progress(self, done: int, total: int) -> None:
        if total > 0:
            self.progress.setRange(0, 100)
            self.progress.setValue(int(done * 100 / total))
            self.status.setText(tr("Downloaded {done} of {total}",
                                   done=ltr(_mb(done)), total=ltr(_mb(total))))
        else:
            # No Content-Length: a moving bar still says "this is working".
            self.progress.setRange(0, 0)
            self.status.setText(tr("Downloaded {done}", done=ltr(_mb(done))))

    def _on_downloaded(self, path=None, error=None) -> None:
        self._worker = None
        self.btn_secondary.setText(tr("Later"))
        self._set_busy(False)
        self.progress.setVisible(False)
        if error or path is None:
            self.status.setVisible(True)
            self.status.setText(
                tr("Update cancelled.") if self._cancel.is_set()
                else tr("Update failed: {error}", error=error or tr("unknown error")))
            self.btn_primary.setText(tr("Try again"))
            return
        self._downloaded = path
        self.status.setVisible(True)
        self.status.setText(tr("Downloaded and checked. sushTun will close to finish."))
        self.btn_primary.setText(tr("Restart and install"))
        self.btn_primary.setFocus()

    # -- installing --------------------------------------------------------

    def _install(self) -> None:
        self._set_busy(True)
        self.status.setVisible(True)
        self.status.setText(tr("Installing…"))
        try:
            updates_mod.install(self._downloaded)
        except updates_mod.UpdateError as exc:
            self._set_busy(False)
            self.status.setText(tr("Update failed: {error}", error=str(exc)))
            self.btn_primary.setText(tr("Try again"))
            self._downloaded = None
            return
        self.accept()  # the caller disconnects, then quits

    def installed(self) -> bool:
        """True once install() has run and the app has to quit to finish."""
        return self.result() == QDialog.Accepted and self._downloaded is not None

    def relaunches_itself(self) -> bool:
        """The Windows installer restarts sushTun; a replaced executable does not."""
        return updates_mod.installed_windows()

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt's name)
        self._cancel.set()
        super().closeEvent(event)


def run_update_flow(release, parent=None) -> bool:
    """Show the update dialog and do what it decided.

    Returns True when the new version is in place and the app must now quit:
    quitting is what hands over to it, and on the portable builds it is also
    what puts the network back before anything else touches it."""
    dlg = UpdateDialog(release, parent)
    dlg.exec()
    if not dlg.installed():
        return False
    if not dlg.relaunches_itself():
        updates_mod.relaunch_after_exit()
    return True
