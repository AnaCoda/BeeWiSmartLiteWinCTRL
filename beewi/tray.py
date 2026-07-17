"""System-tray control panel for the BeeWi bulbs.

A frameless, rounded flyout (no OS title bar, no taskbar entry) with per-light
on/off, an inline color picker (hue slider + swatches), brightness and warmth
sliders, a toggle to control both lights together, and presets. All BLE work
goes through the persistent-connection Engine so dragging stays smooth.
"""

from __future__ import annotations

import sys
from typing import Dict, List

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from . import config
from .engine import Engine

LEVEL_MAX = 9

SWATCHES = [
    (244, 67, 54), (255, 152, 0), (255, 214, 90), (76, 175, 80),
    (0, 188, 212), (33, 150, 243), (123, 97, 255), (233, 30, 99),
    (255, 255, 255),
]

STYLE = """
#card { background: #ffffff; border-radius: 16px; }
#panel { background: #f4f5f7; border-radius: 12px; }
QLabel { color: #1c1d21; font-size: 13px; }
#title { font-size: 14px; font-weight: 600; }
#name { font-weight: 600; }
#muted { color: #7a808a; font-size: 12px; }

QPushButton {
    background: #eceef1; color: #1c1d21; border: none;
    border-radius: 9px; padding: 8px 12px; font-size: 13px;
}
QPushButton:hover { background: #e1e4e9; }
#power:checked, #link:checked { background: #3b82f6; color: white; }
#close { background: transparent; color: #7a808a; border-radius: 8px; font-size: 15px; }
#close:hover { background: #e11d48; color: white; }
#pbtn { padding: 6px 10px; }

QComboBox, QLineEdit {
    background: #eceef1; color: #1c1d21; border: none;
    border-radius: 9px; padding: 7px 10px; font-size: 13px;
}
QComboBox QAbstractItemView {
    background: #ffffff; color: #1c1d21; border: 1px solid #e1e4e9;
    selection-background-color: #3b82f6; selection-color: white; outline: none;
}

QSlider::groove:horizontal { height: 6px; background: #dfe2e7; border-radius: 3px; }
QSlider::sub-page:horizontal { background: #3b82f6; border-radius: 3px; }
QSlider::handle:horizontal {
    width: 16px; height: 16px; margin: -6px 0; border-radius: 8px;
    background: white; border: 1px solid #c4c9d0;
}
QSlider#hue::groove:horizontal {
    height: 12px; border-radius: 6px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #ff0000, stop:0.17 #ffff00, stop:0.33 #00ff00,
        stop:0.5 #00ffff, stop:0.67 #0000ff, stop:0.83 #ff00ff, stop:1 #ff0000);
}
QSlider#hue::sub-page:horizontal { background: transparent; }
QSlider#hue::handle:horizontal {
    width: 14px; height: 14px; margin: -3px 0; border-radius: 8px;
    background: white; border: 2px solid #cfd3da;
}

QScrollBar:vertical { background: transparent; width: 8px; margin: 2px; }
QScrollBar::handle:vertical { background: #c4c9d0; border-radius: 4px; min-height: 24px; }
QScrollBar::handle:vertical:hover { background: #adb3bc; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
"""


def _default_state() -> dict:
    return {"on": True, "mode": "color", "r": 255, "g": 255, "b": 255,
            "brightness": LEVEL_MAX, "warmth": 5}


class _Header(QWidget):
    """Draggable title bar with Scan and close (hide) buttons."""

    def __init__(self, title: str, on_scan, on_close):
        super().__init__()
        self._drag = None
        lay = QHBoxLayout(self)
        lay.setContentsMargins(2, 0, 0, 0)
        lay.setSpacing(6)
        label = QLabel(title)
        label.setObjectName("title")
        self.scan_btn = QPushButton("Scan")
        self.scan_btn.setObjectName("pbtn")
        self.scan_btn.clicked.connect(on_scan)
        close = QPushButton("✕")
        close.setObjectName("close")
        close.setFixedSize(30, 28)
        close.clicked.connect(on_close)
        lay.addWidget(label)
        lay.addStretch(1)
        lay.addWidget(self.scan_btn)
        lay.addWidget(close)

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.LeftButton:
            self._drag = e.globalPosition().toPoint() - self.window().frameGeometry().topLeft()

    def mouseMoveEvent(self, e) -> None:
        if self._drag is not None and e.buttons() & Qt.LeftButton:
            self.window().move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, e) -> None:
        self._drag = None


class LightPanel(QFrame):
    """Controls for one bulb. Emits high-level signals; the window routes them."""

    powerChanged = Signal(bool)
    colorChanged = Signal(int, int, int)
    brightnessChanged = Signal(int)
    warmthChanged = Signal(int)

    def __init__(self, title: str):
        super().__init__()
        self.setObjectName("panel")
        self._state = _default_state()

        self._name = QLabel(title)
        self._name.setObjectName("name")
        self._status = QLabel("…")
        self._status.setObjectName("muted")

        self._power = QPushButton("On")
        self._power.setObjectName("power")
        self._power.setCheckable(True)
        self._power.setChecked(True)
        self._power.toggled.connect(self._on_power)

        self._preview = QLabel()
        self._preview.setFixedSize(22, 22)

        self._hue = QSlider(Qt.Horizontal)
        self._hue.setObjectName("hue")
        self._hue.setRange(0, 359)
        self._hue.valueChanged.connect(self._on_hue)

        self._brightness = QSlider(Qt.Horizontal)
        self._brightness.setRange(0, LEVEL_MAX)
        self._brightness.setValue(LEVEL_MAX)
        self._brightness.valueChanged.connect(self.brightnessChanged)

        self._warmth = QSlider(Qt.Horizontal)
        self._warmth.setRange(0, LEVEL_MAX)
        self._warmth.setValue(5)
        self._warmth.valueChanged.connect(self._on_warmth)

        grid = QGridLayout(self)
        grid.setContentsMargins(14, 12, 14, 12)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)

        top = QHBoxLayout()
        top.addWidget(self._name)
        top.addWidget(self._status)
        top.addStretch(1)
        top.addWidget(self._preview)
        grid.addLayout(top, 0, 0, 1, 2)

        grid.addWidget(self._power, 1, 0, 1, 2)
        grid.addLayout(self._build_swatches(), 2, 0, 1, 2)
        grid.addWidget(self._hue, 3, 0, 1, 2)
        grid.addWidget(QLabel("Brightness"), 4, 0)
        grid.addWidget(self._brightness, 4, 1)
        grid.addWidget(QLabel("Warmth"), 5, 0)
        grid.addWidget(self._warmth, 5, 1)

        self._paint_preview()

    def _build_swatches(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(6)
        for r, g, b in SWATCHES:
            btn = QPushButton()
            btn.setFixedSize(24, 24)
            btn.setStyleSheet(
                f"background: rgb({r},{g},{b}); border-radius: 12px;"
                "border: 1px solid rgba(0,0,0,0.15);"
            )
            btn.clicked.connect(lambda _=False, c=(r, g, b): self._on_swatch(*c))
            row.addWidget(btn)
        row.addStretch(1)
        return row

    # Widget events ------------------------------------------------------

    def _on_power(self, on: bool) -> None:
        self._power.setText("On" if on else "Off")
        self._state["on"] = on
        self.powerChanged.emit(on)

    def _on_warmth(self, level: int) -> None:
        self._state.update(mode="white", warmth=level)
        self._paint_preview()
        self.warmthChanged.emit(level)

    def _on_hue(self, hue: int) -> None:
        c = QColor.fromHsv(hue, 255, 255)
        self._set_color(c.red(), c.green(), c.blue(), move_hue=False)
        self.colorChanged.emit(c.red(), c.green(), c.blue())

    def _on_swatch(self, r: int, g: int, b: int) -> None:
        self._set_color(r, g, b, move_hue=True)
        self.colorChanged.emit(r, g, b)

    def _set_color(self, r: int, g: int, b: int, move_hue: bool) -> None:
        self._state.update(mode="color", r=r, g=g, b=b)
        self._paint_preview()
        if move_hue:
            hue = QColor(r, g, b).hue()
            if hue >= 0:
                self._hue.blockSignals(True)
                self._hue.setValue(hue)
                self._hue.blockSignals(False)

    def _warmth_color(self, level: int) -> tuple:
        # Cool white (level 0) to warm amber (level 9), for the preview dot.
        t = level / LEVEL_MAX
        return (int(200 + 55 * t), int(220 - 50 * t), int(255 - 165 * t))

    def _paint_preview(self) -> None:
        s = self._state
        r, g, b = self._warmth_color(s["warmth"]) if s["mode"] == "white" else (s["r"], s["g"], s["b"])
        self._preview.setStyleSheet(
            f"background: rgb({r},{g},{b}); border-radius: 11px;"
            "border: 1px solid rgba(0,0,0,0.18);"
        )

    # Silent setters (link-mirroring and presets; no signals) ------------

    def set_power_silent(self, on: bool) -> None:
        self._power.blockSignals(True)
        self._power.setChecked(on)
        self._power.setText("On" if on else "Off")
        self._power.blockSignals(False)
        self._state["on"] = on

    def set_brightness_silent(self, level: int) -> None:
        self._brightness.blockSignals(True)
        self._brightness.setValue(level)
        self._brightness.blockSignals(False)
        self._state["brightness"] = level

    def set_warmth_silent(self, level: int) -> None:
        self._warmth.blockSignals(True)
        self._warmth.setValue(level)
        self._warmth.blockSignals(False)
        self._state.update(mode="white", warmth=level)
        self._paint_preview()

    def set_color_silent(self, r: int, g: int, b: int) -> None:
        self._set_color(r, g, b, move_hue=True)

    def apply_state_silent(self, state: dict) -> None:
        self.set_power_silent(state.get("on", True))
        self.set_brightness_silent(state.get("brightness", LEVEL_MAX))
        if state.get("mode") == "white":
            self.set_warmth_silent(state.get("warmth", 5))
        else:
            self.set_color_silent(state.get("r", 255), state.get("g", 255), state.get("b", 255))

    def get_state(self) -> dict:
        return dict(self._state)

    def set_connected(self, connected: bool) -> None:
        self._status.setText("connected" if connected else "connecting…")


class _ScanBridge(QObject):
    """Carries scan results from the BLE loop thread back to the GUI thread."""

    scanned = Signal(list)


class ControlWindow(QWidget):
    """The frameless flyout shown when the tray icon is clicked."""

    def __init__(self, engine: Engine, addresses: List[str]):
        super().__init__()
        self._engine = engine
        self._addresses = list(addresses)
        self._panels: Dict[str, LightPanel] = {}
        self._bridge = _ScanBridge()
        self._bridge.scanned.connect(self._on_scanned)

        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet(STYLE)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 18, 18, 18)  # room for the drop shadow
        card = QFrame()
        card.setObjectName("card")
        card.setMinimumWidth(340)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(28)
        shadow.setXOffset(0)
        shadow.setYOffset(8)
        shadow.setColor(QColor(0, 0, 0, 70))
        card.setGraphicsEffect(shadow)
        outer.addWidget(card)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 14)
        layout.setSpacing(10)

        self._header = _Header("BeeWi Lights Controller", self.start_scan, self.hide)
        layout.addWidget(self._header)

        self._link = QPushButton("Control all lights together")
        self._link.setObjectName("link")
        self._link.setCheckable(True)
        layout.addWidget(self._link)

        # Panels live in a scroll area so any number of lights fits on screen.
        self._panels_widget = QWidget()
        self._panels_widget.setStyleSheet("background: transparent;")
        self._panels_layout = QVBoxLayout(self._panels_widget)
        self._panels_layout.setContentsMargins(0, 0, 0, 0)
        self._panels_layout.setSpacing(10)

        self._scroll = QScrollArea()
        self._scroll.setWidget(self._panels_widget)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.viewport().setStyleSheet("background: transparent;")
        layout.addWidget(self._scroll)

        layout.addLayout(self._build_presets_row())

        self._rebuild_panels()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update_status)
        self._timer.start(1000)
        self._update_status()

    # Building / scanning ------------------------------------------------

    def has_bulbs(self) -> bool:
        return bool(self._addresses)

    def _make_panel(self, addr: str, index: int) -> LightPanel:
        panel = LightPanel(f"Light {index + 1}")
        panel.powerChanged.connect(lambda on, a=addr: self._route_power(a, on))
        panel.colorChanged.connect(lambda r, g, b, a=addr: self._route_color(a, r, g, b))
        panel.brightnessChanged.connect(lambda lv, a=addr: self._route_brightness(a, lv))
        panel.warmthChanged.connect(lambda lv, a=addr: self._route_warmth(a, lv))
        return panel

    def _rebuild_panels(self) -> None:
        while self._panels_layout.count():
            item = self._panels_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._panels.clear()

        if not self._addresses:
            empty = QLabel('No bulbs yet.\nClick "Scan" to find your BeeWi bulbs.')
            empty.setObjectName("muted")
            empty.setWordWrap(True)
            empty.setAlignment(Qt.AlignCenter)
            empty.setMinimumHeight(90)
            self._panels_layout.addWidget(empty)
        else:
            for i, addr in enumerate(self._addresses):
                panel = self._make_panel(addr, i)
                self._panels[addr] = panel
                self._panels_layout.addWidget(panel)
        self._panels_layout.addStretch(1)

    def start_scan(self) -> None:
        self._header.scan_btn.setEnabled(False)
        self._header.scan_btn.setText("Scanning…")
        self._engine.scan(lambda results: self._bridge.scanned.emit(results))

    def _on_scanned(self, results: list) -> None:
        self._header.scan_btn.setEnabled(True)
        self._header.scan_btn.setText("Scan")
        if not results:
            QMessageBox.information(
                self,
                "No bulbs found",
                "No BeeWi bulbs found.\n\nMake sure they are powered on and no "
                "phone is connected to them, then scan again.",
            )
            return
        new = [addr for addr, _ in results if addr not in self._addresses]
        if new:
            self._addresses.extend(new)
            config.save_addresses(self._addresses)
            self._engine.add_bulbs(new)
            self._rebuild_panels()
            self._update_status()
        if self.isVisible():
            self.refresh_size()

    # Routing (honors the link toggle) -----------------------------------

    def _targets(self, source: str) -> List[str]:
        return self._addresses if self._link.isChecked() else [source]

    def _mirror(self, source: str, setter: str, *args) -> None:
        if not self._link.isChecked():
            return
        for addr, panel in self._panels.items():
            if addr != source:
                getattr(panel, setter)(*args)

    def _route_power(self, source: str, on: bool) -> None:
        for a in self._targets(source):
            self._engine.power(a, on)
        self._mirror(source, "set_power_silent", on)

    def _route_color(self, source: str, r: int, g: int, b: int) -> None:
        for a in self._targets(source):
            self._engine.color(a, r, g, b)
        self._mirror(source, "set_color_silent", r, g, b)

    def _route_brightness(self, source: str, level: int) -> None:
        for a in self._targets(source):
            self._engine.brightness(a, level)
        self._mirror(source, "set_brightness_silent", level)

    def _route_warmth(self, source: str, level: int) -> None:
        for a in self._targets(source):
            self._engine.temperature(a, level)
        self._mirror(source, "set_warmth_silent", level)

    # Presets ------------------------------------------------------------

    def _build_presets_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(6)
        self._preset_box = QComboBox()
        self._preset_name = QLineEdit()
        self._preset_name.setPlaceholderText("name")
        self._preset_name.setFixedWidth(72)
        self._reload_presets()

        apply_btn = QPushButton("Apply")
        save_btn = QPushButton("Save")
        del_btn = QPushButton("✕")
        for b in (apply_btn, save_btn, del_btn):
            b.setObjectName("pbtn")
        apply_btn.clicked.connect(self._apply_preset)
        save_btn.clicked.connect(self._save_preset)
        del_btn.clicked.connect(self._delete_preset)

        row.addWidget(self._preset_box, 1)
        row.addWidget(apply_btn)
        row.addWidget(self._preset_name)
        row.addWidget(save_btn)
        row.addWidget(del_btn)
        return row

    def _reload_presets(self) -> None:
        self._preset_box.clear()
        self._preset_box.addItems(sorted(config.load_presets().keys()))

    def _save_preset(self) -> None:
        name = self._preset_name.text().strip()
        if not name:
            return
        presets = config.load_presets()
        presets[name] = {a: p.get_state() for a, p in self._panels.items()}
        config.save_presets(presets)
        self._preset_name.clear()
        self._reload_presets()
        self._preset_box.setCurrentText(name)

    def _apply_preset(self) -> None:
        name = self._preset_box.currentText()
        preset = config.load_presets().get(name)
        if not preset:
            return
        for addr, state in preset.items():
            if addr not in self._panels:
                continue
            self._engine.power(addr, state.get("on", True))
            if state.get("mode") == "white":
                self._engine.temperature(addr, state.get("warmth", 5))
            else:
                self._engine.color(addr, state.get("r", 255), state.get("g", 255), state.get("b", 255))
            self._engine.brightness(addr, state.get("brightness", LEVEL_MAX))
            self._panels[addr].apply_state_silent(state)

    def _delete_preset(self) -> None:
        name = self._preset_box.currentText()
        presets = config.load_presets()
        if name in presets:
            del presets[name]
            config.save_presets(presets)
            self._reload_presets()

    # Status -------------------------------------------------------------

    def _update_status(self) -> None:
        for addr, panel in self._panels.items():
            panel.set_connected(self._engine.is_connected(addr))

    def fit_to(self, max_scroll_height: int) -> None:
        """Size the scroll area to the lights, capped so it never exceeds screen."""
        self._panels_widget.ensurePolished()
        needed = self._panels_widget.sizeHint().height()
        self._scroll.setFixedHeight(min(needed, max_scroll_height) + 2)

    def refresh_size(self) -> None:
        """Fit to contents and reposition at the bottom-right, near the tray."""
        screen = QApplication.primaryScreen().availableGeometry()
        self.fit_to(int(screen.height() * 0.72))
        self.adjustSize()
        size = self.frameGeometry()
        self.move(
            screen.right() - size.width() - 12,
            screen.bottom() - size.height() - 12,
        )

    def closeEvent(self, event) -> None:  # hide to tray instead of quitting
        event.ignore()
        self.hide()


def _make_icon() -> QIcon:
    pix = QPixmap(64, 64)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(255, 210, 60))
    p.setPen(Qt.NoPen)
    p.drawEllipse(12, 8, 40, 40)
    p.setBrush(QColor(120, 120, 120))
    p.drawRect(24, 46, 16, 12)
    p.end()
    return QIcon(pix)


class TrayApp:
    def __init__(self, engine: Engine, addresses: List[str]):
        self._window = ControlWindow(engine, addresses)
        self._tray = QSystemTrayIcon(_make_icon())
        self._tray.setToolTip("BeeWi Lights Controller")

        menu = QMenu()
        show = QAction("Show controls", menu)
        scan = QAction("Scan for bulbs", menu)
        quit_act = QAction("Quit", menu)
        show.triggered.connect(self.show_window)
        scan.triggered.connect(self._window.start_scan)
        quit_act.triggered.connect(QApplication.quit)
        menu.addAction(show)
        menu.addAction(scan)
        menu.addSeparator()
        menu.addAction(quit_act)
        self._tray.setContextMenu(menu)
        self._tray.activated.connect(self._on_activated)
        self._tray.show()
        self._tray.showMessage(
            "BeeWi Lights Controller",
            "Running in the tray. Click the icon to open controls.",
            QSystemTrayIcon.MessageIcon.Information,
            4000,
        )

    def _on_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.Trigger:  # left click
            self._toggle()

    def _toggle(self) -> None:
        if self._window.isVisible():
            self._window.hide()
        else:
            self.show_window()

    def show_window(self) -> None:
        self._window.refresh_size()
        self._window.show()
        self._window.raise_()
        self._window.activateWindow()

    def scan_if_empty(self) -> None:
        if not self._window.has_bulbs():
            self._window.start_scan()


def main() -> int:
    addresses = config.load_addresses()
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    engine = Engine()
    engine.start(addresses)  # empty is fine; bulbs can be added via in-app scan
    app.aboutToQuit.connect(engine.stop)

    tray = TrayApp(engine, addresses)
    tray.show_window()  # show the panel on first launch so it isn't hidden
    tray.scan_if_empty()  # first-run (e.g. exe download): auto-scan for bulbs
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
