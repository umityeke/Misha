import sys
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QLineEdit, QPushButton, QHBoxLayout, QApplication
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from core.pin_security import is_pin_set, verify_pin, set_pin

class C:
    BG        = "#050810"
    PANEL     = "#0B1220"
    PANEL_HI  = "#152238"
    BORDER    = "#243753"
    PRI       = "#63E6E2"
    RED       = "#FF6B81"
    TEXT      = "#C9D7EA"
    DIM       = "#687993"
    WHITE     = "#F4F8FF"

class PinDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Misha Security")
        self.setAccessibleName("Misha security PIN")
        self.setFixedSize(380, 500)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setStyleSheet(
            f"background-color: {C.BG}; border: 1px solid {C.BORDER}; border-radius: 18px;"
        )

        self.is_setup_mode = not is_pin_set()
        self.attempts = 0
        self.max_attempts = 3

        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(34, 30, 34, 26)
        layout.setSpacing(12)

        mark = QLabel("M")
        mark.setFixedSize(56, 56)
        mark.setFont(QFont("Avenir Next", 21, QFont.Weight.Bold))
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark.setStyleSheet(
            f"color: {C.BG}; background: {C.PRI}; border: none; border-radius: 28px;"
        )
        mark_row = QHBoxLayout(); mark_row.addStretch(); mark_row.addWidget(mark); mark_row.addStretch()
        layout.addLayout(mark_row)

        title_lbl = QLabel("Create your access PIN" if self.is_setup_mode else "Welcome back")
        title_lbl.setFont(QFont("Avenir Next", 19, QFont.Weight.DemiBold))
        title_lbl.setStyleSheet(f"color: {C.WHITE}; border: none;")
        title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_lbl)

        # Subtitle
        self.sub_lbl = QLabel(
            "Enter your four-digit PIN to unlock Misha."
            if not self.is_setup_mode else
            "Choose a four-digit PIN. It will be protected locally."
        )
        self.sub_lbl.setFont(QFont("Avenir Next", 10))
        self.sub_lbl.setStyleSheet(f"color: {C.DIM}; border: none;")
        self.sub_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.sub_lbl.setWordWrap(True)
        layout.addWidget(self.sub_lbl)

        # PIN Input
        self.pin_input = QLineEdit()
        self.pin_input.setAccessibleName("Four digit Misha PIN")
        self.pin_input.setAccessibleDescription("Digits are hidden while you type")
        self.pin_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.pin_input.setMaxLength(4)
        self.pin_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pin_input.setFont(QFont("Avenir Next", 24, QFont.Weight.DemiBold))
        self.pin_input.setFixedHeight(58)
        self.pin_input.setStyleSheet(f"""
            QLineEdit {{
                background-color: {C.PANEL};
                color: {C.WHITE};
                border: 1px solid {C.BORDER};
                border-radius: 12px;
                padding: 8px;
                letter-spacing: 15px;
            }}
            QLineEdit:focus {{
                border: 1px solid {C.PRI};
            }}
        """)
        self.pin_input.textChanged.connect(self._on_text_changed)
        layout.addWidget(self.pin_input)

        # Keypad (Optional, but good for UI)
        grid = QVBoxLayout()
        buttons = [
            ["1", "2", "3"],
            ["4", "5", "6"],
            ["7", "8", "9"],
            ["C", "0", "OK"]
        ]

        for row in buttons:
            h_layout = QHBoxLayout()
            h_layout.setSpacing(10)
            for btn_text in row:
                btn = QPushButton(btn_text)
                btn.setAccessibleName(
                    "Clear PIN" if btn_text == "C" else
                    "Submit PIN" if btn_text == "OK" else
                    f"PIN digit {btn_text}"
                )
                btn.setFixedSize(78, 46)
                btn.setFont(QFont("Avenir Next", 13, QFont.Weight.DemiBold))

                bg_color = "#25131B" if btn_text == "C" else (C.PRI if btn_text == "OK" else C.PANEL)
                text_color = C.RED if btn_text == "C" else (C.BG if btn_text == "OK" else C.TEXT)

                btn.setStyleSheet(f"""
                    QPushButton {{
                        background-color: {bg_color};
                        color: {text_color};
                        border: 1px solid {C.BORDER};
                        border-radius: 11px;
                    }}
                    QPushButton:pressed {{
                        background-color: {C.PANEL_HI};
                    }}
                """)

                btn.clicked.connect(lambda checked, t=btn_text: self._on_keypad(t))
                h_layout.addWidget(btn)
            grid.addLayout(h_layout)

        layout.addLayout(grid)
        layout.addStretch()

        secure = QLabel("Protected with PBKDF2  ·  Local access only")
        secure.setFont(QFont("Avenir Next", 8))
        secure.setAlignment(Qt.AlignmentFlag.AlignCenter)
        secure.setStyleSheet(f"color: {C.DIM}; border: none;")
        layout.addWidget(secure)

    def _on_keypad(self, key: str):
        if key == "C":
            self.pin_input.clear()
        elif key == "OK":
            self._verify()
        else:
            if len(self.pin_input.text()) < 4:
                self.pin_input.setText(self.pin_input.text() + key)

    def _on_text_changed(self, text):
        if len(text) == 4:
            self._verify()

    def _verify(self):
        pin = self.pin_input.text()
        if len(pin) != 4 or not pin.isdigit():
            self._show_error("PIN 4 haneli bir sayı olmalıdır.")
            self.pin_input.clear()
            return

        if self.is_setup_mode:
            if set_pin(pin):
                self.accept() # PIN configured successfully
            else:
                self._show_error("PIN güvenli biçimde kaydedilemedi.")
                self.pin_input.clear()
        else:
            if verify_pin(pin):
                self.accept() # Success
            else:
                self.attempts += 1
                rem = self.max_attempts - self.attempts
                if rem <= 0:
                    self._show_error("Çok fazla hatalı giriş! Sistem kilitlendi.")
                    sys.exit(0)
                else:
                    self._show_error(f"Hatalı PIN! Kalan hakkınız: {rem}")
                    self.pin_input.clear()

    def _show_error(self, msg: str):
        self.sub_lbl.setText(msg)
        self.sub_lbl.setStyleSheet(f"color: {C.RED}; border: none;")

def require_pin():
    """Runs the PIN dialog. Returns True if authorized, False otherwise (or exits)."""
    app = QApplication.instance()
    is_temp_app = False
    if not app:
        app = QApplication(sys.argv)
        is_temp_app = True

    dialog = PinDialog()
    result = dialog.exec()

    if result != QDialog.DialogCode.Accepted:
        sys.exit(0)

    if is_temp_app:
        # If we created a temp app, we shouldn't quit it completely since the main app needs it,
        # but Qt allows reusing the instance.
        pass

    return True
