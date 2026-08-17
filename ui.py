from __future__ import annotations

import math
import platform
import random
import subprocess
import sys
import threading
import time
from pathlib import Path

import psutil  # type: ignore

from PyQt6.QtCore import (  # type: ignore
    QEvent, QObject, QPointF, QRectF, Qt, QThread, QTime, QTimer, pyqtSignal,
)
from PyQt6.QtGui import (  # type: ignore
    QAction, QBrush, QColor, QDragEnterEvent, QDropEvent, QFont, QIcon,
    QKeySequence, QLinearGradient, QPainter, QPen, QPixmap, QRadialGradient,
    QShortcut,
)
from PyQt6.QtWidgets import (  # type: ignore
    QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout,
    QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QMainWindow, QPushButton,
    QMenu, QMessageBox, QSizePolicy, QSpinBox, QStyle, QSystemTrayIcon, QTabWidget,
    QTextEdit, QTimeEdit, QVBoxLayout, QWidget,
)

def _base_dir() -> Path:
    if getattr(sys, "_MEIPASS", None):
        return Path(sys._MEIPASS)
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent

BASE_DIR = _base_dir()

_DEFAULT_W, _DEFAULT_H = 1280, 800
_MIN_W,     _MIN_H     = 1040, 680
_LEFT_W  = 220
_RIGHT_W = 360

_OS = platform.system()  # "Windows" | "Darwin" | "Linux"


class C:
    BG        = "#050810"
    BG_ALT    = "#080D18"
    PANEL     = "#0B1220"
    PANEL2    = "#101A2B"
    PANEL_HI  = "#152238"
    BORDER    = "#1C2A40"
    BORDER_B  = "#2E4564"
    BORDER_A  = "#243753"
    PRI       = "#63E6E2"
    PRI_DIM   = "#3C8F99"
    PRI_GHO   = "#102D36"
    ACC       = "#8C9EFF"
    ACC2      = "#E8B86D"
    GREEN     = "#5CE0A2"
    GREEN_D   = "#2E9D70"
    RED       = "#FF6B81"
    MUTED_C   = "#FF6B81"
    TEXT      = "#C9D7EA"
    TEXT_DIM  = "#687993"
    TEXT_MED  = "#91A5C1"
    WHITE     = "#F4F8FF"
    DARK      = "#070B13"
    BAR_BG    = "#172338"


UI_FONT = "Avenir Next"
MONO_FONT = "SF Mono"


def qcol(h: str, a: int = 255) -> QColor:
    c = QColor(h); c.setAlpha(a); return c


class _GlobalAccessibilityFilter(QObject):
    """Apply keyboard and spoken labels to every window when it becomes visible."""

    _CONTROL_TYPES = (
        QPushButton, QLineEdit, QTextEdit, QListWidget, QComboBox, QSpinBox,
        QTimeEdit, QCheckBox,
    )

    @staticmethod
    def _label(control: QWidget) -> str:
        if isinstance(control, (QPushButton, QCheckBox)):
            return " ".join(control.text().split()).strip("◉●◫⌾⛶→↑—× ")
        if isinstance(control, QLineEdit):
            return control.placeholderText().strip()
        if isinstance(control, QTextEdit):
            return control.placeholderText().strip()
        if isinstance(control, QComboBox):
            return control.currentText().strip()
        return control.objectName().replace("_", " ").strip()

    def eventFilter(self, watched, event) -> bool:
        if event.type() == QEvent.Type.Show and isinstance(watched, QWidget):
            controls = [
                control for control in watched.findChildren(QWidget)
                if isinstance(control, self._CONTROL_TYPES)
            ]
            for control in controls:
                if not control.accessibleName().strip():
                    control.setAccessibleName(
                        self._label(control) or f"Misha {control.__class__.__name__} control"
                    )
                control.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        return False

class _SysMetrics:
    def __init__(self):
        self.cpu  = 0.0
        self.mem  = 0.0
        self.net  = 0.0
        self.gpu  = -1.0
        self.tmp  = -1.0
        self._lock = threading.Lock()
        self._last_net = psutil.net_io_counters()
        self._last_net_t = time.time()
        self._running = True
        t = threading.Thread(target=self._loop, daemon=True)
        t.start()

    def _loop(self):
        while self._running:
            try:
                self._update()
            except Exception:
                pass
            time.sleep(1.5)

    def _update(self):
        cpu = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory().percent

        nc  = psutil.net_io_counters()
        now = time.time()
        dt  = now - self._last_net_t
        if dt > 0:
            sent = (nc.bytes_sent - self._last_net.bytes_sent) / dt
            recv = (nc.bytes_recv - self._last_net.bytes_recv) / dt
            net  = (sent + recv) / (1024 * 1024)
        else:
            net = 0.0
        self._last_net   = nc
        self._last_net_t = now

        gpu = self._get_gpu()

        tmp = self._get_temp()

        with self._lock:
            self.cpu = cpu
            self.mem = mem
            self.net = net
            self.gpu = gpu
            self.tmp = tmp

    def _get_gpu(self) -> float:
        # NVIDIA
        try:
            r = subprocess.run(
                ["nvidia-smi", "--query-gpu=utilization.gpu",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=2
            )
            if r.returncode == 0:
                vals = [float(v.strip()) for v in r.stdout.strip().split("\n") if v.strip()]
                if vals:
                    return sum(vals) / len(vals)
        except Exception:
            pass

        # AMD (Linux)
        if _OS == "Linux":
            try:
                r = subprocess.run(
                    ["rocm-smi", "--showuse", "--csv"],
                    capture_output=True, text=True, timeout=2
                )
                if r.returncode == 0:
                    for line in r.stdout.strip().split("\n"):
                        parts = line.split(",")
                        if len(parts) >= 2:
                            try:
                                return float(parts[1].strip().replace("%", ""))
                            except ValueError:
                                pass
            except Exception:
                pass

            # Intel GPU (Linux)
            try:
                r = subprocess.run(
                    ["intel_gpu_top", "-J", "-s", "500"],
                    capture_output=True, text=True, timeout=1
                )
                if r.returncode == 0 and "Render/3D" in r.stdout:
                    import re
                    m = re.search(r'"busy":\s*([\d.]+)', r.stdout)
                    if m:
                        return float(m.group(1))
            except Exception:
                pass

        # macOS — powermetrics (GPU Engine)
        if _OS == "Darwin":
            try:
                r = subprocess.run(
                    ["sudo", "-n", "powermetrics", "-n", "1", "-i", "500",
                     "--samplers", "gpu_power"],
                    capture_output=True, text=True, timeout=2
                )
                if r.returncode == 0 and "GPU" in r.stdout:
                    import re
                    m = re.search(r'GPU\s+Active:\s+([\d.]+)%', r.stdout)
                    if m:
                        return float(m.group(1))
            except Exception:
                pass

        return -1.0

    def _get_temp(self) -> float:
        try:
            temps = psutil.sensors_temperatures()
            candidates = ["coretemp", "k10temp", "cpu_thermal", "acpitz",
                          "cpu-thermal", "zenpower", "it8688"]
            for name in candidates:
                if name in temps:
                    entries = temps[name]
                    if entries:
                        return entries[0].current
            for entries in temps.values():
                if entries:
                    return entries[0].current
        except Exception:
            pass
        if _OS == "Darwin":
            try:
                r = subprocess.run(
                    ["osx-cpu-temp"], capture_output=True, text=True, timeout=2
                )
                if r.returncode == 0:
                    import re
                    m = re.search(r"([\d.]+)", r.stdout)
                    if m:
                        return float(m.group(1))
            except Exception:
                pass

        if _OS == "Windows":
            try:
                r = subprocess.run(
                    ["powershell", "-Command",
                     "(Get-WmiObject MSAcpi_ThermalZoneTemperature -Namespace root/wmi).CurrentTemperature"],
                    capture_output=True, text=True, timeout=3
                )
                if r.returncode == 0 and r.stdout.strip():
                    raw = float(r.stdout.strip().split("\n")[0])
                    return (raw / 10.0) - 273.15
            except Exception:
                pass

        return -1.0

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "cpu": self.cpu,
                "mem": self.mem,
                "net": self.net,
                "gpu": self.gpu,
                "tmp": self.tmp,
            }


_metrics = _SysMetrics()

class HudCanvas(QWidget):
    def __init__(self, face_path: str, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setMinimumSize(300, 300)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.muted    = False
        self.speaking = False
        self.state    = "INITIALISING"

        self._tick       = 0
        self._scale      = 1.0
        self._tgt_scale  = 1.0
        self._halo       = 55.0
        self._tgt_halo   = 55.0
        self._last_t     = time.time()
        self._scan       = 0.0
        self._scan2      = 180.0
        self._rings      = [0.0, 120.0, 240.0]
        self._pulses: list[float] = [0.0, 50.0, 100.0]
        self._blink      = True
        self._blink_tick = 0
        self._particles: list[list[float]] = []
        self._face_px: QPixmap | None = None
        self._load_face(face_path)

        self._tmr = QTimer(self)
        self._tmr.timeout.connect(self._step)
        app = QApplication.instance()
        self._reduce_motion = bool(app and app.property("misha_reduce_motion"))
        if not self._reduce_motion:
            self._tmr.start(16)

    def _load_face(self, path: str):
        try:
            from PIL import Image, ImageDraw
            import io
            img = Image.open(path).convert("RGBA")
            sz  = min(img.size)
            img = img.resize((sz, sz), Image.LANCZOS)
            mk  = Image.new("L", (sz, sz), 0)
            ImageDraw.Draw(mk).ellipse((2, 2, sz - 2, sz - 2), fill=255)
            img.putalpha(mk)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            px = QPixmap(); px.loadFromData(buf.getvalue())
            self._face_px = px
        except Exception:
            self._face_px = None

    def trigger_wake_pulse(self) -> None:
        """Render one unmistakable, non-blocking acknowledgement pulse."""
        self.state = "WAKE_DETECTED"
        self._pulses = [0.0, 14.0, 28.0]
        self._scale = 1.0
        self._tgt_scale = 1.12
        self._halo = max(self._halo, 175.0)
        self._tgt_halo = 190.0
        self.update()

    def _step(self):
        self._tick += 1
        now = time.time()
        if now - self._last_t > (0.12 if self.speaking else 0.5):
            if self.speaking:
                self._tgt_scale = random.uniform(1.06, 1.14)
                self._tgt_halo  = random.uniform(145, 190)
            elif self.muted:
                self._tgt_scale = random.uniform(0.998, 1.002)
                self._tgt_halo  = random.uniform(15, 28)
            else:
                self._tgt_scale = random.uniform(1.001, 1.008)
                self._tgt_halo  = random.uniform(48, 68)
            self._last_t = now

        sp = 0.38 if self.speaking else 0.15
        self._scale += (self._tgt_scale - self._scale) * sp
        self._halo  += (self._tgt_halo  - self._halo)  * sp

        speeds = [1.3, -0.9, 2.0] if self.speaking else [0.55, -0.35, 0.9]
        for i, spd in enumerate(speeds):
            self._rings[i] = (self._rings[i] + spd) % 360

        self._scan  = (self._scan  + (3.0 if self.speaking else 1.3)) % 360
        self._scan2 = (self._scan2 + (-2.0 if self.speaking else -0.75)) % 360

        fw  = min(self.width(), self.height())
        lim = fw * 0.74
        spd = 4.2 if self.speaking else 2.0
        self._pulses = [r + spd for r in self._pulses if r + spd < lim]
        if len(self._pulses) < 3 and random.random() < (0.07 if self.speaking else 0.025):
            self._pulses.append(0.0)

        if self.speaking and random.random() < 0.28:
            cx, cy = self.width() / 2, self.height() / 2
            ang = random.uniform(0, 2 * math.pi)
            r_s = fw * 0.28
            self._particles.append([
                cx + math.cos(ang) * r_s, cy + math.sin(ang) * r_s,
                math.cos(ang) * random.uniform(0.9, 2.4),
                math.sin(ang) * random.uniform(0.9, 2.4) - 0.4, 1.0,
            ])
        self._particles = [
            [p[0]+p[2], p[1]+p[3], p[2]*0.97, p[3]*0.97, p[4]-0.028]
            for p in self._particles if p[4] > 0
        ]

        self._blink_tick += 1
        if self._blink_tick >= 38:
            self._blink = not self._blink
            self._blink_tick = 0
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        bg = QLinearGradient(0, 0, self.width(), self.height())
        bg.setColorAt(0.0, qcol("#07101C"))
        bg.setColorAt(0.52, qcol(C.BG))
        bg.setColorAt(1.0, qcol("#0A1020"))
        p.fillRect(self.rect(), QBrush(bg))

        W, H = self.width(), self.height()
        cx, cy = W / 2, H / 2
        fw = min(W, H)

        # restrained technical grid
        p.setPen(QPen(qcol(C.BORDER, 65), 1))
        for x in range(18, W, 52):
            for y in range(18, H, 52):
                p.drawPoint(x, y)

        r_face = fw * 0.31

        # halo glow
        for i in range(10):
            r   = r_face * (1.8 - i * 0.08)
            frc = 1.0 - i / 10
            a   = max(0, min(255, int(self._halo * 0.085 * frc)))
            col = qcol(C.MUTED_C if self.muted else C.PRI, a)
            p.setPen(QPen(col, 1.5)); p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))

        # pulse rings
        for pr in self._pulses:
            a   = max(0, int(230 * (1.0 - pr / (fw * 0.74))))
            col = qcol(C.MUTED_C if self.muted else C.PRI, a)
            p.setPen(QPen(col, 1.5)); p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QRectF(cx - pr, cy - pr, pr * 2, pr * 2))

        # spinning arc rings
        for idx, (r_frac, w_r, arc_l, gap) in enumerate(
            [(0.48, 3, 115, 78), (0.40, 2, 78, 55), (0.32, 1, 56, 40)]
        ):
            ring_r = fw * r_frac
            base   = self._rings[idx]
            a_val  = max(0, min(255, int(self._halo * (1.0 - idx * 0.18))))
            col    = qcol(C.MUTED_C if self.muted else C.PRI, a_val)
            p.setPen(QPen(col, w_r)); p.setBrush(Qt.BrushStyle.NoBrush)
            angle = base
            rect  = QRectF(cx - ring_r, cy - ring_r, ring_r * 2, ring_r * 2)
            while angle < base + 360:
                p.drawArc(rect, int(angle * 16), int(arc_l * 16))
                angle += arc_l + gap

        # scanners
        sr = fw * 0.50
        sa = min(255, int(self._halo * 1.5))
        ex = 75 if self.speaking else 44
        p.setPen(QPen(qcol(C.MUTED_C if self.muted else C.PRI, sa), 2.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        srect = QRectF(cx - sr, cy - sr, sr * 2, sr * 2)
        p.drawArc(srect, int(self._scan * 16), int(ex * 16))
        p.setPen(QPen(qcol(C.ACC, sa // 2), 1.5))
        p.drawArc(srect, int(self._scan2 * 16), int(ex * 16))

        # tick marks
        t_out, t_in = fw * 0.497, fw * 0.474
        p.setPen(QPen(qcol(C.PRI, 140), 1))
        for deg in range(0, 360, 10):
            rad = math.radians(deg)
            inn = t_in if deg % 30 == 0 else t_in + 6
            p.drawLine(
                QPointF(cx + t_out * math.cos(rad), cy - t_out * math.sin(rad)),
                QPointF(cx + inn  * math.cos(rad), cy - inn  * math.sin(rad)),
            )

        # crosshair
        ch_r, gap_h = fw * 0.51, fw * 0.16
        p.setPen(QPen(qcol(C.PRI, int(self._halo * 0.5)), 1))
        p.drawLine(QPointF(cx - ch_r, cy), QPointF(cx - gap_h, cy))
        p.drawLine(QPointF(cx + gap_h, cy), QPointF(cx + ch_r, cy))
        p.drawLine(QPointF(cx, cy - ch_r), QPointF(cx, cy - gap_h))
        p.drawLine(QPointF(cx, cy + gap_h), QPointF(cx, cy + ch_r))

        # corner brackets
        bl = 24
        bc = qcol(C.PRI, 210)
        hl, hr = cx - fw // 2, cx + fw // 2
        ht, hb = cy - fw // 2, cy + fw // 2
        p.setPen(QPen(bc, 2))
        for bx, by, dx, dy in [(hl,ht,1,1),(hr,ht,-1,1),(hl,hb,1,-1),(hr,hb,-1,-1)]:
            p.drawLine(QPointF(bx, by), QPointF(bx + dx * bl, by))
            p.drawLine(QPointF(bx, by), QPointF(bx, by + dy * bl))

        # face
        if self._face_px:
            fsz    = int(fw * 0.62 * self._scale)
            scaled = self._face_px.scaled(
                fsz, fsz,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            p.drawPixmap(int(cx - fsz / 2), int(cy - fsz / 2), scaled)
        else:
            orb_r = int(fw * 0.27 * self._scale)
            glow = QRadialGradient(QPointF(cx, cy), orb_r * 1.35)
            core = C.MUTED_C if self.muted else C.PRI
            glow.setColorAt(0.0, qcol(C.WHITE, 245))
            glow.setColorAt(0.16, qcol(core, 230))
            glow.setColorAt(0.48, qcol(C.ACC if not self.muted else C.RED, 120))
            glow.setColorAt(1.0, qcol(C.BG, 0))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(glow))
            p.drawEllipse(QRectF(cx - orb_r * 1.35, cy - orb_r * 1.35,
                                 orb_r * 2.7, orb_r * 2.7))
            p.setBrush(QBrush(qcol(C.PANEL, 225)))
            p.setPen(QPen(qcol(core, 210), 1.5))
            p.drawEllipse(QRectF(cx - orb_r * .58, cy - orb_r * .58,
                                 orb_r * 1.16, orb_r * 1.16))
            p.setFont(QFont(UI_FONT, 15, QFont.Weight.DemiBold))
            p.setPen(QPen(qcol(C.WHITE), 1))
            p.drawText(QRectF(cx - 90, cy - 18, 180, 36),
                       Qt.AlignmentFlag.AlignCenter, "MISHA")

        # particles
        for pt in self._particles:
            a = max(0, min(255, int(pt[4] * 255)))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(qcol(C.PRI, a)))
            p.drawEllipse(QPointF(pt[0], pt[1]), 2.5, 2.5)

        # status text
        sy = cy + fw * 0.40
        if self.muted:
            txt, col = "⊘  MUTED",     qcol(C.MUTED_C)
        elif self.speaking:
            txt, col = "●  SPEAKING",  qcol(C.ACC)
        elif self.state == "THINKING":
            sym = "◈" if self._blink else "◇"
            txt, col = f"{sym}  THINKING",   qcol(C.ACC2)
        elif self.state == "PROCESSING":
            sym = "▷" if self._blink else "▶"
            txt, col = f"{sym}  PROCESSING", qcol(C.ACC2)
        elif self.state == "LISTENING":
            sym = "●" if self._blink else "○"
            txt, col = f"{sym}  LISTENING",  qcol(C.GREEN)
        elif self.state == "WAKE_DETECTED":
            txt, col = "✦  MISHA HEARD YOU", qcol(C.ACC2)
        else:
            sym = "●" if self._blink else "○"
            txt, col = f"{sym}  {self.state}", qcol(C.PRI)

        p.setPen(QPen(col, 1))
        p.setFont(QFont(UI_FONT, 11, QFont.Weight.DemiBold))
        p.drawText(QRectF(0, sy, W, 26), Qt.AlignmentFlag.AlignCenter, txt)

        # waveform
        wy = sy + 30
        N, bw = 36, 8
        wx0 = (W - N * bw) / 2
        for i in range(N):
            if self.muted:
                hgt, cl = 2, qcol(C.MUTED_C)
            elif self.speaking:
                hgt = random.randint(3, 20)
                cl  = qcol(C.PRI) if hgt > 12 else qcol(C.PRI_DIM)
            else:
                hgt = int(3 + 2 * math.sin(self._tick * 0.09 + i * 0.6))
                cl  = qcol(C.BORDER_B)
            p.fillRect(QRectF(wx0 + i * bw, wy + 20 - hgt, bw - 1, hgt), cl)

class MetricBar(QWidget):

    def __init__(self, label: str, color: str = C.PRI, parent=None):
        super().__init__(parent)
        self._label = label
        self._color = color
        self._value = 0.0       # 0–100
        self._text  = "--"
        self.setFixedHeight(44)
        self.setMinimumWidth(80)

    def set_value(self, pct: float, text: str):
        self._value = max(0.0, min(100.0, pct))
        self._text  = text
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()

        p.setBrush(QBrush(qcol(C.PANEL2)))
        p.setPen(QPen(qcol(C.BORDER_A), 1))
        p.drawRoundedRect(QRectF(1, 1, W - 2, H - 2), 8, 8)

        bar_h   = 4
        bar_y   = H - bar_h - 7
        bar_w   = W - 16
        bar_x   = 8
        fill_w  = int(bar_w * self._value / 100)

        p.setBrush(QBrush(qcol(C.BAR_BG)))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRectF(bar_x, bar_y, bar_w, bar_h), 2, 2)

        if self._value > 85:
            bar_col = qcol(C.RED)
        elif self._value > 65:
            bar_col = qcol(C.ACC)
        else:
            bar_col = qcol(self._color)

        if fill_w > 0:
            p.setBrush(QBrush(bar_col))
            p.drawRoundedRect(QRectF(bar_x, bar_y, fill_w, bar_h), 2, 2)

        p.setFont(QFont(UI_FONT, 7, QFont.Weight.DemiBold))
        p.setPen(QPen(qcol(C.TEXT_DIM), 1))
        p.drawText(QRectF(8, 5, 50, 14), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self._label)

        p.setFont(QFont(MONO_FONT, 9, QFont.Weight.DemiBold))
        p.setPen(QPen(bar_col if self._text != "--" else qcol(C.TEXT_DIM), 1))
        p.drawText(QRectF(0, 4, W - 6, 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, self._text)

class LogWidget(QTextEdit):
    _sig = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setFont(QFont(MONO_FONT, 9))
        self.setStyleSheet(f"""
            QTextEdit {{
                background: {C.BG_ALT};
                color: {C.TEXT};
                border: 1px solid {C.BORDER};
                border-radius: 10px;
                padding: 10px;
                selection-background-color: {C.PRI_GHO};
            }}
            QScrollBar:vertical {{
                background: {C.BG};
                width: 6px;
                border: none;
            }}
            QScrollBar::handle:vertical {{
                background: {C.BORDER_B};
                border-radius: 3px;
                min-height: 20px;
            }}
        """)
        self._queue: list[str] = []
        self._typing  = False
        self._text    = ""
        self._pos     = 0
        self._tag     = "sys"
        self._tmr = QTimer(self)
        self._tmr.timeout.connect(self._step)
        self._sig.connect(self._enqueue)

    def append_log(self, text: str):
        self._sig.emit(text)

    def _enqueue(self, text: str):
        self._queue.append(text)
        if not self._typing:
            self._next()

    def _next(self):
        if not self._queue:
            self._typing = False
            return
        self._typing = True
        self._text   = self._queue.pop(0)
        self._pos    = 0
        tl = self._text.lower()
        if   tl.startswith("you:"):    self._tag = "you"
        elif tl.startswith("misha:"): self._tag = "ai"
        elif tl.startswith("file:"):   self._tag = "file"
        elif "err" in tl:              self._tag = "err"
        else:                          self._tag = "sys"
        app = QApplication.instance()
        if app and app.property("misha_reduce_motion"):
            cursor = self.textCursor()
            cursor.movePosition(cursor.MoveOperation.End)
            cursor.insertText(self._text + "\n")
            self.setTextCursor(cursor)
            self._typing = False
            self._next()
            return
        self._tmr.start(6)

    def _step(self):
        if self._pos < len(self._text):
            ch  = self._text[self._pos]
            cur = self.textCursor()
            fmt = cur.charFormat()
            col = {
                "you":  qcol(C.WHITE),
                "ai":   qcol(C.PRI),
                "err":  qcol(C.RED),
                "file": qcol(C.GREEN),
                "sys":  qcol(C.ACC2),
            }.get(self._tag, qcol(C.TEXT))
            fmt.setForeground(QBrush(col))
            cur.movePosition(cur.MoveOperation.End)
            cur.insertText(ch, fmt)
            self.setTextCursor(cur)
            self.ensureCursorVisible()
            self._pos += 1
        else:
            self._tmr.stop()
            cur = self.textCursor()
            cur.movePosition(cur.MoveOperation.End)
            cur.insertText("\n")
            self.setTextCursor(cur)
            self.ensureCursorVisible()
            QTimer.singleShot(20, self._next)

_FILE_ICONS = {
    "image":   ("🖼", "#00d4ff"), "video":   ("🎬", "#ff6b00"),
    "audio":   ("🎵", "#cc44ff"), "pdf":     ("📄", "#ff4444"),
    "word":    ("📝", "#4488ff"), "excel":   ("📊", "#44bb44"),
    "code":    ("💻", "#ffcc00"), "archive": ("📦", "#ff8844"),
    "pptx":    ("📊", "#ff6622"), "text":    ("📃", "#aaaaaa"),
    "data":    ("🔧", "#88ddff"), "unknown": ("📎", "#888888"),
}
_EXT_TO_CAT = {
    **dict.fromkeys(["jpg","jpeg","png","gif","webp","bmp","tiff","svg","ico"], "image"),
    **dict.fromkeys(["mp4","avi","mov","mkv","wmv","flv","webm","m4v"],         "video"),
    **dict.fromkeys(["mp3","wav","ogg","m4a","aac","flac","wma","opus"],        "audio"),
    **dict.fromkeys(["pdf"],                                                     "pdf"),
    **dict.fromkeys(["doc","docx"],                                              "word"),
    **dict.fromkeys(["xls","xlsx","ods"],                                        "excel"),
    **dict.fromkeys(["ppt","pptx"],                                              "pptx"),
    **dict.fromkeys(["py","js","ts","jsx","tsx","html","css","java","c","cpp",
                     "cs","go","rs","rb","php","swift","kt","sh","sql","lua"],   "code"),
    **dict.fromkeys(["zip","rar","tar","gz","7z","bz2","xz"],                   "archive"),
    **dict.fromkeys(["txt","md","rst","log"],                                    "text"),
    **dict.fromkeys(["csv","tsv","json","xml"],                                  "data"),
}

def _file_category(path: Path) -> str:
    return _EXT_TO_CAT.get(path.suffix.lower().lstrip("."), "unknown")

def _fmt_size(size: int) -> str:
    if   size < 1024:    return f"{size} B"
    elif size < 1024**2: return f"{size/1024:.1f} KB"
    elif size < 1024**3: return f"{size/1024**2:.1f} MB"
    else:                return f"{size/1024**3:.1f} GB"


class FileDropZone(QWidget):
    file_selected = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAccessibleName("Context file drop zone")
        self.setAccessibleDescription("Drop or choose one local file to provide task context")
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(112)
        self._current_file: str | None = None
        self._hovering  = False
        self._drag_over = False
        self._dash_offset = 0.0
        self._anim_tmr = QTimer(self)
        self._anim_tmr.timeout.connect(self._animate)
        app = QApplication.instance()
        if not (app and app.property("misha_reduce_motion")):
            self._anim_tmr.start(40)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._canvas = _DropCanvas(self)
        layout.addWidget(self._canvas)

    def _animate(self):
        self._dash_offset = (self._dash_offset + 0.8) % 20
        self._canvas.update()

    def dragEnterEvent(self, e: QDragEnterEvent):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self._drag_over = True; self._canvas.update()

    def dragLeaveEvent(self, e):
        self._drag_over = False; self._canvas.update()

    def dropEvent(self, e: QDropEvent):
        self._drag_over = False
        urls = e.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            if Path(path).is_file():
                self._set_file(path)
        self._canvas.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._browse()

    def enterEvent(self, e):
        self._hovering = True; self._canvas.update()

    def leaveEvent(self, e):
        self._hovering = False; self._canvas.update()

    def current_file(self) -> str | None:
        return self._current_file

    def clear_file(self):
        self._current_file = None; self._canvas.update()

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select a file for MISHA", str(Path.home()),
            "All Files (*.*);;"
            "Images (*.jpg *.jpeg *.png *.gif *.webp *.bmp *.svg);;"
            "Documents (*.pdf *.docx *.txt *.md *.pptx);;"
            "Data (*.csv *.xlsx *.json *.xml);;"
            "Code (*.py *.js *.ts *.html *.css *.java *.cpp *.go);;"
            "Audio (*.mp3 *.wav *.ogg *.m4a *.aac *.flac);;"
            "Video (*.mp4 *.avi *.mov *.mkv *.wmv *.webm);;"
            "Archives (*.zip *.rar *.tar *.gz *.7z)",
        )
        if path:
            self._set_file(path)

    def _set_file(self, path: str):
        self._current_file = path
        self._canvas.update()
        self.file_selected.emit(path)


class _DropCanvas(QWidget):
    def __init__(self, zone: FileDropZone):
        super().__init__(zone)
        self._z = zone

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        z    = self._z
        W, H = self.width(), self.height()
        pad  = 6
        rect = QRectF(pad, pad, W - pad * 2, H - pad * 2)

        bg_col = qcol(C.PANEL_HI if z._drag_over else (C.PANEL2 if z._hovering else C.BG_ALT))
        p.setBrush(QBrush(bg_col)); p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(rect, 10, 10)

        if z._current_file:   border_col = qcol(C.GREEN, 200)
        elif z._drag_over:    border_col = qcol(C.PRI, 230)
        elif z._hovering:     border_col = qcol(C.BORDER_B, 200)
        else:                 border_col = qcol(C.BORDER, 160)

        pen = QPen(border_col, 1.5, Qt.PenStyle.DashLine)
        pen.setDashOffset(z._dash_offset)
        p.setPen(pen); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(rect, 10, 10)

        if z._current_file:   self._paint_file(p, W, H)
        elif z._drag_over:    self._paint_drag_over(p, W, H)
        else:                 self._paint_idle(p, W, H, z._hovering)

    def _paint_idle(self, p, W, H, hover):
        cx, cy = W / 2, H / 2
        col = qcol(C.PRI_DIM if not hover else C.PRI)
        p.setPen(QPen(col, 2)); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawLine(QPointF(cx, cy - 14), QPointF(cx, cy + 4))
        p.drawLine(QPointF(cx - 8, cy - 6), QPointF(cx, cy - 14))
        p.drawLine(QPointF(cx + 8, cy - 6), QPointF(cx, cy - 14))
        p.drawLine(QPointF(cx - 14, cy + 4), QPointF(cx + 14, cy + 4))
        p.setFont(QFont(UI_FONT, 8, QFont.Weight.Medium))
        p.setPen(QPen(qcol(C.PRI_DIM if not hover else C.TEXT), 1))
        p.drawText(QRectF(0, cy + 8, W, 16), Qt.AlignmentFlag.AlignCenter,
                   "Drop file here or browse")
        p.setFont(QFont(UI_FONT, 7))
        p.setPen(QPen(qcol("#1a4a5a"), 1))
        p.drawText(QRectF(0, cy + 24, W, 14), Qt.AlignmentFlag.AlignCenter,
                   "Images · documents · audio · code")

    def _paint_drag_over(self, p, W, H):
        cx, cy = W / 2, H / 2
        p.setFont(QFont("Courier New", 20))
        p.setPen(QPen(qcol(C.PRI), 1))
        p.drawText(QRectF(0, cy - 24, W, 32), Qt.AlignmentFlag.AlignCenter, "⬇")
        p.setFont(QFont(UI_FONT, 8, QFont.Weight.DemiBold))
        p.setPen(QPen(qcol(C.PRI), 1))
        p.drawText(QRectF(0, cy + 12, W, 16), Qt.AlignmentFlag.AlignCenter, "Release to load")

    def _paint_file(self, p, W, H):
        if not self._z._current_file: return
        path = Path(self._z._current_file)
        cat  = _file_category(path)
        icon, icon_col = _FILE_ICONS.get(cat, _FILE_ICONS["unknown"])
        size_str = _fmt_size(path.stat().st_size)
        ext_str  = path.suffix.upper().lstrip(".") or "FILE"

        block_x, block_w = 10, 60
        p.setFont(QFont("Segoe UI Emoji", 22) if _OS == "Windows" else QFont("Arial", 22))
        p.setPen(QPen(qcol(icon_col), 1))
        p.drawText(QRectF(block_x, 0, block_w, H), Qt.AlignmentFlag.AlignCenter, icon)

        tx = block_x + block_w + 6
        tw = W - tx - 38

        p.setFont(QFont(UI_FONT, 8, QFont.Weight.DemiBold))
        p.setPen(QPen(qcol(C.WHITE), 1))
        name = path.name if len(path.name) <= 34 else path.name[:31] + "..."
        p.drawText(QRectF(tx, H * 0.18, tw, 16),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, name)

        p.setFont(QFont(MONO_FONT, 7))
        p.setPen(QPen(qcol(C.TEXT_DIM), 1))
        p.drawText(QRectF(tx, H * 0.18 + 18, tw, 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   f"{ext_str}  ·  {size_str}")

        p.setFont(QFont(MONO_FONT, 6))
        p.setPen(QPen(qcol("#1e5c6a"), 1))
        par = str(path.parent)
        if len(par) > 42: par = "…" + par[-41:]
        p.drawText(QRectF(tx, H * 0.18 + 34, tw, 12),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, par)

        p.setFont(QFont(UI_FONT, 9, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.RED, 180), 1))
        p.drawText(QRectF(W - 34, 0, 28, H), Qt.AlignmentFlag.AlignCenter, "✕")

    def mousePressEvent(self, e):
        z = self._z
        if z._current_file and e.pos().x() > self.width() - 34:
            z.clear_file()
        else:
            z.mousePressEvent(e)


class SetupOverlay(QWidget):
    done = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAccessibleName("Misha local setup")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            SetupOverlay {{
                background: {C.PANEL};
                border: 1px solid {C.BORDER_B};
                border-radius: 16px;
            }}
        """)

        detected = {"darwin": "mac", "windows": "windows"}.get(
            _OS.lower(), "linux"
        )
        self._sel_os = detected

        layout = QVBoxLayout(self)
        layout.setContentsMargins(34, 28, 34, 28)
        layout.setSpacing(10)

        def _lbl(txt, font_size=9, bold=False, color=C.PRI,
                 align=Qt.AlignmentFlag.AlignCenter):
            w = QLabel(txt)
            w.setAlignment(align)
            w.setFont(QFont(UI_FONT, font_size,
                            QFont.Weight.Bold if bold else QFont.Weight.Normal))
            w.setStyleSheet(f"color: {color}; background: transparent;")
            return w

        layout.addWidget(_lbl("Welcome to Misha", 18, True, color=C.WHITE))
        layout.addWidget(_lbl("Configure your private, on-device intelligence.", 9, color=C.TEXT_MED))
        layout.addSpacing(6)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER};"); layout.addWidget(sep)
        layout.addSpacing(4)

        layout.addWidget(_lbl("Local Ollama model", 9, True, color=C.TEXT_MED,
                               align=Qt.AlignmentFlag.AlignLeft))
        self._key_input = QLineEdit()
        self._key_input.setAccessibleName("Local Ollama model name")
        self._key_input.setText("qwen3-coder:30b")
        self._key_input.setPlaceholderText("Example: qwen3-coder:30b")
        self._key_input.setFont(QFont(UI_FONT, 10))
        self._key_input.setFixedHeight(42)
        self._key_input.setStyleSheet(f"""
            QLineEdit {{
                background: {C.BG_ALT}; color: {C.TEXT};
                border: 1px solid {C.BORDER}; border-radius: 10px; padding: 4px 12px;
            }}
            QLineEdit:focus {{ border: 1px solid {C.PRI}; }}
        """)
        layout.addWidget(self._key_input)
        layout.addSpacing(12)

        sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet(f"color: {C.BORDER};"); layout.addWidget(sep2)
        layout.addSpacing(4)

        layout.addWidget(_lbl("Operating system", 9, True, color=C.TEXT_MED,
                               align=Qt.AlignmentFlag.AlignLeft))
        det_name = {"windows": "Windows", "mac": "macOS", "linux": "Linux"}[detected]
        layout.addWidget(_lbl(f"Auto-detected: {det_name}", 8, color=C.ACC2,
                               align=Qt.AlignmentFlag.AlignLeft))

        os_row = QHBoxLayout(); os_row.setSpacing(6)
        self._os_btns: dict[str, QPushButton] = {}
        for key, label in [("windows","⊞  Windows"),("mac","  macOS"),("linux","🐧  Linux")]:
            btn = QPushButton(label)
            btn.setFont(QFont(UI_FONT, 9, QFont.Weight.DemiBold))
            btn.setFixedHeight(38)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _, k=key: self._sel(k))
            os_row.addWidget(btn)
            self._os_btns[key] = btn
        layout.addLayout(os_row)
        self._sel(detected)
        layout.addSpacing(12)

        init_btn = QPushButton("Continue to Misha  →")
        init_btn.setAccessibleName("Continue to Misha")
        init_btn.setFont(QFont(UI_FONT, 10, QFont.Weight.DemiBold))
        init_btn.setFixedHeight(42)
        init_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        init_btn.setStyleSheet(f"""
            QPushButton {{
                background: {C.PRI}; color: {C.BG};
                border: none; border-radius: 10px;
            }}
            QPushButton:hover {{
                background: {C.WHITE};
            }}
        """)
        init_btn.clicked.connect(self._submit)
        layout.addWidget(init_btn)

    def _sel(self, key: str):
        self._sel_os = key
        pal = {"windows":(C.PRI,"#001a22"),"mac":(C.ACC2,"#1a1400"),"linux":(C.GREEN,"#001a0d")}
        for k, btn in self._os_btns.items():
            if k == key:
                fg, bg = pal[k]
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: {fg}; color: {bg};
                        border: none; border-radius: 9px; font-weight: bold;
                    }}
                """)
            else:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: {C.BG_ALT}; color: {C.TEXT_DIM};
                        border: 1px solid {C.BORDER}; border-radius: 9px;
                    }}
                    QPushButton:hover {{ color: {C.TEXT}; border: 1px solid {C.BORDER_B}; }}
                """)

    def _submit(self):
        model = self._key_input.text().strip()
        if not model:
            self._key_input.setStyleSheet(
                self._key_input.styleSheet() +
                f" QLineEdit {{ border: 1px solid {C.RED}; }}"
            )
            return
        self.done.emit(model, self._sel_os)


class ModelProviderSettingsDialog(QDialog):
    def __init__(self, model: str, fallbacks: list[str], context_length: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Misha Local Model")
        self.setAccessibleName("Misha local model settings")
        self.setModal(True)
        self.setFixedSize(500, 340)
        self.setStyleSheet(f"QDialog {{ background: {C.PANEL}; color: {C.TEXT}; }}")
        root = QVBoxLayout(self)
        title = QLabel("Local model provider")
        title.setFont(QFont(UI_FONT, 15, QFont.Weight.DemiBold))
        root.addWidget(title)
        note = QLabel(
            "Provider is locked to local Ollama. Cloud aliases and remote hosts are rejected."
        )
        note.setWordWrap(True)
        root.addWidget(note)
        form = QFormLayout()
        provider = QLineEdit("Ollama (localhost only)")
        provider.setReadOnly(True)
        provider.setAccessibleName("Local provider")
        form.addRow("Provider", provider)
        self.model = QLineEdit(model)
        self.model.setAccessibleName("Primary local Ollama model")
        form.addRow("Primary model", self.model)
        self.fallbacks = QLineEdit(", ".join(fallbacks))
        self.fallbacks.setAccessibleName("Fallback local Ollama models")
        self.fallbacks.setPlaceholderText("Up to four comma-separated local models")
        form.addRow("Fallbacks", self.fallbacks)
        self.context = QComboBox()
        self.context.setAccessibleName("Local model context length")
        for value in (2048, 4096, 8192, 16384, 32768):
            self.context.addItem(f"{value:,} tokens", value)
        nearest = min(
            range(self.context.count()),
            key=lambda index: abs(int(self.context.itemData(index)) - context_length),
        )
        self.context.setCurrentIndex(nearest)
        form.addRow("Context", self.context)
        root.addLayout(form)
        root.addStretch()
        buttons = QHBoxLayout()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Save local model settings")
        save.clicked.connect(self.accept)
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        root.addLayout(buttons)

    def values(self) -> tuple[str, list[str], int]:
        fallbacks = [item.strip() for item in self.fallbacks.text().split(",") if item.strip()]
        return self.model.text().strip(), fallbacks, int(self.context.currentData())


class SettingsCenterDialog(QDialog):
    """One durable home for owner-facing application preferences."""

    def __init__(self, values: dict[str, object], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Misha — Settings")
        self.setAccessibleName("Misha settings center")
        self.setMinimumSize(620, 470)
        self.setStyleSheet(f"""
            QDialog {{ background: {C.PANEL}; color: {C.TEXT}; }}
            QTabWidget::pane {{ border: 1px solid {C.BORDER}; background: {C.BG_ALT}; }}
            QTabBar::tab {{ color: {C.TEXT_MED}; padding: 9px 15px; }}
            QTabBar::tab:selected {{ color: {C.PRI}; border-bottom: 2px solid {C.PRI}; }}
            QCheckBox, QLabel {{ color: {C.TEXT}; }}
            QComboBox {{ color: {C.WHITE}; background: {C.PANEL2};
                border: 1px solid {C.BORDER}; padding: 7px; min-width: 210px; }}
        """)
        root = QVBoxLayout(self)
        title = QLabel("SETTINGS CENTER")
        title.setFont(QFont(UI_FONT, 14, QFont.Weight.DemiBold))
        title.setStyleSheet(f"color: {C.WHITE};")
        root.addWidget(title)
        self.tabs = QTabWidget()
        self.tabs.setAccessibleName("Settings categories")
        root.addWidget(self.tabs, stretch=1)

        general = QWidget()
        general_form = QFormLayout(general)
        self.always_on_top = QCheckBox("Keep Misha above other windows")
        self.always_on_top.setChecked(bool(values.get("always_on_top", True)))
        self.launch_at_login = QCheckBox("Start Misha when I sign in")
        self.launch_at_login.setChecked(bool(values.get("launch_at_login", False)))
        general_form.addRow("Window", self.always_on_top)
        general_form.addRow("Startup", self.launch_at_login)
        self.tabs.addTab(general, "General")

        voice = QWidget()
        voice_form = QFormLayout(voice)
        self.hands_free = QCheckBox("Listen for ‘Misha’ without pressing a button")
        self.hands_free.setChecked(bool(values.get("hands_free", True)))
        self.voice_sensitivity = QComboBox()
        self.voice_sensitivity.addItem("Low — reject more ambient sound", "low")
        self.voice_sensitivity.addItem("Normal — balanced", "normal")
        self.voice_sensitivity.addItem("High — detect quieter speech", "high")
        self.voice_sensitivity.setCurrentIndex(max(
            0, self.voice_sensitivity.findData(values.get("voice_sensitivity", "normal"))
        ))
        diagnostics = QPushButton("Open owner voice and device diagnostics")
        diagnostics.clicked.connect(self._open_voice_diagnostics)
        voice_form.addRow("Hands-free", self.hands_free)
        voice_form.addRow("Sensitivity", self.voice_sensitivity)
        voice_form.addRow("Microphone / speaker / wake", diagnostics)
        self.tabs.addTab(voice, "Voice")

        integrations = QWidget()
        integrations_form = QFormLayout(integrations)
        self.screen_observation = QCheckBox("Allow local Screen Observation")
        self.screen_observation.setChecked(bool(values.get("screen_observation", False)))
        self.ide_context = QCheckBox("Allow private VS Code context bridge")
        self.ide_context.setChecked(bool(values.get("ide_context", False)))
        note = QLabel("Both integrations are off by default and remain local-only.")
        note.setWordWrap(True)
        integrations_form.addRow("Screen", self.screen_observation)
        integrations_form.addRow("IDE", self.ide_context)
        integrations_form.addRow("Privacy", note)
        self.tabs.addTab(integrations, "Integrations")

        privacy = QWidget()
        privacy_layout = QVBoxLayout(privacy)
        privacy_note = QLabel(
            "Memory is encrypted locally. Permissions stay under operating-system "
            "control, and the audit view never displays prompts, paths or credentials."
        )
        privacy_note.setWordWrap(True)
        privacy_layout.addWidget(privacy_note)
        memory = QPushButton("Manage encrypted memory")
        memory.clicked.connect(lambda: MemoryManagerDialog(self).exec())
        permissions = QPushButton("Review operating-system permissions")
        permissions.clicked.connect(lambda: PermissionsDialog(self).exec())
        audit = QPushButton("View redacted security audit")
        audit.clicked.connect(lambda: AuditLogDialog(self).exec())
        privacy_layout.addWidget(memory)
        privacy_layout.addWidget(permissions)
        privacy_layout.addWidget(audit)
        privacy_layout.addStretch()
        self.tabs.addTab(privacy, "Privacy")

        language = QWidget()
        language_form = QFormLayout(language)
        self.ui_language = QComboBox()
        self.ui_language.addItem("Türkçe", "tr")
        self.ui_language.addItem("English", "en")
        self.ui_language.setCurrentIndex(
            max(0, self.ui_language.findData(values.get("ui_language", "tr")))
        )
        self.response_language = QComboBox()
        self.response_language.addItem("Follow the user", "auto")
        self.response_language.addItem("Türkçe", "tr")
        self.response_language.addItem("English", "en")
        self.response_language.setCurrentIndex(
            max(0, self.response_language.findData(values.get("response_language", "auto")))
        )
        language_form.addRow("Interface language", self.ui_language)
        language_form.addRow("Assistant replies", self.response_language)
        language_form.addRow("Note", QLabel("Interface language applies fully after restart."))
        self.tabs.addTab(language, "Language")

        advanced = QWidget()
        advanced_form = QFormLayout(advanced)
        self.debug_logging = QCheckBox("Enable additional local diagnostic logs")
        self.debug_logging.setChecked(bool(values.get("debug_logging", False)))
        self.safe_mode = QCheckBox("Strict safe mode (required)")
        self.safe_mode.setChecked(True)
        self.safe_mode.setEnabled(False)
        advanced_form.addRow("Diagnostics", self.debug_logging)
        advanced_form.addRow("Safety", self.safe_mode)
        advanced_form.addRow(
            "Data boundary", QLabel("Debug logs are redacted and stay on this device."),
        )
        self.tabs.addTab(advanced, "Advanced / Debug")

        buttons = QHBoxLayout()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Save settings")
        save.setDefault(True)
        save.clicked.connect(self.accept)
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        root.addLayout(buttons)

    def values(self) -> dict[str, object]:
        return {
            "always_on_top": self.always_on_top.isChecked(),
            "launch_at_login": self.launch_at_login.isChecked(),
            "hands_free": self.hands_free.isChecked(),
            "voice_sensitivity": str(self.voice_sensitivity.currentData()),
            "screen_observation": self.screen_observation.isChecked(),
            "ide_context": self.ide_context.isChecked(),
            "ui_language": str(self.ui_language.currentData()),
            "response_language": str(self.response_language.currentData()),
            "debug_logging": self.debug_logging.isChecked(),
            "safe_mode": True,
        }

    def _open_voice_diagnostics(self) -> None:
        window = self.parent()
        PrivacyOnboardingDialog(
            self,
            checks_callback=getattr(window, "on_setup_diagnostics", None),
            speaker_callback=getattr(window, "on_speaker_test", None),
            devices_callback=getattr(window, "on_audio_devices", None),
            select_devices_callback=getattr(window, "on_audio_device_select", None),
            microphone_callback=getattr(window, "on_microphone_test", None),
            wake_callback=getattr(window, "on_wake_test", None),
        ).exec()


class AccessibilitySettingsDialog(QDialog):
    _SCALES = (0.85, 1.0, 1.15, 1.3, 1.5)

    def __init__(self, font_scale: float, reduce_motion: bool, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Misha Accessibility")
        self.setAccessibleName("Misha accessibility settings")
        self.setModal(True)
        self.setFixedSize(420, 250)
        self.setStyleSheet(f"""
            QDialog {{ background: {C.PANEL}; color: {C.TEXT}; }}
            QLabel, QCheckBox {{ color: {C.TEXT}; }}
            QComboBox {{ color: {C.WHITE}; background: {C.BG_ALT};
                border: 1px solid {C.BORDER_B}; border-radius: 7px; padding: 7px; }}
        """)
        root = QVBoxLayout(self)
        title = QLabel("Accessibility")
        title.setFont(QFont(UI_FONT, 15, QFont.Weight.DemiBold))
        root.addWidget(title)
        note = QLabel(
            "Font scale and motion preferences apply after Misha restarts. "
            "Keyboard focus remains visible at every scale."
        )
        note.setWordWrap(True)
        root.addWidget(note)
        form = QFormLayout()
        self.scale = QComboBox()
        self.scale.setAccessibleName("Misha font scale")
        for value in self._SCALES:
            self.scale.addItem(f"{round(value * 100)}%", value)
        nearest = min(range(len(self._SCALES)), key=lambda index: abs(self._SCALES[index] - font_scale))
        self.scale.setCurrentIndex(nearest)
        form.addRow("Font scale", self.scale)
        self.reduce_motion = QCheckBox("Reduce decorative motion")
        self.reduce_motion.setAccessibleName("Reduce decorative motion")
        self.reduce_motion.setChecked(bool(reduce_motion))
        form.addRow("Motion", self.reduce_motion)
        root.addLayout(form)
        root.addStretch()
        buttons = QHBoxLayout()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Save accessibility settings")
        save.clicked.connect(self.accept)
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        root.addLayout(buttons)

    def values(self) -> tuple[float, bool]:
        return float(self.scale.currentData()), self.reduce_motion.isChecked()


class ProactiveSettingsDialog(QDialog):
    def __init__(self, settings, denylist, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Privacy & Observation")
        self.setModal(True)
        self.setFixedSize(480, 430)
        self.setStyleSheet(f"""
            QDialog {{ background: {C.PANEL}; color: {C.TEXT}; }}
            QLabel, QCheckBox {{ color: {C.TEXT}; }}
            QLineEdit, QTextEdit, QTimeEdit, QSpinBox, QComboBox {{
                color: {C.WHITE}; background: {C.BG_ALT};
                border: 1px solid {C.BORDER_B}; border-radius: 7px; padding: 5px;
            }}
        """)
        root = QVBoxLayout(self)
        title = QLabel("Proactive privacy controls")
        title.setFont(QFont(UI_FONT, 15, QFont.Weight.DemiBold))
        root.addWidget(title)
        self.note = QLabel(
            "Observation stays local. Password managers and credential screens "
            "are always excluded, regardless of these settings."
        )
        self.note.setWordWrap(True)
        self.note.setStyleSheet(f"color: {C.TEXT_MED};")
        root.addWidget(self.note)

        form = QFormLayout()
        self.quiet_enabled = QCheckBox("Enable quiet hours")
        self.quiet_enabled.setChecked(settings.quiet_hours_enabled)
        form.addRow("Quiet hours", self.quiet_enabled)
        self.quiet_start = QTimeEdit(QTime.fromString(settings.quiet_start, "HH:mm"))
        self.quiet_start.setDisplayFormat("HH:mm")
        form.addRow("Starts", self.quiet_start)
        self.quiet_end = QTimeEdit(QTime.fromString(settings.quiet_end, "HH:mm"))
        self.quiet_end.setDisplayFormat("HH:mm")
        form.addRow("Ends", self.quiet_end)
        self.daily_limit = QSpinBox()
        self.daily_limit.setRange(1, 50)
        self.daily_limit.setValue(settings.daily_limit)
        self.daily_limit.setSuffix(" notices / day")
        form.addRow("Daily limit", self.daily_limit)
        self.minimum_priority = QComboBox()
        self.minimum_priority.addItem("Low — all explicit issues", "low")
        self.minimum_priority.addItem("Normal — actionable issues", "normal")
        self.minimum_priority.addItem("Critical — security/data loss only", "critical")
        index = self.minimum_priority.findData(settings.minimum_priority)
        self.minimum_priority.setCurrentIndex(max(0, index))
        form.addRow("Minimum priority", self.minimum_priority)
        root.addLayout(form)

        deny_label = QLabel("Additional blocked apps or domains — one per line")
        deny_label.setStyleSheet(f"color: {C.TEXT_MED};")
        root.addWidget(deny_label)
        self.denylist = QTextEdit()
        self.denylist.setPlainText("\n".join(denylist))
        self.denylist.setFixedHeight(82)
        root.addWidget(self.denylist)

        buttons = QHBoxLayout()
        audit = QPushButton("View security audit")
        audit.clicked.connect(self._open_audit)
        buttons.addWidget(audit)
        memory = QPushButton("Manage memory")
        memory.clicked.connect(self._open_memory)
        buttons.addWidget(memory)
        permissions = QPushButton("Permissions")
        permissions.clicked.connect(self._open_permissions)
        buttons.addWidget(permissions)
        buttons.addStretch()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Save locally")
        save.setStyleSheet(
            f"color: {C.BG}; background: {C.PRI}; border-radius: 8px; padding: 8px 14px;"
        )
        save.clicked.connect(self.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        root.addLayout(buttons)

    def values(self):
        from core.proactive_policy import ProactiveSettings

        settings = ProactiveSettings.validated(
            quiet_hours_enabled=self.quiet_enabled.isChecked(),
            quiet_start=self.quiet_start.time().toString("HH:mm"),
            quiet_end=self.quiet_end.time().toString("HH:mm"),
            daily_limit=self.daily_limit.value(),
            minimum_priority=self.minimum_priority.currentData(),
        )
        denylist = tuple(
            line.strip()
            for line in self.denylist.toPlainText().splitlines()
            if line.strip()
        )
        return settings, denylist

    def _open_audit(self) -> None:
        AuditLogDialog(self).exec()

    def _open_memory(self) -> None:
        MemoryManagerDialog(self).exec()

    def _open_permissions(self) -> None:
        PermissionsDialog(self).exec()


class AuditLogDialog(QDialog):
    def __init__(
        self,
        parent=None,
        *,
        category_filter: str | None = None,
        title_text: str = "Local security audit",
    ):
        super().__init__(parent)
        self._category_filter = category_filter
        self.setWindowTitle(title_text)
        self.setModal(True)
        self.resize(760, 520)
        self.setStyleSheet(f"""
            QDialog {{ background: {C.PANEL}; color: {C.TEXT}; }}
            QLabel {{ color: {C.TEXT}; }}
            QTextEdit {{
                color: {C.TEXT}; background: {C.BG_ALT};
                border: 1px solid {C.BORDER_B}; border-radius: 8px;
                padding: 9px; font-family: {MONO_FONT}; font-size: 11px;
            }}
        """)
        root = QVBoxLayout(self)
        title = QLabel(title_text)
        title.setFont(QFont(UI_FONT, 15, QFont.Weight.DemiBold))
        root.addWidget(title)
        note = QLabel(
            "Only allowlisted metadata is shown. Prompts, messages, paths and "
            "credentials are never rendered in this viewer."
        )
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {C.TEXT_MED};")
        root.addWidget(note)
        self.events = QTextEdit()
        self.events.setReadOnly(True)
        root.addWidget(self.events, stretch=1)
        self.status = QLabel("")
        self.status.setStyleSheet(f"color: {C.TEXT_MED};")
        root.addWidget(self.status)
        buttons = QHBoxLayout()
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh)
        clear = QPushButton("Clear history…")
        clear.setStyleSheet(f"color: {C.RED};")
        clear.clicked.connect(self.clear_history)
        clear.setVisible(category_filter is None)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        buttons.addWidget(refresh)
        buttons.addWidget(clear)
        buttons.addStretch()
        buttons.addWidget(close)
        root.addLayout(buttons)
        self.refresh()

    def refresh(self) -> None:
        try:
            from core.audit_logger import list_events
            from core.audit_view import format_audit_events

            events = list_events(limit=1000 if self._category_filter else 200)
            if self._category_filter:
                events = [
                    event for event in events
                    if event.get("category") == self._category_filter
                ][:200]
            self.events.setPlainText(format_audit_events(events))
            self.status.setText(f"{len(events)} most recent local event(s).")
        except Exception as exc:
            self.events.setPlainText("Audit records are temporarily unavailable.")
            self.status.setText(f"Read failed safely: {type(exc).__name__}")

    def clear_history(self) -> None:
        reply = QMessageBox.question(
            self,
            "Clear local audit history?",
            "This permanently removes the current local audit history. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            from core.audit_logger import AuditEvent, clear_events, log_event

            count = clear_events()
            log_event(AuditEvent(
                category="audit_management",
                action="clear_history",
                status="completed",
                details={"result_status": f"cleared_{count}"},
            ))
            self.refresh()
            self.status.setText(
                f"Cleared {count} historical event(s); a clear marker was retained."
            )
        except Exception as exc:
            self.status.setText(f"Clear failed safely: {type(exc).__name__}")


class MemoryManagerDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Private Memory — Protected")
        self.setModal(True)
        self.resize(820, 590)
        self._records = []
        self._visible_records = []
        self.setStyleSheet(f"""
            QDialog {{ background: {C.PANEL}; color: {C.TEXT}; }}
            QLabel {{ color: {C.TEXT}; }}
            QListWidget, QTextEdit, QComboBox {{
                color: {C.TEXT}; background: {C.BG_ALT};
                border: 1px solid {C.BORDER_B}; border-radius: 8px; padding: 6px;
            }}
        """)
        root = QVBoxLayout(self)
        title = QLabel("Private local memory")
        title.setFont(QFont(UI_FONT, 15, QFont.Weight.DemiBold))
        root.addWidget(title)
        note = QLabel(
            "Opening this window decrypts records only for this local view. "
            "This protected window is excluded from proactive observation."
        )
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {C.TEXT_MED};")
        root.addWidget(note)

        filters = QHBoxLayout()
        self.kind_filter = QComboBox()
        self.kind_filter.addItem("All memory types", None)
        self.kind_filter.addItem("Working", "working")
        self.kind_filter.addItem("Episodic", "episodic")
        self.kind_filter.addItem("Decisions", "decision")
        self.kind_filter.addItem("Long term", "long_term")
        self.kind_filter.currentIndexChanged.connect(self.refresh)
        self.category_filter = QComboBox()
        self.category_filter.addItem("All categories", None)
        self.category_filter.currentIndexChanged.connect(self._render_list)
        filters.addWidget(self.kind_filter)
        filters.addWidget(self.category_filter)
        root.addLayout(filters)

        body = QHBoxLayout()
        self.record_list = QListWidget()
        self.record_list.setMinimumWidth(330)
        self.record_list.currentRowChanged.connect(self._show_selected)
        body.addWidget(self.record_list, stretch=2)
        self.details = QTextEdit()
        self.details.setReadOnly(True)
        self.details.setPlaceholderText("Select a memory record to inspect it.")
        body.addWidget(self.details, stretch=3)
        root.addLayout(body, stretch=1)

        self.status = QLabel("")
        self.status.setStyleSheet(f"color: {C.TEXT_MED};")
        root.addWidget(self.status)
        buttons = QHBoxLayout()
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh)
        delete = QPushButton("Delete selected…")
        delete.setStyleSheet(f"color: {C.RED};")
        delete.clicked.connect(self.delete_selected)
        clear = QPushButton("Clear current view…")
        clear.setStyleSheet(f"color: {C.RED};")
        clear.clicked.connect(self.clear_current)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        buttons.addWidget(refresh)
        buttons.addWidget(delete)
        buttons.addWidget(clear)
        buttons.addStretch()
        buttons.addWidget(close)
        root.addLayout(buttons)
        self.refresh()

    def refresh(self) -> None:
        try:
            from core.memory_service import list_memories

            kind = self.kind_filter.currentData()
            self._records = list_memories(kind, limit=200)
            previous = self.category_filter.currentData()
            self.category_filter.blockSignals(True)
            self.category_filter.clear()
            self.category_filter.addItem("All categories", None)
            for category in sorted({record.category for record in self._records if record.category}):
                self.category_filter.addItem(category, category)
            index = self.category_filter.findData(previous)
            self.category_filter.setCurrentIndex(max(0, index))
            self.category_filter.blockSignals(False)
            self._render_list()
            self.status.setText(f"{len(self._records)} local record(s) loaded.")
        except Exception as exc:
            self._records = []
            self._visible_records = []
            self.record_list.clear()
            self.details.setPlainText(
                "Private memory is locked or temporarily unavailable."
            )
            self.status.setText(f"Read failed safely: {type(exc).__name__}")

    def _render_list(self) -> None:
        category = self.category_filter.currentData()
        self._visible_records = [
            record for record in self._records
            if category is None or record.category == category
        ]
        self.record_list.clear()
        self.details.clear()
        for record in self._visible_records:
            category_suffix = f" · {record.category}" if record.category else ""
            self.record_list.addItem(
                f"[{record.kind}] {record.key}{category_suffix}"
            )

    def _show_selected(self, row: int) -> None:
        if row < 0 or row >= len(self._visible_records):
            self.details.clear()
            return
        import json

        record = self._visible_records[row]
        metadata = json.dumps(
            record.metadata, ensure_ascii=False, indent=2, sort_keys=True
        )
        self.details.setPlainText(
            f"Type: {record.kind}\nKey: {record.key}\nCategory: {record.category or '—'}\n"
            f"Source: {record.source}\nUpdated: {record.updated_at}\n"
            f"Expires: {record.expires_at or 'never'}\n\nValue:\n{record.value}\n\n"
            f"Metadata:\n{metadata}"
        )

    def delete_selected(self) -> None:
        row = self.record_list.currentRow()
        if row < 0 or row >= len(self._visible_records):
            self.status.setText("Select a memory record first.")
            return
        record = self._visible_records[row]
        reply = QMessageBox.question(
            self, "Delete memory record?",
            f"Permanently delete '{record.key}' from local memory?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            from core.memory_service import delete_memory

            deleted = delete_memory(record.id)
            self.refresh()
            self.status.setText(
                "Memory record deleted." if deleted else "Memory record no longer exists."
            )
        except Exception as exc:
            self.status.setText(f"Delete failed safely: {type(exc).__name__}")

    def clear_current(self) -> None:
        kind = self.kind_filter.currentData()
        label = kind or "all memory types"
        reply = QMessageBox.question(
            self, "Clear private memory?",
            f"Permanently delete {label} from local memory? This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            from core.memory_service import clear_memory

            count = clear_memory(kind)
            self.refresh()
            self.status.setText(f"Deleted {count} memory record(s).")
        except Exception as exc:
            self.status.setText(f"Clear failed safely: {type(exc).__name__}")


class TaskRecoveryDialog(QDialog):
    def __init__(self, records, dismiss_callback=None, parent=None):
        super().__init__(parent)
        self._records = tuple(records or ())
        self._dismiss_callback = dismiss_callback
        self.setWindowTitle("Task Recovery — Protected")
        self.setModal(True)
        self.setFixedSize(660, 440)
        self.setStyleSheet(f"QDialog {{ background: {C.PANEL}; color: {C.TEXT}; }}")
        root = QVBoxLayout(self)
        title = QLabel("Interrupted tasks need your review")
        title.setFont(QFont(UI_FONT, 16, QFont.Weight.DemiBold))
        root.addWidget(title)
        self.note = QLabel(
            "Misha found work that did not reach a terminal state. Nothing was "
            "automatically resumed, because repeating a completed external effect "
            "could be unsafe. Review the checkpoint and issue a fresh command if needed."
        )
        self.note.setWordWrap(True)
        self.note.setStyleSheet(f"color: {C.TEXT_MED};")
        root.addWidget(self.note)
        self.tasks = QListWidget()
        self.tasks.setAccessibleName("Interrupted task checkpoints")
        for record in self._records:
            effect = " · effectful step attempted" if record.external_effect_seen else ""
            item_text = (
                f"{record.goal[:180]}\n"
                f"{record.phase.upper()} · {record.completed_steps}/{record.total_steps} "
                f"verified steps{effect} · {record.updated_at}"
            )
            self.tasks.addItem(item_text)
            self.tasks.item(self.tasks.count() - 1).setData(
                Qt.ItemDataRole.UserRole, record.request_id
            )
        root.addWidget(self.tasks, stretch=1)
        self.status = QLabel(
            f"{len(self._records)} task checkpoint(s) are waiting for review."
        )
        self.status.setStyleSheet(f"color: {C.TEXT_MED};")
        buttons = QHBoxLayout()
        dismiss = QPushButton("Dismiss selected")
        dismiss.clicked.connect(self.dismiss_selected)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        buttons.addWidget(self.status, stretch=1)
        buttons.addWidget(dismiss)
        buttons.addWidget(close)
        root.addLayout(buttons)

    def dismiss_selected(self) -> None:
        item = self.tasks.currentItem()
        if item is None:
            self.status.setText("Select a checkpoint first.")
            return
        request_id = str(item.data(Qt.ItemDataRole.UserRole) or "")
        try:
            dismissed = bool(self._dismiss_callback and self._dismiss_callback(request_id))
        except Exception as exc:
            self.status.setText(f"Dismiss failed safely: {type(exc).__name__}")
            return
        if not dismissed:
            self.status.setText("Checkpoint was not changed.")
            return
        self.tasks.takeItem(self.tasks.row(item))
        self.status.setText("Checkpoint dismissed; no task was executed.")


class PermissionsDialog(QDialog):
    _COLORS = {
        "granted": C.GREEN,
        "denied": C.RED,
        "restricted": C.RED,
        "not_requested": C.ACC2,
        "unknown": C.TEXT_DIM,
        "not_applicable": C.TEXT_DIM,
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Misha Permissions")
        self.setModal(True)
        self.setFixedSize(560, 440)
        self._status_labels = {}
        self.setStyleSheet(f"QDialog {{ background: {C.PANEL}; color: {C.TEXT}; }}")
        root = QVBoxLayout(self)
        title = QLabel("macOS privacy permissions")
        title.setFont(QFont(UI_FONT, 15, QFont.Weight.DemiBold))
        root.addWidget(title)
        note = QLabel(
            "Misha cannot grant permissions itself. These controls only show current "
            "status or open the matching macOS Privacy & Security page."
        )
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {C.TEXT_MED};")
        root.addWidget(note)
        for key, label, detail in (
            ("microphone", "Microphone", "Hands-free voice input"),
            ("camera", "Camera", "Optional local camera analysis"),
            ("accessibility", "Accessibility", "Window text and computer control"),
            ("screen_recording", "Screen recording", "Optional visual screen capture"),
        ):
            row = QHBoxLayout()
            text = QLabel(f"{label}\n{detail}")
            text.setStyleSheet(f"color: {C.TEXT};")
            status = QLabel("CHECKING")
            status.setFont(QFont(MONO_FONT, 8, QFont.Weight.DemiBold))
            status.setMinimumWidth(108)
            status.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._status_labels[key] = status
            settings = QPushButton("Open settings")
            settings.clicked.connect(
                lambda _checked=False, permission=key: self._open_settings(permission)
            )
            row.addWidget(text, stretch=1)
            row.addWidget(status)
            row.addWidget(settings)
            root.addLayout(row)
        root.addStretch()
        footer = QHBoxLayout()
        self.message = QLabel("")
        self.message.setStyleSheet(f"color: {C.TEXT_MED};")
        refresh = QPushButton("Refresh status")
        refresh.clicked.connect(self.refresh)
        history = QPushButton("Permission history")
        history.clicked.connect(self._open_history)
        guide = QPushButton("Privacy guide")
        guide.clicked.connect(self._open_guide)
        guide.setVisible(
            parent is None or parent.__class__.__name__ != "PrivacyOnboardingDialog"
        )
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        footer.addWidget(self.message, stretch=1)
        footer.addWidget(guide)
        footer.addWidget(history)
        footer.addWidget(refresh)
        footer.addWidget(close)
        root.addLayout(footer)
        self.refresh()

    def refresh(self) -> None:
        try:
            from core.macos_permissions import get_permission_statuses

            statuses = get_permission_statuses()
            for item in statuses:
                label = self._status_labels.get(item.key)
                if label is None:
                    continue
                label.setText(item.status.replace("_", " ").upper())
                color = self._COLORS.get(item.status, C.TEXT_DIM)
                label.setStyleSheet(
                    f"color: {color}; background: {C.BG_ALT}; border: 1px solid {C.BORDER}; "
                    "border-radius: 7px; padding: 6px;"
                )
            self.message.setText("Permission status refreshed locally.")
        except Exception as exc:
            self.message.setText(f"Status check failed safely: {type(exc).__name__}")

    def _open_settings(self, permission: str) -> None:
        from core.macos_permissions import open_permission_settings

        opened = open_permission_settings(permission)
        self.message.setText(
            "macOS Privacy & Security opened. Grant access there, then refresh."
            if opened else "The matching macOS settings page could not be opened."
        )

    def _open_history(self) -> None:
        AuditLogDialog(
            self,
            category_filter="approval",
            title_text="Permission history",
        ).exec()

    def _open_guide(self) -> None:
        window = self.window()
        PrivacyOnboardingDialog(
            self,
            checks_callback=getattr(window, "on_setup_diagnostics", None),
            speaker_callback=getattr(window, "on_speaker_test", None),
            devices_callback=getattr(window, "on_audio_devices", None),
            select_devices_callback=getattr(window, "on_audio_device_select", None),
            microphone_callback=getattr(window, "on_microphone_test", None),
            wake_callback=getattr(window, "on_wake_test", None),
        ).exec()


class PrivacyOnboardingDialog(QDialog):
    def __init__(
        self,
        parent=None,
        *,
        checks_callback=None,
        speaker_callback=None,
        devices_callback=None,
        select_devices_callback=None,
        microphone_callback=None,
        wake_callback=None,
    ):
        super().__init__(parent)
        self._checks_callback = checks_callback
        self._speaker_callback = speaker_callback
        self._devices_callback = devices_callback
        self._select_devices_callback = select_devices_callback
        self._microphone_callback = microphone_callback
        self._wake_callback = wake_callback
        self.setWindowTitle("Misha Privacy Guide")
        self.setAccessibleName("Misha privacy onboarding")
        self.setModal(True)
        self.setFixedSize(620, 620)
        self.setStyleSheet(f"QDialog {{ background: {C.PANEL}; color: {C.TEXT}; }}")
        root = QVBoxLayout(self)
        title = QLabel("You stay in control")
        title.setFont(QFont(UI_FONT, 18, QFont.Weight.DemiBold))
        root.addWidget(title)
        subtitle = QLabel(
            "Misha is local-first. macOS remains the authority for every privacy "
            "permission, and observation starts OFF."
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet(f"color: {C.TEXT_MED};")
        root.addWidget(subtitle)
        for heading, body, color in (
            (
                "Microphone",
                "Used for hands-free commands. Audio and transcripts stay local; "
                "you can pause listening at any time.",
                C.PRI,
            ),
            (
                "Accessibility",
                "Required only for active-window text and approved computer control. "
                "Password managers and private-memory windows are always excluded.",
                C.ACC2,
            ),
            (
                "Screen observation",
                "Proactive observation is OFF until you explicitly enable OBSERVE. "
                "The header always shows its current state.",
                C.GREEN,
            ),
            (
                "Your data",
                "Memory is encrypted locally. You can inspect or delete individual "
                "records, clear everything, and review permission history.",
                C.ACC,
            ),
        ):
            card = QFrame()
            card.setStyleSheet(
                f"background: {C.BG_ALT}; border: 1px solid {C.BORDER}; border-radius: 9px;"
            )
            layout = QVBoxLayout(card)
            label = QLabel(heading)
            label.setFont(QFont(UI_FONT, 11, QFont.Weight.DemiBold))
            label.setStyleSheet(f"color: {color}; border: none;")
            description = QLabel(body)
            description.setWordWrap(True)
            description.setStyleSheet(f"color: {C.TEXT_MED}; border: none;")
            layout.addWidget(label)
            layout.addWidget(description)
            root.addWidget(card)
        choices = QFrame()
        choices.setStyleSheet(
            f"background: {C.BG_ALT}; border: 1px solid {C.BORDER}; border-radius: 9px;"
        )
        choice_layout = QVBoxLayout(choices)
        choice_title = QLabel("Optional local integrations (both default OFF)")
        choice_title.setStyleSheet(f"color: {C.WHITE}; border: none;")
        self.screen_opt_in = QCheckBox("Enable proactive screen observation after setup")
        self.screen_opt_in.setAccessibleName("Enable proactive screen observation")
        self.screen_opt_in.setChecked(False)
        self.ide_opt_in = QCheckBox("Enable authenticated local IDE context after restart")
        self.ide_opt_in.setAccessibleName("Enable local IDE context server")
        self.ide_opt_in.setChecked(False)
        choice_layout.addWidget(choice_title)
        choice_layout.addWidget(self.screen_opt_in)
        choice_layout.addWidget(self.ide_opt_in)
        root.addWidget(choices)
        example = QLabel('First command to try: “Misha, bugün için güvenli bir plan hazırla.”')
        example.setAccessibleName("First Misha example command")
        example.setWordWrap(True)
        example.setStyleSheet(f"color: {C.PRI};")
        root.addWidget(example)
        root.addStretch()
        buttons = QHBoxLayout()
        permissions = QPushButton("Review permissions")
        permissions.clicked.connect(self._open_permissions)
        checks = QPushButton("Run setup checks")
        checks.clicked.connect(self._open_checks)
        done = QPushButton("Save choices and continue")
        done.setStyleSheet(
            f"color: {C.BG}; background: {C.PRI}; border-radius: 8px; padding: 9px 14px;"
        )
        done.clicked.connect(self.accept)
        buttons.addWidget(permissions)
        buttons.addWidget(checks)
        buttons.addStretch()
        buttons.addWidget(done)
        root.addLayout(buttons)

    def opt_in_values(self) -> tuple[bool, bool]:
        return self.screen_opt_in.isChecked(), self.ide_opt_in.isChecked()

    def _open_permissions(self) -> None:
        PermissionsDialog(self).exec()

    def _open_checks(self) -> None:
        SetupChecksDialog(
            self,
            checks_callback=self._checks_callback,
            speaker_callback=self._speaker_callback,
            devices_callback=self._devices_callback,
            select_devices_callback=self._select_devices_callback,
            microphone_callback=self._microphone_callback,
            wake_callback=self._wake_callback,
        ).exec()


class SetupChecksDialog(QDialog):
    _results_sig = pyqtSignal(object)
    _message_sig = pyqtSignal(bool, str)
    _devices_sig = pyqtSignal(object)

    def __init__(
        self,
        parent=None,
        *,
        checks_callback=None,
        speaker_callback=None,
        devices_callback=None,
        select_devices_callback=None,
        microphone_callback=None,
        wake_callback=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Misha Setup Checks")
        self.setModal(True)
        self.setFixedSize(720, 650)
        self._checks_callback = checks_callback
        self._speaker_callback = speaker_callback
        self._devices_callback = devices_callback
        self._select_devices_callback = select_devices_callback
        self._microphone_callback = microphone_callback
        self._wake_callback = wake_callback
        self._labels = {}
        self.setStyleSheet(f"QDialog {{ background: {C.PANEL}; color: {C.TEXT}; }}")
        root = QVBoxLayout(self)
        title = QLabel("Local setup readiness")
        title.setFont(QFont(UI_FONT, 16, QFont.Weight.DemiBold))
        root.addWidget(title)
        note = QLabel(
            "These checks stay on this Mac. They validate readiness without recording "
            "or uploading audio."
        )
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {C.TEXT_MED};")
        root.addWidget(note)
        device_row = QHBoxLayout()
        self.input_device = QComboBox()
        self.input_device.addItem("Loading microphones…", None)
        self.output_device = QComboBox()
        self.output_device.addItem("Loading speakers…", None)
        save_devices = QPushButton("Save devices")
        save_devices.clicked.connect(self.save_devices)
        device_row.addWidget(self.input_device, stretch=2)
        device_row.addWidget(self.output_device, stretch=2)
        device_row.addWidget(save_devices)
        root.addLayout(device_row)
        for key, label in (
            ("local_ai", "Local intelligence"),
            ("speech_recognition", "Offline speech recognition"),
            ("owner_voice", "Owner voice profile"),
            ("microphone", "Microphone"),
            ("speaker", "Speaker and local TTS"),
            ("wake_word", "Wake-word pipeline"),
        ):
            row = QHBoxLayout()
            name = QLabel(label)
            name.setStyleSheet(f"color: {C.TEXT};")
            status = QLabel("NOT CHECKED")
            status.setFont(QFont(MONO_FONT, 8, QFont.Weight.DemiBold))
            status.setAlignment(Qt.AlignmentFlag.AlignCenter)
            status.setMinimumWidth(110)
            message = QLabel("")
            message.setWordWrap(True)
            message.setStyleSheet(f"color: {C.TEXT_MED};")
            self._labels[key] = (status, message)
            row.addWidget(name, stretch=2)
            row.addWidget(status)
            row.addWidget(message, stretch=4)
            root.addLayout(row)
        root.addStretch()
        self.summary = QLabel("Run checks to validate local setup.")
        self.summary.setStyleSheet(f"color: {C.TEXT_MED};")
        root.addWidget(self.summary)
        buttons = QHBoxLayout()
        run = QPushButton("Run checks")
        run.clicked.connect(self.run_checks)
        speaker = QPushButton("Test speaker")
        speaker.clicked.connect(self.test_speaker)
        microphone = QPushButton("Test microphone")
        microphone.clicked.connect(self.test_microphone)
        wake = QPushButton("Test “Misha”")
        wake.clicked.connect(self.test_wake)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        self._run_button = run
        buttons.addWidget(run)
        buttons.addWidget(speaker)
        buttons.addWidget(microphone)
        buttons.addWidget(wake)
        buttons.addStretch()
        buttons.addWidget(close)
        root.addLayout(buttons)
        self._results_sig.connect(self._apply_results)
        self._message_sig.connect(self._apply_message)
        self._devices_sig.connect(self._apply_devices)
        QTimer.singleShot(0, self.load_devices)
        QTimer.singleShot(0, self.run_checks)

    def load_devices(self) -> None:
        if not self._devices_callback:
            self._apply_message(False, "Audio device discovery is not connected yet.")
            return

        def worker():
            try:
                self._devices_sig.emit(self._devices_callback())
            except Exception as exc:
                self._message_sig.emit(False, f"Device discovery failed: {type(exc).__name__}")

        threading.Thread(target=worker, daemon=True).start()

    def _apply_devices(self, devices) -> None:
        self.input_device.clear()
        self.output_device.clear()
        for item in devices.get("inputs", []):
            suffix = " — default" if item.get("default") else ""
            self.input_device.addItem(f"Mic: {item['name']}{suffix}", item["index"])
        for item in devices.get("outputs", []):
            suffix = " — default" if item.get("default") else ""
            self.output_device.addItem(f"Speaker: {item['name']}{suffix}", item["index"])
        if not devices.get("inputs"):
            self.input_device.addItem("No compatible microphone", None)
        if not devices.get("outputs"):
            self.output_device.addItem("No compatible speaker", None)

    def save_devices(self) -> None:
        if not self._select_devices_callback:
            self._apply_message(False, "Audio device selection is not connected yet.")
            return
        input_index = self.input_device.currentData()
        output_index = self.output_device.currentData()
        self._run_simple_callback(
            lambda: self._select_devices_callback(input_index, output_index)
        )

    def run_checks(self) -> None:
        if not self._checks_callback:
            self.summary.setText("Setup diagnostics are not connected yet.")
            return
        self._run_button.setEnabled(False)
        self.summary.setText("Checking local components…")

        def worker():
            try:
                self._results_sig.emit(tuple(self._checks_callback()))
            except Exception as exc:
                self._message_sig.emit(False, f"Checks failed safely: {type(exc).__name__}")

        threading.Thread(target=worker, daemon=True).start()

    def _apply_results(self, checks) -> None:
        from core.setup_diagnostics import setup_is_ready
        from memory.config_manager import set_config

        for check in checks:
            pair = self._labels.get(check.key)
            if pair is None:
                continue
            status, message = pair
            status.setText("READY" if check.ready else "ACTION NEEDED")
            color = C.GREEN if check.ready else C.ACC2
            status.setStyleSheet(
                f"color: {color}; background: {C.BG_ALT}; border: 1px solid {C.BORDER}; "
                "border-radius: 7px; padding: 5px;"
            )
            message.setText(check.message)
        ready = setup_is_ready(tuple(checks))
        self.summary.setText(
            "Setup complete — all required local components are ready."
            if ready else "Setup is incomplete — review the ACTION NEEDED rows."
        )
        self.summary.setStyleSheet(f"color: {C.GREEN if ready else C.ACC2};")
        set_config("setup_validation_completed", "1" if ready else "0")
        self._run_button.setEnabled(True)

    def test_speaker(self) -> None:
        if not self._speaker_callback:
            self.summary.setText("Speaker test is not connected yet.")
            return

        self._run_simple_callback(self._speaker_callback)

    def test_microphone(self) -> None:
        if not self._microphone_callback:
            self._apply_message(False, "Microphone test is not connected yet.")
            return
        self.summary.setText("Speak normally for two seconds…")
        self._run_simple_callback(self._microphone_callback)

    def test_wake(self) -> None:
        if not self._wake_callback:
            self._apply_message(False, "Wake-word test is not connected yet.")
            return
        self.summary.setText('Say “Misha” clearly after the listener starts…')
        self._run_simple_callback(self._wake_callback)

    def _run_simple_callback(self, callback) -> None:
        def worker():
            try:
                ok, message = callback()
                self._message_sig.emit(bool(ok), str(message)[:240])
            except Exception as exc:
                self._message_sig.emit(False, f"Test failed safely: {type(exc).__name__}")

        threading.Thread(target=worker, daemon=True).start()

    def _apply_message(self, ok: bool, message: str) -> None:
        self.summary.setText(message)
        self.summary.setStyleSheet(f"color: {C.GREEN if ok else C.ACC2};")
        self._run_button.setEnabled(True)


class MainWindow(QMainWindow):
    _log_sig   = pyqtSignal(str)
    _state_sig = pyqtSignal(str)
    _wake_feedback_sig = pyqtSignal()
    _voice_status_sig = pyqtSignal(bool, str)
    _microphone_muted_sig = pyqtSignal(bool)
    _vad_sensitivity_sig = pyqtSignal(str)
    _proactive_status_sig = pyqtSignal(bool)
    _task_recovery_sig = pyqtSignal(object, object)
    _approval_sig = pyqtSignal(str, object)

    def __init__(self, face_path: str):
        super().__init__()
        from memory.config_manager import get_config

        self.setWindowTitle("M.I.S.H.A")
        self.setAccessibleName("Misha personal assistant")
        self._always_on_top = (get_config("always_on_top") or "1").strip().lower() not in {
            "0", "false", "no", "off",
        }
        self._apply_window_flags()
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self.setMinimumSize(_MIN_W, _MIN_H)
        self.resize(_DEFAULT_W, _DEFAULT_H)

        self._restore_window_position(get_config("window_position"))

        self.on_text_command  = None
        self.on_voice_toggle = None
        self.on_voice_command = None
        self.on_vad_sensitivity_change = None
        self.on_proactive_toggle = None
        self.on_proactive_settings_change = None
        self.on_setup_diagnostics = None
        self.on_speaker_test = None
        self.on_audio_devices = None
        self.on_audio_device_select = None
        self.on_microphone_test = None
        self.on_wake_test = None
        self._muted           = False
        self._vad_sensitivity = "normal"
        self._voice_available = False
        self._voice_status_message = "Local voice setup is required."
        self._proactive_enabled = False
        self._current_file: str | None = None
        self._drag_origin = None
        self._allow_close = False
        self._position_save_timer = QTimer(self)
        self._position_save_timer.setSingleShot(True)
        self._position_save_timer.timeout.connect(self._save_window_position)

        central = QWidget()
        central.setObjectName("appRoot")
        central.setStyleSheet(f"""
            QWidget#appRoot {{
                background: {C.BG};
                border-radius: 18px;
                border: 1px solid {C.BORDER_B};
            }}
            QToolTip {{
                color: {C.WHITE}; background: {C.PANEL_HI};
                border: 1px solid {C.BORDER_B}; padding: 6px;
            }}
        """)
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 10)
        root.setSpacing(10)
        root.addWidget(self._build_header())

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(10)

        self._left_panel = self._build_left_panel()
        body.addWidget(self._left_panel, stretch=0)

        body.addWidget(self._build_center_panel(face_path), stretch=5)

        self._right_panel = self._build_right_panel()
        body.addWidget(self._right_panel, stretch=0)

        root.addLayout(body, stretch=1)
        root.addWidget(self._build_footer())
        self._apply_accessibility_metadata()

        self._clock_tmr = QTimer(self)
        self._clock_tmr.timeout.connect(self._tick_clock)
        self._clock_tmr.start(1000)
        self._tick_clock()

        # Metrik güncelleme timer'ı
        self._metric_tmr = QTimer(self)
        self._metric_tmr.timeout.connect(self._update_metrics)
        self._metric_tmr.start(2000)
        self._update_metrics()

        self._log_sig.connect(self._log.append_log)
        self._state_sig.connect(self._apply_state)
        self._wake_feedback_sig.connect(self._show_wake_feedback)
        self._voice_status_sig.connect(self._apply_voice_status)
        self._microphone_muted_sig.connect(
            lambda muted: self._set_microphone_muted(bool(muted), notify=False)
        )
        self._vad_sensitivity_sig.connect(self._apply_vad_sensitivity)
        self._proactive_status_sig.connect(self._apply_proactive_status)
        self._task_recovery_sig.connect(self._show_task_recovery)
        self._approval_sig.connect(self._show_approval_dialog)

        self._overlay: SetupOverlay | None = None
        self._ready = self._check_config()
        if not self._ready:
            self._show_setup()
        else:
            self._schedule_privacy_onboarding()

        sc_mute = QShortcut(QKeySequence("F4"), self)
        sc_mute.activated.connect(self._toggle_mute)
        sc_full = QShortcut(QKeySequence("F11"), self)
        sc_full.activated.connect(self._toggle_fullscreen)

    def _show_task_recovery(self, records, dismiss_callback) -> None:
        if not records:
            return
        TaskRecoveryDialog(records, dismiss_callback, self).exec()

    def _show_approval_dialog(self, message: str, result_future) -> None:
        """Display an exact-target approval on the Qt thread; failures deny safely."""
        approved = False
        try:
            self.show()
            self.activateWindow()
            reply = QMessageBox.question(
                self,
                "Misha — Approval required",
                str(message)[:4_000],
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            approved = reply == QMessageBox.StandardButton.Yes
        except Exception:
            approved = False
        if not result_future.done():
            result_future.set_result(approved)

    def _apply_window_flags(self) -> None:
        flags = Qt.WindowType.FramelessWindowHint
        if self._always_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)

    def set_always_on_top(self, enabled: bool) -> None:
        from memory.config_manager import set_config

        enabled = bool(enabled)
        if enabled == self._always_on_top:
            return
        visible = self.isVisible()
        self._always_on_top = enabled
        self._apply_window_flags()
        set_config("always_on_top", "1" if enabled else "0")
        if visible:
            self.show()
            self.raise_()

    def _restore_window_position(self, stored: str | None) -> None:
        import json

        point = None
        try:
            payload = json.loads(stored) if stored else {}
            point = (int(payload["x"]), int(payload["y"]))
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            point = None
        screens = QApplication.screens()
        if point is not None:
            candidate = QRectF(point[0], point[1], 80, 80)
            if any(QRectF(screen.availableGeometry()).intersects(candidate) for screen in screens):
                self.move(*point)
                return
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(
            screen.x() + max(0, (screen.width() - _DEFAULT_W) // 2),
            screen.y() + max(0, (screen.height() - _DEFAULT_H) // 2),
        )

    def _save_window_position(self) -> None:
        import json
        from memory.config_manager import set_config

        if self.isFullScreen() or self.isMaximized():
            return
        set_config(
            "window_position",
            json.dumps({"x": self.x(), "y": self.y()}, separators=(",", ":")),
        )

    def moveEvent(self, event):
        super().moveEvent(event)
        if hasattr(self, "_position_save_timer"):
            self._position_save_timer.start(350)

    def closeEvent(self, event):
        if self._allow_close:
            self._save_window_position()
            event.accept()
            return
        event.ignore()
        self.hide()

    def _toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_origin = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_origin is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_origin)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_origin = None
        super().mouseReleaseEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._overlay and self._overlay.isVisible():
            ow, oh = 520, 430
            cw = self.centralWidget()
            self._overlay.setGeometry(
                (cw.width()  - ow) // 2,
                (cw.height() - oh) // 2,
                ow, oh,
            )

    def _update_metrics(self):
        snap = _metrics.snapshot()

        # CPU
        cpu = snap["cpu"]
        self._bar_cpu.set_value(cpu, f"{cpu:.0f}%")

        # MEM
        mem = snap["mem"]
        self._bar_mem.set_value(mem, f"{mem:.0f}%")

        # NET
        net = snap["net"]
        if net < 1.0:
            net_str = f"{net*1024:.0f}KB/s"
        else:
            net_str = f"{net:.1f}MB/s"
        net_pct = min(100, net * 10)  # 10 MB/s = %100
        self._bar_net.set_value(net_pct, net_str)

        # GPU
        gpu = snap["gpu"]
        if gpu >= 0:
            self._bar_gpu.set_value(gpu, f"{gpu:.0f}%")
        else:
            self._bar_gpu.set_value(0, "N/A")

        # TMP
        tmp = snap["tmp"]
        if tmp >= 0:
            tmp_pct = min(100, (tmp / 100) * 100)
            self._bar_tmp.set_value(tmp_pct, f"{tmp:.0f}°C")
        else:
            self._bar_tmp.set_value(0, "N/A")

        try:
            boot_t  = psutil.boot_time()
            elapsed = time.time() - boot_t
            h = int(elapsed // 3600)
            m = int((elapsed % 3600) // 60)
            self._uptime_lbl.setText(f"UP  {h:02d}:{m:02d}")
        except Exception:
            self._uptime_lbl.setText("UP  --:--")

        try:
            proc_count = len(psutil.pids())
            self._proc_lbl.setText(f"PROC  {proc_count}")
        except Exception:
            self._proc_lbl.setText("PROC  --")


    def _build_header(self) -> QWidget:
        w = QWidget()
        w.setFixedHeight(66)
        w.setStyleSheet(
            f"background: {C.PANEL}; border: 1px solid {C.BORDER}; border-radius: 12px;"
        )
        lay = QHBoxLayout(w)
        lay.setContentsMargins(18, 0, 12, 0)
        lay.setSpacing(12)

        mark = QLabel("M")
        mark.setFixedSize(38, 38)
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark.setFont(QFont(UI_FONT, 15, QFont.Weight.Bold))
        mark.setStyleSheet(
            f"color: {C.BG}; background: {C.PRI}; border: none; border-radius: 19px;"
        )
        lay.addWidget(mark)

        brand = QVBoxLayout(); brand.setSpacing(0)
        title = QLabel("MISHA")
        title.setFont(QFont(UI_FONT, 16, QFont.Weight.DemiBold))
        title.setStyleSheet(f"color: {C.WHITE}; background: transparent; border: none;")
        brand.addWidget(title)
        sub = QLabel("PERSONAL INTELLIGENCE")
        sub.setFont(QFont(MONO_FONT, 7, QFont.Weight.Medium))
        sub.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent; border: none;")
        brand.addWidget(sub)
        lay.addLayout(brand)
        lay.addStretch()

        self._proactive_btn = QPushButton("◉  OBSERVE OFF")
        self._proactive_btn.setAccessibleName("Toggle proactive observation")
        self._proactive_btn.setToolTip(
            "Local proactive observation; protected apps and credentials are excluded."
        )
        self._proactive_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._proactive_btn.setFont(QFont(MONO_FONT, 8, QFont.Weight.DemiBold))
        self._proactive_btn.setFixedHeight(30)
        self._proactive_btn.setMinimumWidth(132)
        self._proactive_btn.clicked.connect(self._toggle_proactive)
        self._apply_proactive_status(False)
        lay.addWidget(self._proactive_btn)

        self._header_state = QLabel("●  INITIALISING")
        self._header_state.setAccessibleName("Misha runtime state")
        self._header_state.setFont(QFont(UI_FONT, 9, QFont.Weight.DemiBold))
        self._header_state.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._header_state.setFixedHeight(30)
        self._header_state.setMinimumWidth(126)
        self._header_state.setStyleSheet(
            f"color: {C.PRI}; background: {C.PRI_GHO}; border: 1px solid {C.BORDER_A}; "
            "border-radius: 15px; padding: 0 12px;"
        )
        lay.addWidget(self._header_state)

        right_col = QVBoxLayout(); right_col.setSpacing(0)
        self._clock_lbl = QLabel("00:00:00")
        self._clock_lbl.setFont(QFont(MONO_FONT, 12, QFont.Weight.DemiBold))
        self._clock_lbl.setStyleSheet(f"color: {C.WHITE}; background: transparent; border: none;")
        self._clock_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        right_col.addWidget(self._clock_lbl)
        self._date_lbl = QLabel("")
        self._date_lbl.setFont(QFont(UI_FONT, 7))
        self._date_lbl.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent; border: none;")
        self._date_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        right_col.addWidget(self._date_lbl)
        lay.addLayout(right_col)

        for label, accessible_name, handler, hover in [
            ("—", "Minimize Misha", self.showMinimized, C.ACC),
            ("×", "Hide Misha", self.close, C.RED),
        ]:
            btn = QPushButton(label)
            btn.setAccessibleName(accessible_name)
            btn.setFixedSize(30, 30)
            btn.setFont(QFont(UI_FONT, 13, QFont.Weight.DemiBold))
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(f"""
                QPushButton {{ color: {C.TEXT_MED}; background: transparent;
                    border: none; border-radius: 8px; }}
                QPushButton:hover {{ color: {hover}; background: {C.PANEL_HI}; }}
            """)
            btn.clicked.connect(handler)
            lay.addWidget(btn)
        return w

    def _build_center_panel(self, face_path: str) -> QWidget:
        panel = QWidget()
        panel.setStyleSheet(
            f"background: {C.BG_ALT}; border: 1px solid {C.BORDER}; border-radius: 12px;"
        )
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setSpacing(8)

        top = QHBoxLayout()
        title_col = QVBoxLayout(); title_col.setSpacing(1)
        self._hero_title = QLabel("Ready when you are")
        self._hero_title.setFont(QFont(UI_FONT, 16, QFont.Weight.DemiBold))
        self._hero_title.setStyleSheet(f"color: {C.WHITE}; background: transparent; border: none;")
        title_col.addWidget(self._hero_title)
        self._hero_subtitle = QLabel("Type a command — private local voice is being prepared")
        self._hero_subtitle.setFont(QFont(UI_FONT, 9))
        self._hero_subtitle.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent; border: none;")
        title_col.addWidget(self._hero_subtitle)
        top.addLayout(title_col)
        top.addStretch()
        privacy = QLabel("◉  PRIVATE SESSION")
        privacy.setFont(QFont(MONO_FONT, 7, QFont.Weight.DemiBold))
        privacy.setStyleSheet(
            f"color: {C.GREEN}; background: #10251F; border: 1px solid #1D4B3B; "
            "border-radius: 9px; padding: 6px 9px;"
        )
        top.addWidget(privacy)
        lay.addLayout(top)

        self.hud = HudCanvas(face_path)
        self.hud.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        lay.addWidget(self.hud, stretch=1)

        hint = QLabel("QUICK START")
        hint.setFont(QFont(MONO_FONT, 7, QFont.Weight.DemiBold))
        hint.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent; border: none;")
        lay.addWidget(hint)
        prompts = QHBoxLayout(); prompts.setSpacing(7)
        for label, command in [
            ("Summarize my screen", "Ekranımda ne olduğunu özetle"),
            ("Plan my day", "Bugün yapacaklarımı planla"),
            ("Open a workspace", "Çalışma alanımı aç"),
        ]:
            btn = QPushButton(label)
            btn.setFixedHeight(34)
            btn.setFont(QFont(UI_FONT, 8, QFont.Weight.Medium))
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(f"""
                QPushButton {{ color: {C.TEXT_MED}; background: {C.PANEL};
                    border: 1px solid {C.BORDER}; border-radius: 9px; padding: 0 10px; }}
                QPushButton:hover {{ color: {C.WHITE}; border: 1px solid {C.PRI_DIM};
                    background: {C.PANEL_HI}; }}
            """)
            btn.clicked.connect(lambda _, text=command: self._use_prompt(text))
            prompts.addWidget(btn)
        lay.addLayout(prompts)
        return panel

    def _use_prompt(self, text: str):
        self._input.setText(text)
        self._input.setFocus()

    def _tick_clock(self):
        self._clock_lbl.setText(time.strftime("%H:%M:%S"))
        self._date_lbl.setText(time.strftime("%a %d %b %Y"))

    def _build_left_panel(self) -> QWidget:
        w = QWidget()
        w.setFixedWidth(_LEFT_W)
        w.setStyleSheet(
            f"background: {C.PANEL}; border: 1px solid {C.BORDER}; border-radius: 12px;"
        )
        lay = QVBoxLayout(w)
        lay.setContentsMargins(14, 16, 14, 14)
        lay.setSpacing(8)

        eyebrow = QLabel("OVERVIEW")
        eyebrow.setFont(QFont(MONO_FONT, 7, QFont.Weight.DemiBold))
        eyebrow.setStyleSheet(f"color: {C.PRI_DIM}; background: transparent; border: none;")
        lay.addWidget(eyebrow)

        hdr = QLabel("System health")
        hdr.setFont(QFont(UI_FONT, 14, QFont.Weight.DemiBold))
        hdr.setStyleSheet(f"color: {C.WHITE}; background: transparent; border: none;")
        lay.addWidget(hdr)

        online = QLabel("●  All systems operational")
        online.setFont(QFont(UI_FONT, 8, QFont.Weight.Medium))
        online.setStyleSheet(
            f"color: {C.GREEN}; background: #10251F; border: 1px solid #1D4B3B; "
            "border-radius: 8px; padding: 7px 8px;"
        )
        lay.addWidget(online)
        lay.addSpacing(4)

        self._bar_cpu = MetricBar("CPU", C.PRI)
        self._bar_mem = MetricBar("MEM", C.ACC2)
        self._bar_net = MetricBar("NET", C.GREEN)
        self._bar_gpu = MetricBar("GPU", C.ACC)
        self._bar_tmp = MetricBar("TMP", "#ff6688")

        for bar in [self._bar_cpu, self._bar_mem, self._bar_net,
                    self._bar_gpu, self._bar_tmp]:
            lay.addWidget(bar)

        lay.addSpacing(6)

        info_panel = QWidget()
        info_panel.setStyleSheet(
            f"background: {C.BG_ALT}; border: 1px solid {C.BORDER}; border-radius: 9px;"
        )
        ip_lay = QVBoxLayout(info_panel)
        ip_lay.setContentsMargins(6, 5, 6, 5)
        ip_lay.setSpacing(3)

        self._uptime_lbl = QLabel("UP  --:--")
        self._uptime_lbl.setFont(QFont(MONO_FONT, 8, QFont.Weight.DemiBold))
        self._uptime_lbl.setStyleSheet(f"color: {C.GREEN}; background: transparent; border: none;")
        ip_lay.addWidget(self._uptime_lbl)

        self._proc_lbl = QLabel("PROC  --")
        self._proc_lbl.setFont(QFont(MONO_FONT, 8))
        self._proc_lbl.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent; border: none;")
        ip_lay.addWidget(self._proc_lbl)

        os_name = {"Windows": "WIN", "Darwin": "macOS", "Linux": "LINUX"}.get(_OS, _OS.upper())
        os_lbl = QLabel(f"OS  {os_name}")
        os_lbl.setFont(QFont(MONO_FONT, 8))
        os_lbl.setStyleSheet(f"color: {C.ACC2}; background: transparent; border: none;")
        ip_lay.addWidget(os_lbl)

        lay.addWidget(info_panel)
        lay.addStretch()

        section = QLabel("CAPABILITIES")
        section.setFont(QFont(MONO_FONT, 7, QFont.Weight.DemiBold))
        section.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent; border: none;")
        lay.addWidget(section)
        for txt, col in [
            ("◉  Voice interface", C.PRI),
            ("◇  Vision context", C.ACC),
            ("□  Secure actions", C.GREEN),
        ]:
            lbl = QLabel(txt)
            lbl.setFont(QFont(UI_FONT, 9, QFont.Weight.Medium))
            lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            lbl.setStyleSheet(
                f"color: {col}; background: {C.BG_ALT};"
                f"border: 1px solid {C.BORDER}; border-radius: 8px; padding: 8px;"
            )
            lay.addWidget(lbl)

        return w
    def _build_right_panel(self) -> QWidget:
        w = QWidget()
        w.setFixedWidth(_RIGHT_W)
        w.setStyleSheet(
            f"background: {C.PANEL}; border: 1px solid {C.BORDER}; border-radius: 12px;"
        )
        lay = QVBoxLayout(w)
        lay.setContentsMargins(14, 16, 14, 14)
        lay.setSpacing(9)

        def _sec(txt):
            l = QLabel(txt)
            l.setFont(QFont(UI_FONT, 11, QFont.Weight.DemiBold))
            l.setStyleSheet(f"color: {C.WHITE}; background: transparent; border: none;")
            return l

        activity_head = QHBoxLayout()
        activity_head.addWidget(_sec("Live activity"))
        activity_head.addStretch()
        live = QLabel("● LIVE")
        live.setFont(QFont(MONO_FONT, 7, QFont.Weight.DemiBold))
        live.setStyleSheet(f"color: {C.GREEN}; background: transparent; border: none;")
        activity_head.addWidget(live)
        lay.addLayout(activity_head)
        self._log = LogWidget()
        lay.addWidget(self._log, stretch=1)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER}; margin: 2px 0;")
        lay.addWidget(sep)

        lay.addWidget(_sec("Context file"))
        self._drop_zone = FileDropZone()
        self._drop_zone.file_selected.connect(self._on_file_selected)
        lay.addWidget(self._drop_zone)

        self._file_hint = QLabel("Drop a file to give Misha extra context")
        self._file_hint.setFont(QFont(UI_FONT, 8))
        self._file_hint.setStyleSheet(
            f"color: {C.TEXT_MED}; background: transparent; border: none;"
        )
        self._file_hint.setWordWrap(True)
        lay.addWidget(self._file_hint)

        sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet(f"color: {C.BORDER}; margin: 2px 0;")
        lay.addWidget(sep2)

        lay.addWidget(_sec("Ask Misha"))
        lay.addLayout(self._build_input_row())

        self._mute_btn = QPushButton("🎙  MICROPHONE ACTIVE")
        self._mute_btn.setAccessibleName("Toggle microphone mute")
        self._mute_btn.setFixedHeight(38)
        self._mute_btn.setFont(QFont(UI_FONT, 9, QFont.Weight.DemiBold))
        self._mute_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._mute_btn.clicked.connect(self._toggle_mute)
        self._style_mute_btn()
        lay.addWidget(self._mute_btn)

        self._vad_btn = QPushButton("◫  VOICE SENSITIVITY: NORMAL")
        self._vad_btn.setAccessibleName("Change voice sensitivity")
        self._vad_btn.setFixedHeight(34)
        self._vad_btn.setFont(QFont(UI_FONT, 8, QFont.Weight.Medium))
        self._vad_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._vad_btn.clicked.connect(self._cycle_vad_sensitivity)
        self._style_vad_sensitivity_btn()
        lay.addWidget(self._vad_btn)

        self._talk_btn = QPushButton("VOICE MODEL NOT READY")
        self._talk_btn.setAccessibleName("Voice service status")
        self._talk_btn.setFixedHeight(38)
        self._talk_btn.setFont(QFont(UI_FONT, 9, QFont.Weight.DemiBold))
        self._talk_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._talk_btn.setEnabled(False)
        self._talk_btn.clicked.connect(self._capture_voice_command)
        lay.addWidget(self._talk_btn)

        privacy_btn = QPushButton("⌾  PRIVACY & OBSERVATION")
        privacy_btn.setAccessibleName("Open privacy and observation settings")
        privacy_btn.setFixedHeight(34)
        privacy_btn.setFont(QFont(UI_FONT, 8, QFont.Weight.Medium))
        privacy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        privacy_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.TEXT_MED};
                border: 1px solid {C.BORDER}; border-radius: 9px;
            }}
            QPushButton:hover {{ color: {C.GREEN}; border-color: {C.GREEN_D}; }}
        """)
        privacy_btn.clicked.connect(self._open_proactive_settings)
        self._privacy_btn = privacy_btn
        lay.addWidget(privacy_btn)

        accessibility_btn = QPushButton("Aa  ACCESSIBILITY")
        accessibility_btn.setAccessibleName("Open accessibility settings")
        accessibility_btn.setFixedHeight(34)
        accessibility_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        accessibility_btn.setStyleSheet(f"""
            QPushButton {{ color: {C.TEXT_MED}; background: transparent;
                border: 1px solid {C.BORDER}; border-radius: 9px; }}
            QPushButton:hover {{ color: {C.ACC2}; border-color: {C.ACC2}; }}
        """)
        accessibility_btn.clicked.connect(self._open_accessibility_settings)
        self._accessibility_btn = accessibility_btn
        lay.addWidget(accessibility_btn)

        model_btn = QPushButton("◇  LOCAL MODEL")
        model_btn.setAccessibleName("Open local model settings")
        model_btn.setFixedHeight(34)
        model_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        model_btn.clicked.connect(self._open_model_settings)
        self._model_btn = model_btn
        lay.addWidget(model_btn)

        settings_btn = QPushButton("⚙  SETTINGS CENTER")
        settings_btn.setAccessibleName("Open settings center")
        settings_btn.setFixedHeight(34)
        settings_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        settings_btn.clicked.connect(self._open_settings_center)
        self._settings_btn = settings_btn
        lay.addWidget(settings_btn)

        fs_btn = QPushButton("⛶  FULLSCREEN  [F11]")
        fs_btn.setAccessibleName("Toggle fullscreen")
        fs_btn.setFixedHeight(34)
        fs_btn.setFont(QFont(UI_FONT, 8, QFont.Weight.Medium))
        fs_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        fs_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.TEXT_MED};
                border: 1px solid {C.BORDER}; border-radius: 9px;
            }}
            QPushButton:hover {{
                color: {C.PRI}; border: 1px solid {C.BORDER_B};
            }}
        """)
        fs_btn.clicked.connect(self._toggle_fullscreen)
        lay.addWidget(fs_btn)

        return w

    def _build_input_row(self) -> QHBoxLayout:
        row = QHBoxLayout(); row.setSpacing(7)
        self._input = QLineEdit()
        self._input.setAccessibleName("Text command")
        self._input.setPlaceholderText("Type a command…")
        self._input.setFont(QFont(UI_FONT, 9))
        self._input.setFixedHeight(40)
        self._input.setStyleSheet(f"""
            QLineEdit {{
                background: {C.BG_ALT}; color: {C.WHITE};
                border: 1px solid {C.BORDER}; border-radius: 10px; padding: 4px 12px;
            }}
            QLineEdit:focus {{ border: 1px solid {C.PRI_DIM}; background: {C.PANEL2}; }}
        """)
        self._input.returnPressed.connect(self._send)
        row.addWidget(self._input)

        send = QPushButton("↑")
        send.setAccessibleName("Send text command")
        send.setFixedSize(40, 40)
        send.setFont(QFont(UI_FONT, 13, QFont.Weight.Bold))
        send.setCursor(Qt.CursorShape.PointingHandCursor)
        send.setStyleSheet(f"""
            QPushButton {{
                background: {C.PRI}; color: {C.BG};
                border: none; border-radius: 10px;
            }}
            QPushButton:hover {{ background: {C.WHITE}; }}
        """)
        send.clicked.connect(self._send)
        row.addWidget(send)
        return row

    def _apply_accessibility_metadata(self) -> None:
        """Give every interactive control a stable spoken label and keyboard focus."""
        for button in self.findChildren(QPushButton):
            if not button.accessibleName().strip():
                label = " ".join(button.text().split()).strip("◉●◫⌾⛶→↑—× ")
                button.setAccessibleName(label or "Misha action")
            button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        for field in self.findChildren(QLineEdit):
            if not field.accessibleName().strip():
                field.setAccessibleName(field.placeholderText().strip() or "Misha text field")
            field.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def _build_footer(self) -> QWidget:
        w = QWidget()
        w.setFixedHeight(28)
        w.setStyleSheet("background: transparent; border: none;")
        lay = QHBoxLayout(w); lay.setContentsMargins(6, 0, 6, 0)

        def _fl(txt, color=C.TEXT_MED):
            l = QLabel(txt); l.setFont(QFont(UI_FONT, 7))
            l.setStyleSheet(f"color: {color}; background: transparent; border: none;")
            return l

        lay.addWidget(_fl("F4  Mute    F11  Fullscreen"))
        lay.addStretch()
        lay.addWidget(_fl("Private by design  ·  Actions require approval", C.GREEN_D))
        lay.addStretch()
        lay.addWidget(_fl("MISHA  /  2026", C.PRI_DIM))
        return w

    def _on_file_selected(self, path: str):
        self._current_file = path
        p    = Path(path)
        cat  = _file_category(p)
        icon, _ = _FILE_ICONS.get(cat, _FILE_ICONS["unknown"])
        size = _fmt_size(p.stat().st_size)
        self._file_hint.setText(f"{icon}  {p.name}  ·  {size}  ·  Tell MISHA what to do with it")
        self._log.append_log(f"FILE: {p.name} ({size}) loaded")
        if self.on_text_command:
            msg = (
                f"[FILE_UPLOADED] path={path} | name={p.name} | "
                f"type={p.suffix.lstrip('.')} | size={size} | "
                f"Briefly tell the user you can see the file '{p.name}' "
                f"({size}) has been uploaded and ask what they'd like to do with it."
            )
            threading.Thread(target=self.on_text_command, args=(msg,), daemon=True).start()

    def _toggle_proactive(self) -> None:
        if self.on_proactive_toggle:
            self.on_proactive_toggle(not self._proactive_enabled)

    def _open_proactive_settings(self) -> None:
        from memory.config_manager import (
            get_proactive_denylist,
            get_proactive_settings,
        )

        dialog = ProactiveSettingsDialog(
            get_proactive_settings(), get_proactive_denylist(), self
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            settings, denylist = dialog.values()
            if self.on_proactive_settings_change:
                self.on_proactive_settings_change(settings, denylist)

    def _open_accessibility_settings(self) -> None:
        from memory.config_manager import get_config, set_config

        try:
            scale = float(get_config("font_scale") or 1.0)
        except (TypeError, ValueError):
            scale = 1.0
        reduced = str(get_config("reduce_motion") or "0").strip().casefold() in {
            "1", "true", "yes", "on",
        }
        dialog = AccessibilitySettingsDialog(scale, reduced, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            selected_scale, selected_reduced = dialog.values()
            set_config("font_scale", f"{selected_scale:.2f}")
            set_config("reduce_motion", "1" if selected_reduced else "0")
            self._log.append_log("SYS: Accessibility settings saved; restart Misha to apply.")

    def _open_settings_center(self) -> None:
        from core.desktop_lifecycle import launch_at_login_enabled, set_launch_at_login
        from memory.config_manager import get_config, set_config

        enabled = lambda key, default=False: (get_config(key) or ("1" if default else "0")).strip().casefold() in {
            "1", "true", "yes", "on",
        }
        dialog = SettingsCenterDialog({
            "always_on_top": self._always_on_top,
            "launch_at_login": launch_at_login_enabled(),
            "hands_free": not self._muted,
            "voice_sensitivity": self._vad_sensitivity,
            "screen_observation": enabled("proactive_enabled"),
            "ide_context": enabled("ide_context_enabled"),
            "ui_language": (get_config("ui_language") or "tr").strip().casefold(),
            "response_language": (get_config("response_language") or "auto").strip().casefold(),
            "debug_logging": enabled("debug_logging"),
            "safe_mode": True,
        }, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        self.set_always_on_top(bool(values["always_on_top"]))
        try:
            startup = set_launch_at_login(bool(values["launch_at_login"]))
        except (OSError, RuntimeError, ValueError) as exc:
            self._log.append_log(f"ERR: Start-at-login setting failed safely: {type(exc).__name__}")
            startup = launch_at_login_enabled()
        persisted = {
            "launch_at_login": "1" if startup else "0",
            "hands_free_enabled": "1" if values["hands_free"] else "0",
            "vad_sensitivity": str(values["voice_sensitivity"]),
            "proactive_enabled": "1" if values["screen_observation"] else "0",
            "ide_context_enabled": "1" if values["ide_context"] else "0",
            "ui_language": str(values["ui_language"]),
            "response_language": str(values["response_language"]),
            "debug_logging": "1" if values["debug_logging"] else "0",
            "safe_mode": "1",
        }
        for key, value in persisted.items():
            set_config(key, value)
        self._set_microphone_muted(not bool(values["hands_free"]), notify=False)
        self._apply_vad_sensitivity(str(values["voice_sensitivity"]))
        if self.on_voice_toggle:
            self.on_voice_toggle(bool(values["hands_free"]))
        if self.on_vad_sensitivity_change:
            self.on_vad_sensitivity_change(str(values["voice_sensitivity"]))
        if self.on_proactive_toggle:
            self.on_proactive_toggle(bool(values["screen_observation"]))
        self._log.append_log("SYS: Settings saved. Interface language applies after restart.")

    def _open_model_settings(self) -> None:
        import json
        from memory.config_manager import get_config, save_local_ai_config

        model = (get_config("local_model") or "qwen3-coder:30b").strip()
        try:
            raw_fallbacks = json.loads(get_config("local_model_fallbacks") or "[]")
            fallbacks = [str(item) for item in raw_fallbacks] if isinstance(raw_fallbacks, list) else []
        except (TypeError, ValueError, json.JSONDecodeError):
            fallbacks = []
        try:
            context_length = int(get_config("local_context_length") or "8192")
        except (TypeError, ValueError):
            context_length = 8192
        dialog = ModelProviderSettingsDialog(model, fallbacks, context_length, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            selected_model, selected_fallbacks, selected_context = dialog.values()
            try:
                save_local_ai_config(
                    model=selected_model,
                    fallback_models=selected_fallbacks,
                    context_length=selected_context,
                )
            except ValueError as exc:
                self._log.append_log(f"ERR: Local model settings rejected: {exc}")
                return
            from core.ai.runtime import _ollama_provider

            _ollama_provider.cache_clear()
            self._log.append_log("SYS: Local model settings saved and provider cache reset.")

    def _apply_proactive_status(self, enabled: bool) -> None:
        self._proactive_enabled = bool(enabled)
        if not hasattr(self, "_proactive_btn"):
            return
        if self._proactive_enabled:
            self._proactive_btn.setText("●  OBSERVE ON")
            self._proactive_btn.setStyleSheet(f"""
                QPushButton {{
                    color: {C.ACC2}; background: #2A2110;
                    border: 1px solid #70551E; border-radius: 15px;
                    padding: 0 12px;
                }}
                QPushButton:hover {{ color: {C.WHITE}; background: #382B13; }}
            """)
        else:
            self._proactive_btn.setText("◉  OBSERVE OFF")
            self._proactive_btn.setStyleSheet(f"""
                QPushButton {{
                    color: {C.TEXT_DIM}; background: {C.PANEL2};
                    border: 1px solid {C.BORDER}; border-radius: 15px;
                    padding: 0 12px;
                }}
                QPushButton:hover {{ color: {C.WHITE}; border-color: {C.BORDER_B}; }}
            """)

    def _toggle_mute(self):
        if not self._voice_available:
            self._log.append_log(f"SYS: {self._voice_status_message}")
            if self.on_voice_toggle:
                self.on_voice_toggle(False)
            return
        self._set_microphone_muted(not self._muted, notify=True)

    def _set_microphone_muted(self, muted: bool, *, notify: bool) -> None:
        muted = bool(muted)
        if muted == self._muted:
            return
        self._muted = muted
        self.hud.muted = self._muted
        self._style_mute_btn()
        self._talk_btn.setEnabled(False)
        if self._muted:
            self._talk_btn.setText("Ⅱ  HANDS-FREE LISTENING PAUSED")
            self._apply_state("MUTED")
            self._log.append_log("SYS: Microphone muted.")
        else:
            self._talk_btn.setText("●  HANDS-FREE LISTENING ACTIVE")
            self._apply_state("LISTENING")
            self._log.append_log("SYS: Microphone active.")
        if notify and self.on_voice_toggle:
            self.on_voice_toggle(not self._muted)

    def _style_mute_btn(self):
        if not self._voice_available:
            self._mute_btn.setText("◌  VOICE SETUP REQUIRED")
            self._mute_btn.setStyleSheet(f"""
                QPushButton {{
                    background: #211C12; color: {C.ACC2};
                    border: 1px solid #594728; border-radius: 10px;
                }}
                QPushButton:hover {{ background: #2B2417; }}
            """)
            return
        if self._muted:
            self._mute_btn.setText("🔇  MICROPHONE MUTED")
            self._mute_btn.setStyleSheet(f"""
                QPushButton {{
                    background: #25131B; color: {C.MUTED_C};
                    border: 1px solid #5A2A3A; border-radius: 10px;
                }}
            """)
        else:
            self._mute_btn.setText("🎙  MICROPHONE ACTIVE")
            self._mute_btn.setStyleSheet(f"""
                QPushButton {{
                    background: #10251F; color: {C.GREEN};
                    border: 1px solid #1D4B3B; border-radius: 10px;
                }}
                QPushButton:hover {{ background: #16352B; }}
            """)

    def _cycle_vad_sensitivity(self) -> None:
        order = ("low", "normal", "high")
        current = self._vad_sensitivity if self._vad_sensitivity in order else "normal"
        selected = order[(order.index(current) + 1) % len(order)]
        self._apply_vad_sensitivity(selected)
        if self.on_vad_sensitivity_change:
            self.on_vad_sensitivity_change(selected)

    def _apply_vad_sensitivity(self, sensitivity: str) -> None:
        normalized = str(sensitivity).strip().lower()
        self._vad_sensitivity = normalized if normalized in {"low", "normal", "high"} else "normal"
        self._style_vad_sensitivity_btn()

    def _style_vad_sensitivity_btn(self) -> None:
        if not hasattr(self, "_vad_btn"):
            return
        self._vad_btn.setText(
            f"◫  VOICE SENSITIVITY: {self._vad_sensitivity.upper()}"
        )
        self._vad_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.TEXT_MED};
                border: 1px solid {C.BORDER}; border-radius: 9px;
            }}
            QPushButton:hover {{
                color: {C.PRI}; border: 1px solid {C.BORDER_B};
            }}
        """)

    def _capture_voice_command(self):
        if not self._voice_available or self._muted:
            self._log.append_log(f"SYS: {self._voice_status_message}")
            return
        if not self.on_voice_command:
            self._log.append_log("SYS: Local voice handler is unavailable.")
            return
        self._talk_btn.setEnabled(False)
        self._talk_btn.setText("LISTENING FOR 6 SECONDS…")

        def _run():
            try:
                self.on_voice_command()
            finally:
                self._voice_status_sig.emit(True, "Private local voice command service is ready.")

        threading.Thread(target=_run, daemon=True).start()

    def _apply_voice_status(self, available: bool, message: str):
        self._voice_available = bool(available)
        self._voice_status_message = message.strip() or "Local voice status changed."
        self._style_mute_btn()
        self._talk_btn.setEnabled(False)
        self._talk_btn.setText(
            "●  HANDS-FREE LISTENING ACTIVE"
            if self._voice_available else "VOICE MODEL NOT READY"
        )
        self._talk_btn.setStyleSheet(f"""
            QPushButton {{
                background: {C.PRI_GHO if self._voice_available else C.BG_ALT};
                color: {C.PRI if self._voice_available else C.TEXT_DIM};
                border: 1px solid {C.PRI_DIM if self._voice_available else C.BORDER};
                border-radius: 10px;
            }}
            QPushButton:hover {{ background: {C.PANEL_HI}; }}
        """)
        self._log.append_log(f"SYS: {self._voice_status_message}")

    def _send(self):
        txt = self._input.text().strip()
        if not txt: return
        self._input.clear()
        self._log.append_log(f"You: {txt}")
        if self.on_text_command:
            threading.Thread(target=self.on_text_command, args=(txt,), daemon=True).start()

    def _apply_state(self, state: str):
        self.hud.state    = state
        self.hud.speaking = (state == "SPEAKING")
        state_map = {
            "READY": ("Ready", "Private local intelligence is online", C.GREEN),
            "LISTENING": ("Listening", "I’m ready for your next request", C.GREEN),
            "WAKE_DETECTED": ("I heard you", "Wake word verified — I’m listening", C.ACC2),
            "THINKING": ("Thinking", "Planning the best next step", C.ACC2),
            "PROCESSING": ("Working on it", "Misha is using the right tools for this task", C.ACC),
            "PLANNING": ("Planning", "Building a safe execution plan", C.ACC2),
            "AWAITING_APPROVAL": ("Approval needed", "Waiting for your explicit permission", C.ACC2),
            "EXECUTING": ("Working on it", "Running a validated tool step", C.ACC),
            "VERIFYING": ("Verifying", "Checking the result against real state", C.PRI),
            "RECOVERING": ("Recovering", "Choosing a safe alternative", C.ACC2),
            "SPEAKING": ("Responding", "You can interrupt at any time", C.PRI),
            "RESPONDING": ("Responding", "Preparing the verified result", C.PRI),
            "MUTED": ("Microphone muted", "Type a command or enable the microphone", C.MUTED_C),
            "INITIALISING": ("Starting Misha", "Preparing your private assistant", C.PRI),
        }
        title, subtitle, color = state_map.get(
            state, (state.title(), "Misha is active", C.PRI)
        )
        self._hero_title.setText(title)
        self._hero_subtitle.setText(subtitle)
        self._header_state.setText(f"●  {state}")
        self._header_state.setStyleSheet(
            f"color: {color}; background: {C.PRI_GHO}; border: 1px solid {C.BORDER_A}; "
            "border-radius: 15px; padding: 0 12px;"
        )

    def _show_wake_feedback(self) -> None:
        """Acknowledge a verified wake word with a cue and a dedicated HUD pulse."""
        self._apply_state("WAKE_DETECTED")
        self.hud.trigger_wake_pulse()
        QApplication.beep()

        def _begin_listening() -> None:
            if self.hud.state == "WAKE_DETECTED" and not self._muted:
                self._apply_state("LISTENING")

        QTimer.singleShot(420, _begin_listening)

    def _check_config(self) -> bool:
        from memory.config_manager import get_config
        return bool(get_config("ai_provider")) and bool(get_config("os_system"))

    def _show_setup(self):
        ov = SetupOverlay(self.centralWidget())
        cw = self.centralWidget()
        ow, oh = 520, 430
        ov.setGeometry(
            (cw.width()  - ow) // 2,
            (cw.height() - oh) // 2,
            ow, oh,
        )
        ov.done.connect(self._on_setup_done)
        ov.show()
        self._overlay = ov

    def _schedule_privacy_onboarding(self) -> None:
        from memory.config_manager import get_config

        completed = (get_config("privacy_onboarding_completed") or "0").strip().lower()
        if completed not in {"1", "true", "yes", "on"}:
            QTimer.singleShot(800, self._show_privacy_onboarding)

    def _show_privacy_onboarding(self) -> None:
        from memory.config_manager import set_config

        dialog = PrivacyOnboardingDialog(
            self,
            checks_callback=self.on_setup_diagnostics,
            speaker_callback=self.on_speaker_test,
            devices_callback=self.on_audio_devices,
            select_devices_callback=self.on_audio_device_select,
            microphone_callback=self.on_microphone_test,
            wake_callback=self.on_wake_test,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            screen_enabled, ide_enabled = dialog.opt_in_values()
            set_config("proactive_enabled", "1" if screen_enabled else "0")
            set_config("ide_context_enabled", "1" if ide_enabled else "0")
            set_config("privacy_onboarding_completed", "1")
            if screen_enabled and self.on_proactive_toggle:
                self.on_proactive_toggle(True)
            self._log.append_log(
                "SYS: Privacy choices saved. IDE context changes apply after restart."
            )

    def _on_setup_done(self, model: str, os_name: str):
        from memory.config_manager import save_local_ai_config, set_config
        save_local_ai_config(model=model)
        set_config("os_system", os_name)
        self._ready = True
        if self._overlay:
            self._overlay.hide()
            self._overlay = None
        self._apply_state("READY")
        self._log.append_log(
            f"SYS: Initialised. OS={os_name.upper()}. LOCAL MODEL={model}."
        )
        self._schedule_privacy_onboarding()

class _RootShim:
    def __init__(self, app: QApplication):
        self._app = app
    def mainloop(self):
        self._app.exec()
    def protocol(self, *_):
        pass


class MishaUI:
    def __init__(self, face_path: str, size=None):
        from memory.config_manager import get_config

        self._app = QApplication.instance() or QApplication(sys.argv)
        self._app.setQuitOnLastWindowClosed(False)
        self._app.setStyle("Fusion")
        self._accessibility_filter = _GlobalAccessibilityFilter(self._app)
        self._app.installEventFilter(self._accessibility_filter)
        try:
            font_scale = max(0.85, min(float(get_config("font_scale") or 1.0), 1.5))
        except (TypeError, ValueError):
            font_scale = 1.0
        reduce_motion = str(get_config("reduce_motion") or "0").strip().casefold() in {
            "1", "true", "yes", "on",
        }
        self._app.setProperty("misha_reduce_motion", reduce_motion)
        self._app.setProperty("misha_font_scale", font_scale)
        self._app.setFont(QFont(UI_FONT, round(10 * font_scale)))
        self._app.setStyleSheet(f"""
            QMessageBox {{ background: {C.PANEL}; }}
            QMessageBox QLabel {{ color: {C.TEXT}; min-width: 360px; padding: 10px; }}
            QMessageBox QPushButton {{
                min-width: 92px; min-height: 34px; color: {C.TEXT};
                background: {C.PANEL2}; border: 1px solid {C.BORDER}; border-radius: 9px;
            }}
            QMessageBox QPushButton:hover {{ color: {C.WHITE}; border-color: {C.PRI_DIM}; }}
            QPushButton:focus, QLineEdit:focus, QTextEdit:focus, QListWidget:focus,
            QComboBox:focus, QSpinBox:focus, QTimeEdit:focus {{
                border: 2px solid {C.ACC2};
                outline: none;
            }}
        """)
        self._win = MainWindow(face_path)
        self._tray = None
        self._tray_actions = {}
        self._create_tray_icon()
        self._win.show()
        self.root = _RootShim(self._app)

    def _create_tray_icon(self) -> None:
        icon_path = BASE_DIR / "logo.icns"
        icon = QIcon(str(icon_path)) if icon_path.exists() else self._app.style().standardIcon(
            QStyle.StandardPixmap.SP_ComputerIcon
        )
        tray = QSystemTrayIcon(icon, self._app)
        tray.setToolTip("Misha — private local assistant")
        menu = QMenu()

        show_action = QAction("Show / Hide Misha", menu)
        show_action.triggered.connect(self.toggle_visibility)
        menu.addAction(show_action)

        mute_action = QAction("Mute microphone", menu)
        mute_action.setCheckable(True)
        mute_action.triggered.connect(lambda checked: self._set_muted_from_tray(bool(checked)))
        menu.addAction(mute_action)

        wake_action = QAction('Hands-free “Misha”', menu)
        wake_action.setCheckable(True)
        wake_action.setChecked(True)
        wake_action.triggered.connect(lambda checked: self._set_muted_from_tray(not bool(checked)))
        menu.addAction(wake_action)
        menu.addSeparator()

        top_action = QAction("Always on top", menu)
        top_action.setCheckable(True)
        top_action.setChecked(self._win._always_on_top)
        top_action.triggered.connect(self._win.set_always_on_top)
        menu.addAction(top_action)

        startup_action = QAction("Start at login", menu)
        startup_action.setCheckable(True)
        from core.desktop_lifecycle import launch_at_login_enabled
        startup_action.setChecked(launch_at_login_enabled())
        startup_action.triggered.connect(self._set_launch_at_login)
        menu.addAction(startup_action)
        menu.addSeparator()

        quit_action = QAction("Quit Misha", menu)
        quit_action.triggered.connect(self.quit)
        menu.addAction(quit_action)
        tray.setContextMenu(menu)
        tray.activated.connect(self._tray_activated)
        tray.show()
        self._tray = tray
        self._tray_actions = {
            "show": show_action, "mute": mute_action, "wake": wake_action,
            "always_on_top": top_action, "startup": startup_action,
            "quit": quit_action,
        }

    def _tray_activated(self, reason) -> None:
        if reason in {
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        }:
            self.toggle_visibility()

    def _set_muted_from_tray(self, muted: bool) -> None:
        if muted != self._win._muted:
            self._win._toggle_mute()
        self._sync_tray_voice_state()

    def _sync_tray_voice_state(self) -> None:
        muted = self._win._muted
        for key, checked in (("mute", muted), ("wake", not muted)):
            action = self._tray_actions.get(key)
            if action is not None:
                action.blockSignals(True)
                action.setChecked(checked)
                action.blockSignals(False)

    def _set_launch_at_login(self, enabled: bool) -> None:
        from core.desktop_lifecycle import set_launch_at_login
        from memory.config_manager import set_config

        action = self._tray_actions.get("startup")
        try:
            active = set_launch_at_login(bool(enabled))
            set_config("launch_at_login", "1" if active else "0")
            if action is not None:
                action.setChecked(active)
        except (OSError, ValueError) as exc:
            if action is not None:
                action.setChecked(not bool(enabled))
            self.write_log(f"SYS: Start-at-login update failed safely: {type(exc).__name__}")

    def quit(self) -> None:
        self._win._allow_close = True
        if self._tray is not None:
            self._tray.hide()
        self._win.close()
        self._app.quit()

    def toggle_visibility(self):

        def _do_toggle():
            if self._win.isHidden():
                self._win.show()
                self._win.activateWindow()
                self._win.raise_()
            else:
                self._win.hide()

        QTimer.singleShot(0, _do_toggle)

    def ask_approval(self, message: str) -> bool:
        """
        Synchronously asks for user approval using a QMessageBox.
        Called from a background thread (asyncio executor).
        """
        import concurrent.futures

        result_future = concurrent.futures.Future()
        if QThread.currentThread() == self._app.thread():
            self._win._show_approval_dialog(message, result_future)
        else:
            self._win._approval_sig.emit(str(message), result_future)
        try:
            return bool(result_future.result(timeout=300))
        except (concurrent.futures.TimeoutError, Exception):
            return False

    @property
    def muted(self) -> bool:
        return self._win._muted

    @muted.setter
    def muted(self, v: bool):
        if v != self._win._muted:
            self._win._toggle_mute()

    @property
    def current_file(self) -> str | None:
        return self._win._drop_zone.current_file()

    @property
    def on_text_command(self):
        return self._win.on_text_command

    @on_text_command.setter
    def on_text_command(self, cb):
        self._win.on_text_command = cb

    @property
    def on_voice_toggle(self):
        return self._win.on_voice_toggle

    @on_voice_toggle.setter
    def on_voice_toggle(self, cb):
        self._win.on_voice_toggle = cb

    @property
    def on_vad_sensitivity_change(self):
        return self._win.on_vad_sensitivity_change

    @on_vad_sensitivity_change.setter
    def on_vad_sensitivity_change(self, cb):
        self._win.on_vad_sensitivity_change = cb

    @property
    def on_proactive_toggle(self):
        return self._win.on_proactive_toggle

    @on_proactive_toggle.setter
    def on_proactive_toggle(self, cb):
        self._win.on_proactive_toggle = cb

    @property
    def on_proactive_settings_change(self):
        return self._win.on_proactive_settings_change

    @on_proactive_settings_change.setter
    def on_proactive_settings_change(self, cb):
        self._win.on_proactive_settings_change = cb

    @property
    def on_setup_diagnostics(self):
        return self._win.on_setup_diagnostics

    @on_setup_diagnostics.setter
    def on_setup_diagnostics(self, cb):
        self._win.on_setup_diagnostics = cb

    @property
    def on_speaker_test(self):
        return self._win.on_speaker_test

    @on_speaker_test.setter
    def on_speaker_test(self, cb):
        self._win.on_speaker_test = cb

    @property
    def on_audio_devices(self):
        return self._win.on_audio_devices

    @on_audio_devices.setter
    def on_audio_devices(self, cb):
        self._win.on_audio_devices = cb

    @property
    def on_audio_device_select(self):
        return self._win.on_audio_device_select

    @on_audio_device_select.setter
    def on_audio_device_select(self, cb):
        self._win.on_audio_device_select = cb

    @property
    def on_microphone_test(self):
        return self._win.on_microphone_test

    @on_microphone_test.setter
    def on_microphone_test(self, cb):
        self._win.on_microphone_test = cb

    @property
    def on_wake_test(self):
        return self._win.on_wake_test

    @on_wake_test.setter
    def on_wake_test(self, cb):
        self._win.on_wake_test = cb

    def set_voice_available(self, available: bool, message: str):
        self._win._voice_status_sig.emit(bool(available), message)

    def set_hands_free_enabled(self, enabled: bool) -> None:
        self._win._microphone_muted_sig.emit(not bool(enabled))
        QTimer.singleShot(0, self._sync_tray_voice_state)

    def set_vad_sensitivity(self, sensitivity: str) -> None:
        self._win._vad_sensitivity_sig.emit(str(sensitivity))

    def set_proactive_enabled(self, enabled: bool) -> None:
        self._win._proactive_status_sig.emit(bool(enabled))

    def show_recoverable_tasks(self, records, dismiss_callback=None) -> None:
        self._win._task_recovery_sig.emit(tuple(records or ()), dismiss_callback)

    def add_shutdown_handler(self, callback) -> None:
        self._app.aboutToQuit.connect(callback)

    @property
    def on_voice_command(self):
        return self._win.on_voice_command

    @on_voice_command.setter
    def on_voice_command(self, cb):
        self._win.on_voice_command = cb

    def set_state(self, state: str):
        self._win._state_sig.emit(state)

    def notify_wake_detected(self) -> None:
        self._win._wake_feedback_sig.emit()

    def write_log(self, text: str):
        self._win._log_sig.emit(text)

    def show_plan(self, summary: str) -> None:
        """Surface the validated preflight plan without exposing parameters."""
        self.write_log(str(summary)[:1_200])

    def wait_for_api_key(self):
        self.wait_for_setup()

    def wait_for_setup(self):
        while not self._win._ready:
            time.sleep(0.1)

    def start_speaking(self):
        self.set_state("SPEAKING")

    def stop_speaking(self):
        if not self.muted:
            self.set_state("LISTENING")
