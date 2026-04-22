"""
Journal overlay — runs as its own process.
Usage: python _journal_overlay.py <journal_path>
"""
import sys, pathlib

journal_path = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else (
    pathlib.Path(__file__).parent.parent.parent.parent / "data" / "next_step.txt"
)

try:
    from PyQt6.QtWidgets import (QApplication, QLineEdit, QWidget,
                                  QVBoxLayout, QLabel)
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QFont

    app = QApplication(sys.argv)

    class JournalOverlay(QWidget):
        def __init__(self):
            super().__init__()
            self.setWindowFlags(
                Qt.WindowType.FramelessWindowHint |
                Qt.WindowType.WindowStaysOnTopHint |
                Qt.WindowType.Tool,
            )
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            self.setFixedWidth(540)

            outer = QVBoxLayout(self)
            outer.setContentsMargins(0, 0, 0, 0)

            container = QWidget()
            container.setObjectName("container")
            container.setStyleSheet("""
                #container {
                    background: #111116;
                    border: 1px solid #333340;
                    border-radius: 12px;
                }
            """)
            outer.addWidget(container)

            inner = QVBoxLayout(container)
            inner.setContentsMargins(16, 12, 16, 14)
            inner.setSpacing(6)

            hint = QLabel("\U0001f4dd  What\u2019s your next step?")
            hint.setStyleSheet("color: #666680; font-size: 11px;")
            hint.setFont(QFont("Segoe UI", 9))
            inner.addWidget(hint)

            self.inp = QLineEdit()
            self.inp.setPlaceholderText("Type one line \u2192 Enter to save  \u00b7  Esc to cancel")
            self.inp.setFont(QFont("Segoe UI", 13))
            self.inp.setStyleSheet("""
                QLineEdit {
                    background: #1a1a22;
                    color: #e8e8f0;
                    border: 1px solid #2a2a38;
                    border-radius: 8px;
                    padding: 10px 14px;
                    selection-background-color: #4e9eff44;
                }
                QLineEdit:focus { border-color: #4e9eff; }
            """)
            self.inp.returnPressed.connect(self._save_and_close)
            inner.addWidget(self.inp)

            screen = app.primaryScreen().geometry()
            self.adjustSize()
            self.move(screen.center().x() - self.width() // 2, 80)

        def keyPressEvent(self, e):
            if e.key() == Qt.Key.Key_Escape:
                self.close()
            else:
                super().keyPressEvent(e)

        def _save_and_close(self):
            text = self.inp.text().strip()
            if text:
                journal_path.parent.mkdir(parents=True, exist_ok=True)
                journal_path.write_text(text, encoding="utf-8")
            self.close()
            app.quit()

    w = JournalOverlay()
    w.show()
    w.inp.setFocus()
    w.activateWindow()
    sys.exit(app.exec())
except Exception:
    sys.exit(1)
