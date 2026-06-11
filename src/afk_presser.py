"""AFK Key Presser — a small PyQt5 desktop app.

Pick a key, set how fast/often to tap it, then Start. Pressing is driven by
``presser_engine.KeyPresser`` (validated input, no CPU spin, crash-safe). A
global hotkey (Ctrl+Shift+Alt) toggles pressing so you can start it after
switching to the target window.

Run with:  python afk_presser.py
"""

from __future__ import annotations

import sys

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QApplication,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from pynput import keyboard

from presser_engine import (
    InvalidKeyError,
    KeyPresser,
    available_special_keys,
    parse_key,
)

TOGGLE_HOTKEY = "<ctrl>+<shift>+<alt>"
TOGGLE_HOTKEY_LABEL = "Ctrl+Shift+Alt"

# Default timing values (seconds). Used both to seed the spin boxes and to
# restore them when the "Default" button is clicked.
DEFAULT_HOLD_MIN = 0.05
DEFAULT_HOLD_MAX = 0.12
DEFAULT_GAP_MIN = 0.5
DEFAULT_GAP_MAX = 2.0

# Qt special keys -> the names presser_engine understands.
_QT_KEY_NAMES = {
    Qt.Key_Space: "space",
    Qt.Key_Return: "enter",
    Qt.Key_Enter: "enter",
    Qt.Key_Tab: "tab",
    Qt.Key_Escape: "esc",
    Qt.Key_Backspace: "backspace",
    Qt.Key_Delete: "delete",
    Qt.Key_Insert: "insert",
    Qt.Key_Home: "home",
    Qt.Key_End: "end",
    Qt.Key_PageUp: "pageup",
    Qt.Key_PageDown: "pagedown",
    Qt.Key_Up: "up",
    Qt.Key_Down: "down",
    Qt.Key_Left: "left",
    Qt.Key_Right: "right",
}
for _n in range(1, 25):
    _qk = getattr(Qt, f"Key_F{_n}", None)
    if _qk is not None:
        _QT_KEY_NAMES[_qk] = f"f{_n}"


STYLESHEET = """
QMainWindow, QWidget { background-color: #1e1f26; color: #e6e6eb; }
QLabel#title { font-size: 20px; font-weight: 600; color: #ffffff; }
QLabel#hint { color: #9aa0ad; font-size: 11px; }
QGroupBox {
    border: 1px solid #33353f; border-radius: 8px;
    margin-top: 10px; padding: 12px; font-weight: 600;
}
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: #b9c0cf; }
QLineEdit, QComboBox, QDoubleSpinBox {
    background-color: #2a2c36; border: 1px solid #3a3d49;
    border-radius: 6px; padding: 6px 8px; color: #e6e6eb; selection-background-color: #5a6cff;
}
QLineEdit:focus, QComboBox:focus, QDoubleSpinBox:focus { border: 1px solid #5a6cff; }
QComboBox::drop-down { border: none; }
QPushButton {
    background-color: #2a2c36; border: 1px solid #3a3d49;
    border-radius: 6px; padding: 7px 14px; color: #e6e6eb;
}
QPushButton:hover { background-color: #343744; }
QPushButton#primary { background-color: #3bb273; border: none; font-weight: 600; font-size: 14px; padding: 11px; }
QPushButton#primary:hover { background-color: #44c882; }
QPushButton#primary[running="true"] { background-color: #d9534f; }
QPushButton#primary[running="true"]:hover { background-color: #e2625e; }
"""


class MainWindow(QMainWindow):
    # Engine and hotkey callbacks fire on background threads; these signals
    # marshal them back onto the GUI thread.
    stateChanged = pyqtSignal(str)
    errorOccurred = pyqtSignal(str)
    hotkeyToggled = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("AFK Key Presser")
        self.setMinimumWidth(420)

        self._capturing = False
        self._engine = KeyPresser(
            on_state_change=self.stateChanged.emit,
            on_error=self.errorOccurred.emit,
        )

        self._build_ui()
        self.stateChanged.connect(self._on_state_change)
        self.errorOccurred.connect(self._on_error)
        self.hotkeyToggled.connect(self._on_toggle_clicked)

        self._hotkeys = keyboard.GlobalHotKeys({TOGGLE_HOTKEY: self.hotkeyToggled.emit})
        self._hotkeys.start()

        self._apply_timing()  # push initial spinbox values to the engine

    # -- UI construction ---------------------------------------------------
    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)

        title = QLabel("AFK Key Presser")
        title.setObjectName("title")
        root.addWidget(title)

        # --- Key selection ---
        key_box = QGroupBox("Key")
        key_form = QFormLayout(key_box)
        key_row = QHBoxLayout()
        self.key_edit = QLineEdit("a")
        # Read-only so a stray keystroke (including the presser's own, if this
        # window is focused while running) can't silently change the key.
        # Set it via the Capture… button or the Special list instead.
        self.key_edit.setReadOnly(True)
        self.key_edit.setPlaceholderText("use Capture… or the Special list")
        self.key_edit.setToolTip(
            "Read-only — set the key with Capture… or the Special list "
            "so it can't be changed by accident."
        )
        self.capture_btn = QPushButton("Capture…")
        self.capture_btn.setToolTip("Click, then press any key to capture it.")
        self.capture_btn.clicked.connect(self._start_capture)
        key_row.addWidget(self.key_edit)
        key_row.addWidget(self.capture_btn)
        key_form.addRow("Press key:", key_row)

        self.special_combo = QComboBox()
        self.special_combo.addItem("— pick a special key —", "")
        for name in available_special_keys():
            self.special_combo.addItem(name, name)
        self.special_combo.currentIndexChanged.connect(self._on_special_picked)
        key_form.addRow("Special:", self.special_combo)
        root.addWidget(key_box)

        # --- Timing ---
        timing_box = QGroupBox("Timing (seconds)")
        timing_form = QFormLayout(timing_box)
        self.hold_min = self._make_spin(DEFAULT_HOLD_MIN)
        self.hold_max = self._make_spin(DEFAULT_HOLD_MAX)
        self.gap_min = self._make_spin(DEFAULT_GAP_MIN)
        self.gap_max = self._make_spin(DEFAULT_GAP_MAX)
        timing_form.addRow("Hold min / max:", self._pair(self.hold_min, self.hold_max))
        timing_form.addRow("Interval min / max:", self._pair(self.gap_min, self.gap_max))

        self.reset_btn = QPushButton("Default")
        self.reset_btn.setToolTip("Reset the timing fields to their default values.")
        self.reset_btn.clicked.connect(self._reset_timing)
        reset_row = QHBoxLayout()
        reset_row.setContentsMargins(0, 0, 0, 0)
        reset_row.addStretch(1)
        reset_row.addWidget(self.reset_btn)
        reset_wrap = QWidget()
        reset_wrap.setLayout(reset_row)
        timing_form.addRow(reset_wrap)
        root.addWidget(timing_box)

        # --- Start / status ---
        self.toggle_btn = QPushButton("Start")
        self.toggle_btn.setObjectName("primary")
        self.toggle_btn.setProperty("running", "false")
        self.toggle_btn.clicked.connect(self._on_toggle_clicked)
        root.addWidget(self.toggle_btn)

        self.status_label = QLabel("● Idle")
        self.status_label.setStyleSheet("color: #9aa0ad;")
        self.status_label.setAlignment(Qt.AlignCenter)
        root.addWidget(self.status_label)

        hint = QLabel(
            f"Global hotkey {TOGGLE_HOTKEY_LABEL} toggles pressing.\n"
            "Switch to your target window first — keys go to whatever is focused."
        )
        hint.setObjectName("hint")
        hint.setAlignment(Qt.AlignCenter)
        hint.setWordWrap(True)
        root.addWidget(hint)

        self.setCentralWidget(central)

    def _make_spin(self, value: float) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(0.0, 60.0)
        spin.setSingleStep(0.05)
        spin.setDecimals(2)
        # Make only the embedded line edit read-only (not the whole spin box):
        # this blocks keyboard typing so a stray keystroke can't change the
        # timing, while the arrow buttons, arrow keys, and scroll wheel keep
        # working. (spin.setReadOnly(True) would also disable stepping.)
        spin.lineEdit().setReadOnly(True)
        spin.setToolTip("Adjust with the arrow buttons or scroll wheel.")
        spin.setValue(value)
        spin.valueChanged.connect(self._apply_timing)
        return spin

    @staticmethod
    def _pair(a: QWidget, b: QWidget) -> QWidget:
        wrap = QWidget()
        row = QHBoxLayout(wrap)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(a)
        row.addWidget(b)
        return wrap

    # -- key capture -------------------------------------------------------
    def _start_capture(self) -> None:
        self._capturing = True
        self.capture_btn.setText("Press any key…")
        self.setFocus()

    def keyPressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if not self._capturing:
            super().keyPressEvent(event)
            return
        name = _QT_KEY_NAMES.get(event.key())
        if name is None:
            text = event.text()
            name = text if len(text) == 1 and text.isprintable() else None
        if name:
            self.key_edit.setText(name)
            self.special_combo.setCurrentIndex(0)
        self._capturing = False
        self.capture_btn.setText("Capture…")
        event.accept()

    def _on_special_picked(self, index: int) -> None:
        value = self.special_combo.itemData(index)
        if value:
            self.key_edit.setText(value)

    # -- engine wiring -----------------------------------------------------
    def _apply_timing(self) -> None:
        self._engine.set_timing(
            self.hold_min.value(),
            self.hold_max.value(),
            self.gap_min.value(),
            self.gap_max.value(),
        )

    def _reset_timing(self) -> None:
        # Each setValue fires valueChanged -> _apply_timing, pushing the
        # restored values to the engine.
        self.hold_min.setValue(DEFAULT_HOLD_MIN)
        self.hold_max.setValue(DEFAULT_HOLD_MAX)
        self.gap_min.setValue(DEFAULT_GAP_MIN)
        self.gap_max.setValue(DEFAULT_GAP_MAX)

    def _on_toggle_clicked(self) -> None:
        if self._engine.is_running:
            self._engine.stop()
            return
        try:
            self._engine.set_key(self.key_edit.text())
        except InvalidKeyError as exc:
            self._flash_status(f"● {exc}", "#d9534f")
            return
        self._apply_timing()
        self._engine.start()

    def _on_state_change(self, state: str) -> None:
        running = state == "running"
        self.toggle_btn.setText("Stop" if running else "Start")
        self.toggle_btn.setProperty("running", "true" if running else "false")
        # Re-polish so the [running] stylesheet selector takes effect.
        self.toggle_btn.style().unpolish(self.toggle_btn)
        self.toggle_btn.style().polish(self.toggle_btn)
        if running:
            self._flash_status(f"● Pressing '{self.key_edit.text().strip()}'", "#3bb273")
        else:
            self._flash_status("● Idle", "#9aa0ad")

    def _on_error(self, message: str) -> None:
        self._flash_status(f"● {message}", "#d9534f")

    def _flash_status(self, text: str, color: str) -> None:
        self.status_label.setText(text)
        self.status_label.setStyleSheet(f"color: {color};")

    # -- shutdown ----------------------------------------------------------
    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        try:
            self._hotkeys.stop()
        except Exception:
            pass
        self._engine.shutdown()
        super().closeEvent(event)


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLESHEET)
    window = MainWindow()
    window.show()
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
