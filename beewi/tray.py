"""System-tray control panel for the BeeWi bulbs.

Click the tray icon to expand a panel with per-light on/off, brightness, warmth,
and a live color picker, a toggle to control both lights together, and presets.
All BLE work goes through the persistent-connection Engine so dragging is smooth.
"""

from __future__ import annotations

import sys
from typing import Dict, List

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QColorDialog,
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QSlider,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from . import config
from .engine import Engine

LEVEL_MAX = 9


def _default_state() -> dict:
    return {"on": True, "mode": "color", "r": 255, "g": 255, "b": 255,
            "brightness": LEVEL_MAX, "warmth": 5}


class LightPanel(QGroupBox):
    """Controls for one bulb. Emits high-level signals; the window routes them."""

    powerChanged = Signal(bool)
    colorChanged = Signal(int, int, int)
    brightnessChanged = Signal(int)
    warmthChanged = Signal(int)

    def __init__(self, title: str):
        super().__init__(title)
        self._base_title = title
        self._state = _default_state()

        self._power = QPushButton("On")
        self._power.setCheckable(True)
        self._power.setChecked(True)
        self._power.toggled.connect(self._on_power)

        self._color_btn = QPushButton("Color")
        self._color_btn.clicked.connect(self._pick_color)

        self._brightness = QSlider(Qt.Horizontal)
        self._brightness.setRange(0, LEVEL_MAX)
        self._brightness.setValue(LEVEL_MAX)
        self._brightness.valueChanged.connect(self.brightnessChanged)

        self._warmth = QSlider(Qt.Horizontal)
        self._warmth.setRange(0, LEVEL_MAX)
        self._warmth.setValue(5)
        self._warmth.valueChanged.connect(self._on_warmth)

        grid = QGridLayout(self)
        grid.addWidget(self._power, 0, 0)
        grid.addWidget(self._color_btn, 0, 1)
        grid.addWidget(QLabel("Brightness"), 1, 0)
        grid.addWidget(self._brightness, 1, 1)
        grid.addWidget(QLabel("Warmth"), 2, 0)
        grid.addWidget(self._warmth, 2, 1)
        self._refresh_color_btn()

    # Widget events ------------------------------------------------------

    def _on_power(self, on: bool) -> None:
        self._power.setText("On" if on else "Off")
        self._state["on"] = on
        self.powerChanged.emit(on)

    def _on_warmth(self, level: int) -> None:
        self._state["mode"] = "white"
        self._state["warmth"] = level
        self.warmthChanged.emit(level)

    def _pick_color(self) -> None:
        dlg = QColorDialog(QColor(self._state["r"], self._state["g"], self._state["b"]), self)
        # Qt's own dialog emits currentColorChanged live while dragging; the
        # native Windows one does not, so force the Qt dialog.
        dlg.setOption(QColorDialog.DontUseNativeDialog, True)
        dlg.currentColorChanged.connect(self._on_color_live)
        dlg.exec()

    def _on_color_live(self, color: QColor) -> None:
        if not color.isValid():
            return
        self._state.update(mode="color", r=color.red(), g=color.green(), b=color.blue())
        self._refresh_color_btn()
        self.colorChanged.emit(color.red(), color.green(), color.blue())

    def _refresh_color_btn(self) -> None:
        s = self._state
        self._color_btn.setStyleSheet(
            f"background-color: rgb({s['r']},{s['g']},{s['b']}); color: "
            f"{'black' if (s['r']+s['g']+s['b']) > 384 else 'white'};"
        )

    # Silent setters (used for link-mirroring and presets; no signals) ----

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

    def set_color_silent(self, r: int, g: int, b: int) -> None:
        self._state.update(mode="color", r=r, g=g, b=b)
        self._refresh_color_btn()

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
        self.setTitle(f"{self._base_title}   {'●' if connected else '…'}")


class ControlWindow(QWidget):
    """The expandable panel shown when the tray icon is clicked."""

    def __init__(self, engine: Engine, addresses: List[str]):
        super().__init__()
        self._engine = engine
        self._addresses = addresses
        self._panels: Dict[str, LightPanel] = {}

        self.setWindowTitle("BeeWi Lights")
        self.setWindowFlags(Qt.Tool)

        layout = QVBoxLayout(self)

        self._link = QPushButton("Control both lights together")
        self._link.setCheckable(True)
        layout.addWidget(self._link)

        for i, addr in enumerate(addresses):
            panel = LightPanel(f"Light {i + 1}")
            panel.powerChanged.connect(lambda on, a=addr: self._route_power(a, on))
            panel.colorChanged.connect(lambda r, g, b, a=addr: self._route_color(a, r, g, b))
            panel.brightnessChanged.connect(lambda lv, a=addr: self._route_brightness(a, lv))
            panel.warmthChanged.connect(lambda lv, a=addr: self._route_warmth(a, lv))
            self._panels[addr] = panel
            layout.addWidget(panel)

        layout.addLayout(self._build_presets_row())

        # Keep the connection dots fresh.
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update_status)
        self._timer.start(1000)
        self._update_status()

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
        self._preset_box = QComboBox()
        self._reload_presets()
        apply_btn = QPushButton("Apply")
        save_btn = QPushButton("Save")
        del_btn = QPushButton("Delete")
        apply_btn.clicked.connect(self._apply_preset)
        save_btn.clicked.connect(self._save_preset)
        del_btn.clicked.connect(self._delete_preset)
        row.addWidget(QLabel("Preset"))
        row.addWidget(self._preset_box, 1)
        row.addWidget(apply_btn)
        row.addWidget(save_btn)
        row.addWidget(del_btn)
        return row

    def _reload_presets(self) -> None:
        self._preset_box.clear()
        self._preset_box.addItems(sorted(config.load_presets().keys()))

    def _save_preset(self) -> None:
        name, ok = QInputDialog.getText(self, "Save preset", "Preset name:")
        if not ok or not name.strip():
            return
        presets = config.load_presets()
        presets[name.strip()] = {a: p.get_state() for a, p in self._panels.items()}
        config.save_presets(presets)
        self._reload_presets()
        self._preset_box.setCurrentText(name.strip())

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
        self._tray.setToolTip("BeeWi Lights")

        menu = QMenu()
        show = QAction("Show controls", menu)
        quit_act = QAction("Quit", menu)
        show.triggered.connect(self._toggle)
        quit_act.triggered.connect(QApplication.quit)
        menu.addAction(show)
        menu.addSeparator()
        menu.addAction(quit_act)
        self._tray.setContextMenu(menu)
        self._tray.activated.connect(self._on_activated)
        self._tray.show()
        self._tray.showMessage(
            "BeeWi Lights",
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
        self._window.adjustSize()
        screen = QApplication.primaryScreen().availableGeometry()
        size = self._window.frameGeometry()
        self._window.move(
            screen.right() - size.width() - 12,
            screen.bottom() - size.height() - 12,
        )
        self._window.show()
        self._window.raise_()
        self._window.activateWindow()


def main() -> int:
    addresses = config.load_addresses()
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    if not addresses:
        QMessageBox.information(
            None,
            "No bulbs saved",
            "No bulbs saved yet.\n\nRun 'uv run beewi scan' first to find and "
            "save your bulbs, then start the tray again.",
        )
        return 1

    engine = Engine()
    engine.start(addresses)
    app.aboutToQuit.connect(engine.stop)

    tray = TrayApp(engine, addresses)
    tray.show_window()  # show the panel on first launch so it isn't hidden
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
