# -*- coding: utf-8 -*-
# =========================================================================
# Copyright (C) 2026 Ezequiel M. Rezende
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
# =========================================================================
# =========================================================================
# Extension: igz_calculator — Calculator (Standard / Scientific)
# Author: Ezequiel M. Rezende
# Version: 1.1.0
# Date: 2026-11-07
# License: GPL-3.0-or-later (same as IngeTrazo)
# Repository: https://github.com/em-rezende/Ingetrazo-igz-calculator
#
# IngeTrazo — "Calculator" toolbar + side panel. A native calculator
# (Standard and Scientific) that:
#
#   • opens as a floating dialog **or** as a side panel/dock;
#   • shows the current value in a large display, the last 4 results
#     in a fixed block (oldest on top, newest at the bottom) and an
#     extended, scrollable history (4–50 entries, user-configurable);
#   • supports the physical keyboard: digits, operators, parentheses,
#     Enter, Backspace, Esc, Del and single-letter shortcuts for
#     functions (r, p, e, s, q, c, ^, %, !, n, l, i, m);
#   • injects the current value into the VCB (Value Control Box) of
#     IngeTrazo in one click, with a clipboard fallback when no VCB
#     is available;
#   • keeps dialog and panel synchronized in real time (state_changed
#     signal on a module-level _SyncBus);
#   • persists history, mode (Standard/Scientific), angle (DEG/RAD)
#     and history_limit in state.json (application data folder);
#   • is fully internationalized (pt-BR / en / es) via core.i18n
#     when available, and via local i18n/<lang>.json files otherwise.
#
# The extension is written as a standalone single-file plugin: it
# exposes `setup(app)` (plus `register`, `init`, `load`, `on_load` as
# aliases) and creates the toolbar with `QMainWindow.addToolBar`. It has
# no runtime dependency beyond PySide6 — in particular, it does NOT use
# QtWebEngine or QtWebChannel, so it works in a PySide6-Essentials host
# such as the packaged IngeTrazo.
#
# Integration points with the host (all small helpers at the bottom of
# this module — `_find_main_window`, `_add_toolbar`,
# `_attach_calculator_panel`, `_try_setup`, `_ensure_toolbar`): find
# the main window, add the toolbar, attach the panel as a tab/dock,
# retry the setup for a few seconds and re-create the toolbar if the
# host calls restoreState() after the plugin runs. Everything else
# (parser, calculator UI, history, injection, sync, i18n) is fully
# self-contained.
# =========================================================================

from __future__ import annotations

import json
import math
import os
import re
import sys
import traceback
from typing import Optional

from PySide6.QtCore import QEvent, QObject, QTimer, Qt, Signal
from PySide6.QtGui import QAction, QIcon, QKeyEvent, QPalette
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QDialog,
    QDockWidget,
    QDoubleSpinBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QStyle,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

# Diagnóstico: desligado por padrão para não poluir o stderr do IngeTrazo a
# cada carga. Defina IGZ_CALCULATOR_DEBUG=1 no ambiente para reativar os logs
# (útil apenas durante o desenvolvimento).
DEBUG = bool(os.environ.get("IGZ_CALCULATOR_DEBUG"))


def _log(s: str) -> None:
    if DEBUG:
        try:
            print(f"[igz_calculator] {s}", file=sys.stderr, flush=True)
        except Exception:
            pass


# =========================================================================
# INTERNACIONALIZAÇÃO
# =========================================================================
# Ordem de resolução de uma string `text` (chave = string-fonte em pt-BR):
#   1. core.i18n do IngeTrazo (tr()) — se disponível e traduzido.
#   2. i18n/<lang>.json do plugin — se existir.
#   3. _TEXTS local (fallback mínimo, cobre en/es/pt-BR).
#   4. O próprio `text` (identidade).

try:
    from core.i18n import tr as _tr_i18n
    from core.i18n import current_language as _current_language
except Exception:
    def _tr_i18n(s, **kw):
        return s.format(**kw) if kw else s

    def _current_language():
        return "pt-BR"


_HERE = os.path.dirname(os.path.abspath(__file__))
_I18N_DIR = os.path.join(_HERE, "i18n")


# Cache: {lang: {chave: tradução}}
_I18N_CACHE: dict[str, dict] = {}


def _load_i18n_json(lang_key: str) -> dict:
    """Carrega i18n/<lang>.json do plugin (cacheado)."""
    if lang_key in _I18N_CACHE:
        return _I18N_CACHE[lang_key]

    data: dict = {}
    try:
        path = os.path.join(_I18N_DIR, f"{lang_key}.json")
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                data = {str(k): str(v) for k, v in raw.items()}
    except Exception:
        _log(f"_load_i18n_json({lang_key!r}) falhou:\n"
             + traceback.format_exc())

    _I18N_CACHE[lang_key] = data
    return data


_TEXTS = {
    "pt-BR": {},  # já é o padrão
    "en": {
        "Calculadora": "Calculator",
        "Padrão ☰": "Standard ☰",
        "Científica ☰": "Scientific ☰",
        "Histórico 📋": "History 📋",
        "Histórico extenso": "Extended history",
        "Injetar ↑": "Inject ↑",
        "Copiado! ✔": "Copied! ✔",
        "Injetado! ✔": "Injected! ✔",
        "Erro": "Error",
        "Calculadora": "Calculator",
        "Painel Calculadora": "Calculator Panel",
        "Abre a calculadora em uma janela flutuante.":
            "Open the calculator in a floating window.",
        "Ir para a aba Calculadora no painel lateral.":
            "Go to the Calculator tab in the side panel.",
        "Mostrar/ocultar a calculadora no painel lateral.":
            "Show/hide the calculator in the side panel.",
        "Dock Calculadora": "Calculator Dock",
    },
    "es": {
        "Calculadora": "Calculadora",
        "Padrão ☰": "Estándar ☰",
        "Científica ☰": "Científica ☰",
        "Histórico 📋": "Historial 📋",
        "Histórico extenso": "Historial extendido",
        "Injetar ↑": "Inyectar ↑",
        "Copiado! ✔": "¡Copiado! ✔",
        "Injetado! ✔": "¡Inyectado! ✔",
        "Erro": "Error",
        "Calculadora": "Calculadora",
        "Painel Calculadora": "Panel Calculadora",
        "Abre a calculadora em uma janela flutuante.":
            "Abre la calculadora en una ventana flotante.",
        "Ir para a aba Calculadora no painel lateral.":
            "Ir a la pestaña Calculadora en el panel lateral.",
        "Mostrar/ocultar a calculadora no painel lateral.":
            "Mostrar/ocultar la calculadora en el panel lateral.",
        "Dock Calculadora": "Dock Calculadora",
    },
}


def _lang_key() -> str:
    """Normaliza o idioma atual ('pt_BR' → 'pt-BR')."""
    try:
        lang = str(_current_language() or "pt-BR").strip().replace("_", "-")
    except Exception:
        return "pt-BR"
    if lang in _TEXTS:
        return lang
    base = lang.split("-")[0].lower()
    for key in _TEXTS:
        if key.lower().split("-")[0] == base:
            return key
    return "pt-BR"


def _t(text: str, **kw) -> str:
    """Traduz `text` (chave = string-fonte em pt-BR)."""
    # 1) core.i18n do host
    try:
        x = _tr_i18n(text)
        if isinstance(x, str) and x != text:
            return x.format(**kw) if kw else x
    except Exception:
        pass

    lang = _lang_key()

    # 2) i18n/<lang>.json do plugin
    try:
        data = _load_i18n_json(lang)
        if text in data:
            out = data[text]
            return out.format(**kw) if kw else out
    except Exception:
        pass

    # 3) _TEXTS local
    try:
        out = _TEXTS.get(lang, {}).get(text)
        if out is not None:
            return out.format(**kw) if kw else out
    except Exception:
        pass

    # 4) Identidade
    return text.format(**kw) if kw else text


# =========================================================================
# PERSISTÊNCIA
# =========================================================================

def _config_file() -> str:
    try:
        from PySide6.QtCore import QStandardPaths
        base = QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)
    except Exception:
        base = ""
    if not base:
        base = os.path.join(os.path.expanduser("~"), ".ingetrazo")
    d = os.path.join(base, "igz_calculator")
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        pass
    return os.path.join(d, "state.json")


def _load_state() -> dict:
    try:
        with open(_config_file(), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_state(data: dict) -> None:
    try:
        path = _config_file()
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception:
        traceback.print_exc()


# =========================================================================
# PARSER MATEMÁTICO
# =========================================================================

_ATOM = r"(?:\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|[A-Za-z_][A-Za-z0-9_.]*)"


def _replace_func1(expr: str, name: str, py_name: str,
                   inner_suffix: str = "") -> str:
    out = []
    i = 0
    n = len(expr)
    while i < n:
        idx = expr.find(name, i)
        if idx < 0:
            out.append(expr[i:])
            break
        out.append(expr[i:idx])
        j = idx + len(name)
        while j < n and expr[j].isspace():
            j += 1
        if j >= n or expr[j] != "(":
            out.append(name)
            i = j
            continue
        depth = 0
        k = j
        while k < n:
            if expr[k] == "(":
                depth += 1
            elif expr[k] == ")":
                depth -= 1
                if depth == 0:
                    break
            k += 1
        if depth != 0:
            out.append(expr[idx:])
            i = n
            break
        inner = expr[j + 1:k]
        out.append(f"{py_name}(({inner}){inner_suffix})")
        i = k + 1
    return "".join(out)


def _replace_pow(expr: str) -> str:
    pat = re.compile(
        r"(?<![A-Za-z0-9_.])(" + _ATOM + r")\s*pow\s*(" + _ATOM
        + r")(?![A-Za-z0-9_])"
    )
    guard = 0
    while "pow" in expr and guard < 100:
        guard += 1
        m = pat.search(expr)
        if not m:
            break
        expr = expr[:m.start()] + f"({m.group(1)}**{m.group(2)})" + expr[m.end():]
    return expr


def _replace_postfix(expr: str, suffix: str, repl: str) -> str:
    pat = re.compile(
        r"(?<![A-Za-z0-9_.])(" + _ATOM + r")\s*"
        + re.escape(suffix) + r"\b"
    )
    if suffix == "fact":
        return pat.sub(lambda m: f"__fact({m.group(1)})", expr)
    return pat.sub(lambda m: f"({m.group(1)}{repl})", expr)


def _replace_factorial(expr: str) -> str:
    pat = re.compile(r"__fact\(([^()]*)\)")
    return pat.sub(lambda m: f"math.factorial(int({m.group(1)}))", expr)


def _add_implicit_mul(expr: str) -> str:
    expr = re.sub(
        r"(?<![A-Za-z0-9_.])(\d+(?:\.\d+)?)\s*([A-Za-z_])",
        r"\1*\2", expr,
    )
    expr = re.sub(
        r"(?<![A-Za-z0-9_.])(\d+(?:\.\d+)?)\s*\(",
        r"\1*(", expr,
    )
    expr = re.sub(r"\)(\d)", r")*\1", expr)
    expr = re.sub(r"\)([A-Za-z_])", r")*\1", expr)
    return expr


def _auto_close_parens(expr: str) -> str:
    opens = expr.count("(")
    closes = expr.count(")")
    return expr + (")" * max(0, opens - closes))


def _safe_eval(expr: str):
    env = {
        "math": math,
        "pow10": lambda x: 10 ** x,
        "random": __import__("random"),
        "int": int, "float": float, "abs": abs, "round": round,
    }
    return eval(expr, {"__builtins__": {}}, env)


# =========================================================================
# SINCRONIZAÇÃO
# =========================================================================

class _SyncBus(QObject):
    """Bus global. Emite estado sem depender de instância viva.
    Slots devem verificar se o C++ do receptor existe antes de acessar."""
    state_changed = Signal(str, str, bool, bool, list)


_sync_bus = _SyncBus()


# =========================================================================
# INSTÂNCIA ÚNICA + TRACKER DE VCB
# =========================================================================

_dialog_instance: Optional["CalculatorDialog"] = None

_EDITABLE_TYPES = (
    QLineEdit, QSpinBox, QDoubleSpinBox, QAbstractSpinBox,
)

_last_vcb_ref = {"widget": None}
_tracker_installed = False


class _VcbTracker(QObject):
    def eventFilter(self, obj, event):
        try:
            if event.type() == QEvent.FocusIn:
                if isinstance(obj, _EDITABLE_TYPES) and obj.isVisible():
                    if _dialog_instance is None or not _dialog_instance.isVisible():
                        _last_vcb_ref["widget"] = obj
        except Exception:
            pass
        return False


def _install_vcb_tracker() -> None:
    global _tracker_installed
    if _tracker_installed:
        return
    try:
        qapp = QApplication.instance()
        if qapp is not None:
            tracker = _VcbTracker(qapp)
            qapp.installEventFilter(tracker)
            qapp._igz_vcb_tracker = tracker  # noqa: SLF001
            _tracker_installed = True
    except Exception:
        _log("_install_vcb_tracker falhou:\n" + traceback.format_exc())


def _is_editable(w) -> bool:
    try:
        return isinstance(w, _EDITABLE_TYPES) and w.isVisible()
    except Exception:
        return False


def _find_active_vcb():
    try:
        fw = QApplication.focusWidget()
        if _is_editable(fw):
            return fw
    except Exception:
        pass
    try:
        w = _last_vcb_ref["widget"]
        if w is not None:
            try:
                _ = w.isVisible()
            except RuntimeError:
                _last_vcb_ref["widget"] = None
                w = None
            if w is not None and _is_editable(w):
                return w
    except Exception:
        pass
    return None


def _inject_into_widget(widget, text: str) -> bool:
    try:
        if isinstance(widget, QLineEdit):
            widget.selectAll()
            widget.insert(text)
            QTimer.singleShot(0, widget.editingFinished.emit)
            return True
        if isinstance(widget, QSpinBox):
            widget.setValue(int(round(float(text.replace(",", ".")))))
            QTimer.singleShot(0, widget.editingFinished.emit)
            return True
        if isinstance(widget, QDoubleSpinBox):
            widget.setValue(float(text.replace(",", ".")))
            QTimer.singleShot(0, widget.editingFinished.emit)
            return True
    except Exception:
        _log(f"_inject_into_widget falhou:\n{traceback.format_exc()}")
    return False


def _inject_via_keyevents(widget, text: str) -> bool:
    try:
        widget.clear()
        for ch in text:
            QApplication.postEvent(
                widget,
                QKeyEvent(QEvent.KeyPress, 0, Qt.NoModifier, ch),
            )
        QApplication.postEvent(
            widget,
            QKeyEvent(QEvent.KeyPress, Qt.Key_Return, Qt.NoModifier),
        )
        return True
    except Exception:
        _log(f"_inject_via_keyevents falhou:\n{traceback.format_exc()}")
    return False


# =========================================================================
# BASE COMPARTILHADA
# =========================================================================

class _CalculatorBase:
    """Mixin com lógica, sincronização, teclado e HISTÓRICO EXTENSO."""

    #: Opções de limite de histórico (o "4" é o comportamento antigo).
    _HIST_OPTIONS = (4, 10, 25, 50)
    _HIST_DEFAULT = 25

    def _init_state(self) -> None:
        self.current_input = "0"
        self.internal_expr = "0"
        self.should_reset = False
        self.is_rad = False
        self.history: list[str] = []
        self.history_limit: int = self._HIST_DEFAULT
        self.mode = "standard"

        self._suppress_broadcast = False
        self._sync_slot_bound = False
        self._kbd_shortcuts: list = []
        self._kbd_installed = False
        self._alive = True

        try:
            st = _load_state()
            self.history = list(st.get("history") or [])
            self.is_rad = bool(st.get("is_rad", False))
            self.mode = str(st.get("mode", "standard"))
            lim = int(st.get("history_limit", self._HIST_DEFAULT))
            if lim not in self._HIST_OPTIONS:
                lim = self._HIST_DEFAULT
            self.history_limit = lim
            # Garante que o histórico carregado não exceda o limite.
            self.history = self.history[-self.history_limit:]
        except Exception:
            pass

    # -----------------------------------------------------------------
    # Broadcast
    # -----------------------------------------------------------------
    def _broadcast_state(self) -> None:
        if getattr(self, "_suppress_broadcast", False):
            return
        try:
            _sync_bus.state_changed.emit(
                self.current_input,
                self.internal_expr,
                self.should_reset,
                self.is_rad,
                list(self.history),
            )
        except Exception:
            _log("_broadcast_state falhou (ignorado):\n"
                 + traceback.format_exc())

    def _connect_sync(self) -> None:
        if self._sync_slot_bound:
            return
        try:
            _sync_bus.state_changed.connect(self._on_remote_state)
            self._sync_slot_bound = True
        except Exception:
            _log("_connect_sync falhou:\n" + traceback.format_exc())

    def _on_remote_state(self, current: str, internal: str,
                         reset: bool, rad: bool, hist: list) -> None:
        try:
            if not getattr(self, "_alive", False):
                return
        except RuntimeError:
            return
        try:
            self._suppress_broadcast = True

            self.current_input = current
            self.internal_expr = internal
            self.should_reset = reset
            self.is_rad = rad
            self.history = list(hist)[-self.history_limit:]

            try:
                self.btn_angle.blockSignals(True)
                self._update_angle_button()
            finally:
                try:
                    self.btn_angle.blockSignals(False)
                except Exception:
                    pass

            try:
                self._refresh_display()
            except Exception:
                traceback.print_exc()
        finally:
            self._suppress_broadcast = False

    # -----------------------------------------------------------------
    # TECLADO FÍSICO
    # -----------------------------------------------------------------
    def _install_keyboard(self) -> None:
        if self._kbd_installed:
            return
        try:
            QShortcut = None
            QKeySequence = None
            try:
                from PySide6.QtGui import QShortcut as _QS
                from PySide6.QtGui import QKeySequence as _QKS
                QShortcut, QKeySequence = _QS, _QKS
            except Exception:
                try:
                    from PySide6.QtWidgets import QShortcut as _QS2
                    from PySide6.QtWidgets import QKeySequence as _QKS2
                    QShortcut, QKeySequence = _QS2, _QKS2
                except Exception:
                    QShortcut = None

            if QShortcut is None:
                _log("_install_keyboard: QShortcut indisponível.")
                self._kbd_installed = True
                return

            def add(seq_str, callback):
                try:
                    sc = QShortcut(QKeySequence(seq_str), self)
                    sc.setContext(Qt.WidgetWithChildrenShortcut)
                    sc.activated.connect(callback)
                    self._kbd_shortcuts.append(sc)
                except Exception:
                    _log(f"atalho {seq_str!r} falhou:\n"
                         + traceback.format_exc())

            for d in "0123456789":
                add(d, lambda d=d: self._input_direct(d))
            add("+",  lambda: self._input_direct("+"))
            add("-",  lambda: self._input_direct("-"))
            add("*",  lambda: self._input_direct("*"))
            add("/",  lambda: self._input_direct("/"))
            add("(",  lambda: self._input_direct("("))
            add(")",  lambda: self._input_direct(")"))
            add(",",  lambda: self._input_dot())
            add(".",  lambda: self._input_dot())
            add("=",  lambda: self._calculate())
            add("Return",    lambda: self._calculate())
            add("Enter",     lambda: self._calculate())
            add("Backspace", lambda: self._backspace())
            add("Escape",    lambda: self._clear_all())
            add("Delete",    lambda: self._clear_current())
            add("r", lambda: self._toggle_angle())
            add("p", lambda: self._input_sci("Math.PI", "π"))
            add("e", lambda: self._input_sci("Math.E", "e"))
            add("s", lambda: self._input_sci("Math.sqrt", "√"))
            add("q", lambda: self._input_direct("sqr"))
            add("c", lambda: self._input_direct("cube"))
            add("^", lambda: self._input_direct("pow"))
            add("%", lambda: self._input_direct("pct"))
            add("!", lambda: self._input_direct("fact"))
            add("n", lambda: self._input_sci("Math.log", "ln"))
            add("l", lambda: self._input_sci("Math.log10", "log"))
            add("i", lambda: self._input_direct("inv"))
            add("m", lambda: self._input_direct("mod"))

            self._kbd_installed = True
            _log(f"_install_keyboard: {len(self._kbd_shortcuts)} atalhos")
        except Exception:
            _log("_install_keyboard falhou (UI continua):\n"
                 + traceback.format_exc())

    def keyPressEvent(self, event) -> None:
        try:
            if not getattr(self, "_alive", False):
                return
            key = event.key()
            txt = event.text()

            if key in (Qt.Key_Return, Qt.Key_Enter):
                self._calculate()
                event.accept()
                return
            if key == Qt.Key_Backspace:
                self._backspace()
                event.accept()
                return
            if key == Qt.Key_Escape:
                self._clear_all()
                event.accept()
                return
            if key == Qt.Key_Delete:
                self._clear_current()
                event.accept()
                return
            if txt and len(txt) == 1:
                if txt.isdigit():
                    self._input_direct(txt)
                    event.accept()
                    return
                if txt in "+-*/()":
                    self._input_direct(txt)
                    event.accept()
                    return
                if txt in ",.":
                    self._input_dot()
                    event.accept()
                    return
                if txt == "=":
                    self._calculate()
                    event.accept()
                    return
        except Exception:
            traceback.print_exc()
        try:
            QWidget.keyPressEvent(self, event)
        except Exception:
            try:
                event.ignore()
            except Exception:
                pass

    # -----------------------------------------------------------------
    # Construção da UI
    # -----------------------------------------------------------------
    def _build_ui(self, root: QVBoxLayout) -> None:
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # Menu
        try:
            menu = QHBoxLayout()
            menu.setSpacing(4)

            self.cb_mode = QComboBox()
            self.cb_mode.addItem(_t("Padrão ☰"), "standard")
            self.cb_mode.addItem(_t("Científica ☰"), "scientific")
            self.cb_mode.setCurrentIndex(1 if self.mode == "scientific" else 0)
            self.cb_mode.currentIndexChanged.connect(self._on_mode_changed)
            menu.addWidget(self.cb_mode)

            self.btn_angle = QPushButton(_t("DEG"))
            self.btn_angle.setFixedWidth(56)
            self.btn_angle.clicked.connect(self._toggle_angle)
            menu.addWidget(self.btn_angle)

            menu.addStretch(1)

            self.btn_hist = QPushButton(_t("Histórico 📋"))
            self.btn_hist.setStyleSheet(
                "QPushButton{font-size:11px;padding:3px 6px;}"
            )
            self.btn_hist.clicked.connect(self._copy_history)
            menu.addWidget(self.btn_hist)

            self.btn_inject = QPushButton(_t("Injetar ↑"))
            self.btn_inject.setStyleSheet(
                "QPushButton{background:#e67e22;color:white;font-weight:bold;"
                "border:none;border-radius:4px;padding:3px 8px;"
                "font-size:11px;}"
                "QPushButton:hover{background:#d35400;}"
                "QPushButton:disabled{background:#888;}"
            )
            self.btn_inject.clicked.connect(self._inject)
            menu.addWidget(self.btn_inject)

            root.addLayout(menu)
        except Exception:
            _log("_build_ui: menu falhou:\n" + traceback.format_exc())

        # Display principal (4 linhas grandes + atual)
        try:
            display_box = QVBoxLayout()
            display_box.setSpacing(0)

            self.lbl_hist = [QLabel("") for _ in range(4)]
            for lbl in self.lbl_hist:
                lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                lbl.setStyleSheet(
                    "color:#00cc00;background:#1a1a1a;padding:2px 8px;"
                    "font-size:12px;"
                )
                lbl.setMinimumHeight(16)
                display_box.addWidget(lbl)

            self.lbl_current = QLabel("0")
            self.lbl_current.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.lbl_current.setStyleSheet(
                "color:#00ff00;background:#000;padding:4px 8px;"
                "font-size:22px;font-weight:bold;border-radius:4px;"
            )
            self.lbl_current.setMinimumHeight(38)
            display_box.addWidget(self.lbl_current)

            root.addLayout(display_box)
        except Exception:
            _log("_build_ui: display falhou:\n" + traceback.format_exc())

        # ── Histórico extenso (rolável) ──
        self._build_extended_history(root)

        # Teclados
        try:
            self.grid_standard = QGridLayout()
            self.grid_standard.setSpacing(3)
            self._build_standard()
            root.addLayout(self.grid_standard)
        except Exception:
            _log("_build_ui: teclado padrão falhou:\n"
                 + traceback.format_exc())

        try:
            self.grid_scientific = QGridLayout()
            self.grid_scientific.setSpacing(2)
            self._build_scientific()
            root.addLayout(self.grid_scientific)
        except Exception:
            _log("_build_ui: teclado científico falhou:\n"
                 + traceback.format_exc())

        try:
            self._apply_mode_visibility()
            self._update_angle_button()
            self._refresh_display()
        except Exception:
            _log("_build_ui: apply/update/refresh falhou:\n"
                 + traceback.format_exc())

        try:
            self._install_keyboard()
        except Exception:
            _log("_build_ui: _install_keyboard falhou:\n"
                 + traceback.format_exc())

        try:
            self._connect_sync()
        except Exception:
            _log("_build_ui: _connect_sync falhou:\n"
                 + traceback.format_exc())


    # =====================================================================
    # DISPLAY + HISTÓRICO EXTENSO (estilo editor de texto: novo embaixo)
    # =====================================================================
    
    def _build_extended_history(self, root: QVBoxLayout) -> None:
        """Histórico rolável, altura dinâmica, ordem 'editor de texto':
        entradas mais antigas em cima, mais recentes embaixo, stretch no topo
        (para alinhar o bloco embaixo quando há poucas linhas)."""
        try:
            from PySide6.QtWidgets import (
                QScrollArea, QFrame, QToolButton, QSizePolicy as _QSP,
            )
    
            header = QHBoxLayout()
            header.setSpacing(4)
    
            self.btn_hist_toggle = QToolButton()
            self.btn_hist_toggle.setText(_t("Histórico extenso"))
            self.btn_hist_toggle.setCheckable(True)
            self.btn_hist_toggle.setChecked(True)
            self.btn_hist_toggle.setToolButtonStyle(
                Qt.ToolButtonTextBesideIcon
            )
            self.btn_hist_toggle.setArrowType(Qt.DownArrow)
            header.addWidget(self.btn_hist_toggle)
    
            header.addStretch(1)
    
            self.lbl_hist_count = QLabel(
                f"({len(self.history)}/{self.history_limit})"
            )
            self.lbl_hist_count.setStyleSheet("color:#888;font-size:10px;")
            header.addWidget(self.lbl_hist_count)
    
            self.cb_hist_limit = QComboBox()
            for n in self._HIST_OPTIONS:
                self.cb_hist_limit.addItem(f"{n}", n)
            idx = self.cb_hist_limit.findData(self.history_limit)
            if idx >= 0:
                self.cb_hist_limit.setCurrentIndex(idx)
            self.cb_hist_limit.currentIndexChanged.connect(
                self._on_hist_limit_changed
            )
            header.addWidget(self.cb_hist_limit)
    
            root.addLayout(header)
    
            # Scroll
            self.hist_scroll = QScrollArea()
            self.hist_scroll.setWidgetResizable(True)
            self.hist_scroll.setFrameShape(QFrame.NoFrame)
            self.hist_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            self.hist_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            self.hist_scroll.setMinimumHeight(60)
            self.hist_scroll.setMaximumHeight(16777215)
            self.hist_scroll.setSizePolicy(_QSP.Expanding, _QSP.Expanding)
            self.hist_scroll.setVisible(True)
    
            self.hist_inner = QWidget()
            self.hist_inner.setSizePolicy(_QSP.Expanding, _QSP.Expanding)
            self.hist_layout = QVBoxLayout(self.hist_inner)
            self.hist_layout.setContentsMargins(0, 0, 0, 0)
            self.hist_layout.setSpacing(0)
            # STRETCH NO TOPO (para o bloco grudar embaixo quando tem poucas
            # linhas — comportamento de editor de texto).
            self.hist_layout.addStretch(1)
    
            self.hist_scroll.setWidget(self.hist_inner)
            root.addWidget(self.hist_scroll, 1)
    
            def _on_toggle(checked: bool) -> None:
                try:
                    self.hist_scroll.setVisible(checked)
                    self.btn_hist_toggle.setArrowType(
                        Qt.DownArrow if checked else Qt.RightArrow
                    )
                except Exception:
                    traceback.print_exc()
    
            self.btn_hist_toggle.toggled.connect(_on_toggle)
        except Exception:
            _log("_build_extended_history falhou:\n"
                 + traceback.format_exc())
    
    
    def _rebuild_hist_rows(self) -> None:
        """Reconstrói as linhas do histórico rolável.
    
        Ordem 'editor de texto':
          - entradas mais antigas em cima
          - entradas mais recentes embaixo
          - stretch no TOPO (deixa o bloco alinhado embaixo com poucas linhas)
        """
        try:
            # Remove só os widgets existentes; preserva o stretch no topo.
            # Como o stretch está na posição 0, removemos widgets de
            # posições > 0 (as linhas ficam empilhadas em 1..N-1).
            while self.hist_layout.count() > 1:
                # Pega o último item (evita mexer no stretch do topo)
                item = self.hist_layout.takeAt(self.hist_layout.count() - 1)
                w = item.widget()
                if w is not None:
                    w.deleteLater()
    
            shown = self.history[-self.history_limit:]
            for line in shown:
                lbl = QLabel(line.replace(".", ","))
                lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                lbl.setStyleSheet(
                    "color:#00cc00;background:#111;padding:1px 8px;"
                    "font-size:11px;"
                )
                lbl.setMinimumHeight(14)
                # Insere sempre no FIM (antes do stretch que está no topo)
                self.hist_layout.addWidget(lbl)
    
            if hasattr(self, "lbl_hist_count"):
                self.lbl_hist_count.setText(
                    f"({len(self.history)}/{self.history_limit})"
                )
    
            # Auto-scroll para o fim (mais recente) — igual editor
            if hasattr(self, "hist_scroll") and self.hist_scroll.isVisible():
                QTimer.singleShot(0, self._scroll_hist_to_bottom)
        except Exception:
            _log("_rebuild_hist_rows falhou:\n" + traceback.format_exc())
    
    
    def _scroll_hist_to_bottom(self) -> None:
        try:
            if not hasattr(self, "hist_scroll"):
                return
            sb = self.hist_scroll.verticalScrollBar()
            if sb is not None:
                sb.setValue(sb.maximum())
        except Exception:
            pass
    
    
    def _scroll_hist_to_bottom(self) -> None:
        """Move a barra de rolagem vertical para o fim (mais recente)."""
        try:
            if not hasattr(self, "hist_scroll"):
                return
            sb = self.hist_scroll.verticalScrollBar()
            if sb is not None:
                sb.setValue(sb.maximum())
        except Exception:
            pass
    
   
    def _on_hist_limit_changed(self, idx: int) -> None:
        try:
            data = self.cb_hist_limit.itemData(idx)
            if data is None:
                return
            new_limit = int(data)
            if new_limit == self.history_limit:
                return
            self.history_limit = new_limit
            # Trunca o histórico atual para o novo limite
            if len(self.history) > self.history_limit:
                self.history = self.history[-self.history_limit:]
            # Limpa o cache e reconstrói
            self._persist()
            self._rebuild_hist_rows()
            _log(f"_on_hist_limit_changed: limite={self.history_limit}")
        except Exception:
            traceback.print_exc()

    # -----------------------------------------------------------------
    # Teclados visuais
    # -----------------------------------------------------------------
    def _btn(self, text, slot, style: str = "", small: bool = False):
        b = QPushButton(text)
        try:
            b.clicked.connect(slot)
        except Exception:
            _log(f"_btn: connect falhou para {text!r}:\n"
                 + traceback.format_exc())
        if small:
            b.setStyleSheet(
                "QPushButton{background:#bcbcbc;color:#333;font-size:11px;"
                "border:none;border-radius:4px;padding:2px;}"
                "QPushButton:hover{background:#aeaeae;}"
            )
        elif style == "op":
            b.setStyleSheet(
                "QPushButton{background:#ff9500;color:white;font-size:13px;"
                "border:none;border-radius:4px;padding:3px;}"
                "QPushButton:hover{background:#e08500;}"
            )
        elif style == "clr":
            b.setStyleSheet(
                "QPushButton{background:#ff3b30;color:white;font-size:13px;"
                "border:none;border-radius:4px;padding:3px;}"
                "QPushButton:hover{background:#d32f2f;}"
            )
        elif style == "paren":
            b.setStyleSheet(
                "QPushButton{background:#3498db;color:white;font-weight:bold;"
                "font-size:13px;border:none;border-radius:4px;padding:3px;}"
                "QPushButton:hover{background:#2980b9;}"
            )
        else:
            b.setStyleSheet(
                "QPushButton{background:#e0e0e0;color:#000;font-size:13px;"
                "border:none;border-radius:4px;padding:3px;}"
                "QPushButton:hover{background:#d4d4d4;}"
            )
        b.setMinimumHeight(30)
        return b

    def _build_standard(self) -> None:
        g = self.grid_standard
        cells = [
            ("CE", lambda: self._clear_current(), "clr"),
            ("C",  lambda: self._clear_all(),     "clr"),
            ("⌫",  lambda: self._backspace(),     "fun"),
            ("/",  lambda: self._input_direct("/"), "op"),
            ("7",  lambda: self._input_direct("7")),
            ("8",  lambda: self._input_direct("8")),
            ("9",  lambda: self._input_direct("9")),
            ("*",  lambda: self._input_direct("*"), "op"),
            ("4",  lambda: self._input_direct("4")),
            ("5",  lambda: self._input_direct("5")),
            ("6",  lambda: self._input_direct("6")),
            ("-",  lambda: self._input_direct("-"), "op"),
            ("1",  lambda: self._input_direct("1")),
            ("2",  lambda: self._input_direct("2")),
            ("3",  lambda: self._input_direct("3")),
            ("+",  lambda: self._input_direct("+"), "op"),
            ("±",  lambda: self._change_sign(), "fun"),
            ("0",  lambda: self._input_direct("0")),
            (",",  lambda: self._input_dot()),
            ("=",  lambda: self._calculate(), "op"),
        ]
        for i, item in enumerate(cells):
            if len(item) == 3:
                txt, slot, style = item
            else:
                txt, slot = item
                style = ""
            small = (style == "fun")
            g.addWidget(self._btn(txt, slot, style, small), i // 4, i % 4)

    def _build_scientific(self) -> None:
        g = self.grid_scientific
        rows = [
            [("(",  lambda: self._input_direct("("), "paren"),
             (")",  lambda: self._input_direct(")"), "paren"),
             ("",   None, ""),
             ("CE", lambda: self._clear_current(), "clr"),
             ("C",  lambda: self._clear_all(), "clr")],
            [("Rand", lambda: self._input_sci("Math.random", "rand"), "fun"),
             ("mod",  lambda: self._input_direct("mod"), "fun"),
             ("log",  lambda: self._input_sci("Math.log10", "log"), "fun"),
             ("ln",   lambda: self._input_sci("Math.log", "ln"), "fun"),
             ("x!",   lambda: self._input_direct("fact"), "fun")],
            [("e",   lambda: self._input_sci("Math.E", "e"), "fun"),
             ("π",   lambda: self._input_sci("Math.PI", "π"), "fun"),
             ("sin", lambda: self._input_sci("Math.sin", "sin"), "fun"),
             ("cos", lambda: self._input_sci("Math.cos", "cos"), "fun"),
             ("tan", lambda: self._input_sci("Math.tan", "tan"), "fun")],
            [("√x", lambda: self._input_sci("Math.sqrt", "√"), "fun"),
             ("x²", lambda: self._input_direct("sqr"), "fun"),
             ("x³", lambda: self._input_direct("cube"), "fun"),
             ("xʸ", lambda: self._input_direct("pow"), "fun"),
             ("/",  lambda: self._input_direct("/"), "op")],
            [("x⁻¹", lambda: self._input_direct("inv"), "fun"),
             ("7",   lambda: self._input_direct("7")),
             ("8",   lambda: self._input_direct("8")),
             ("9",   lambda: self._input_direct("9")),
             ("*",   lambda: self._input_direct("*"), "op")],
            [("10ˣ", lambda: self._input_sci("Math.pow10", "10^"), "fun"),
             ("4",   lambda: self._input_direct("4")),
             ("5",   lambda: self._input_direct("5")),
             ("6",   lambda: self._input_direct("6")),
             ("-",   lambda: self._input_direct("-"), "op")],
            [("%",  lambda: self._input_direct("pct"), "fun"),
             ("1",  lambda: self._input_direct("1")),
             ("2",  lambda: self._input_direct("2")),
             ("3",  lambda: self._input_direct("3")),
             ("+",  lambda: self._input_direct("+"), "op")],
            [("±",  lambda: self._change_sign(), "fun"),
             ("0",  lambda: self._input_direct("0")),
             (",",  lambda: self._input_dot()),
             ("⌫",  lambda: self._backspace(), "fun"),
             ("=",  lambda: self._calculate(), "op")],
        ]
        for r, row in enumerate(rows):
            for c, item in enumerate(row):
                if len(item) == 3:
                    txt, slot, style = item
                elif len(item) == 2:
                    txt, slot = item
                    style = ""
                else:
                    txt, slot, style = ("", None, "")
                if slot is None or txt == "":
                    g.addWidget(QWidget(), r, c)
                    continue
                small = (style == "fun")
                g.addWidget(self._btn(txt, slot, style, small), r, c)

    # -----------------------------------------------------------------
    # Modos
    # -----------------------------------------------------------------
    def _apply_mode_visibility(self) -> None:
        is_sci = (self.mode == "scientific")
        for i in range(self.grid_standard.count()):
            w = self.grid_standard.itemAt(i).widget()
            if w is not None:
                w.setVisible(not is_sci)
        for i in range(self.grid_scientific.count()):
            w = self.grid_scientific.itemAt(i).widget()
            if w is not None:
                w.setVisible(is_sci)
        self.btn_angle.setVisible(is_sci)

    def _on_mode_changed(self, idx: int) -> None:
        try:
            data = self.cb_mode.itemData(idx)
            self.mode = str(data) if data else "standard"
            self._apply_mode_visibility()
            self._clear_all()
            self._persist()
            self._broadcast_state()
        except Exception:
            traceback.print_exc()

    def _update_angle_button(self) -> None:
        if self.is_rad:
            self.btn_angle.setText(_t("RAD"))
            self.btn_angle.setStyleSheet(
                "QPushButton{background:#e67e22;color:white;font-weight:bold;"
                "border-radius:4px;padding:3px 6px;font-size:11px;}"
            )
        else:
            self.btn_angle.setText(_t("DEG"))
            self.btn_angle.setStyleSheet(
                "QPushButton{background:#2c3e50;color:white;font-weight:bold;"
                "border-radius:4px;padding:3px 6px;font-size:11px;}"
            )

    def _toggle_angle(self) -> None:
        try:
            self.is_rad = not self.is_rad
            self._update_angle_button()
            self._persist()
            self._broadcast_state()
        except Exception:
            traceback.print_exc()

    # -----------------------------------------------------------------
    # Display + histórico
    # -----------------------------------------------------------------
    
    def _refresh_display(self) -> None:
        """Atualiza display atual + 4 linhas fixas + histórico rolável.
    
        Ordem das 4 linhas fixas: igual ao histórico extenso (editor de texto)
        → entradas mais antigas em cima, mais recentes embaixo.
        """
        try:
            # Linha atual (grande)
            self.lbl_current.setText(
                self.current_input.replace(".", ",")
                if self.current_input else "0"
            )
    
            # 4 linhas fixas — mais antiga em cima, mais recente embaixo.
            n = len(self.history)
            for i in range(4):
                # i=0 → 4ª mais recente (topo); i=3 → mais recente (baixo)
                src = n - 4 + i
                text = (self.history[src]
                        if 0 <= src < n else "")
                self.lbl_hist[i].setText(
                    text.replace(".", ",") if text else ""
                )
    
            # Histórico extenso (mesma ordem: antigo em cima, novo embaixo)
            self._rebuild_hist_rows()
            self._persist()
        except Exception:
            traceback.print_exc()
       

    def _push_history(self, line: str) -> None:
        self.history.append(line)
        # Mantém apenas as últimas N entradas
        if len(self.history) > self.history_limit:
            self.history = self.history[-self.history_limit:]

    def _persist(self) -> None:
        try:
            _save_state({
                "history": self.history[-self.history_limit:],
                "history_limit": self.history_limit,
                "is_rad": self.is_rad,
                "mode": self.mode,
            })
        except Exception:
            pass

    # -----------------------------------------------------------------
    # Entrada
    # -----------------------------------------------------------------
    _OPERATORS = {"+", "-", "*", "/", "pow", "mod", "pct",
                  "sqr", "cube", "inv", "fact"}

    def _input_direct(self, char: str) -> None:
        try:
            visible, internal = char, char
            if char == "pow":  visible, internal = "^",   "pow"
            if char == "sqr":  visible, internal = "²",   "sqr"
            if char == "cube": visible, internal = "³",   "cube"
            if char == "inv":  visible, internal = "⁻¹",  "inv"
            if char == "fact": visible, internal = "!",   "fact"
            if char == "mod":  visible, internal = " mod ", "mod"
            if char == "pct":  visible, internal = "%",   "pct"

            is_op = char in self._OPERATORS

            if self.should_reset:
                if is_op:
                    self.should_reset = False
                else:
                    self.current_input = "0"
                    self.internal_expr = "0"
                    self.should_reset = False

            err = _t("Erro")
            if self.current_input in ("0", err):
                if is_op:
                    self.current_input = "0" + visible
                    self.internal_expr = "0" + internal
                else:
                    self.current_input = visible
                    self.internal_expr = internal
            else:
                self.current_input += visible
                self.internal_expr += internal
            self._refresh_display()
            self._broadcast_state()
        except Exception:
            _log("_input_direct falhou:\n" + traceback.format_exc())

    def _input_dot(self) -> None:
        try:
            err = _t("Erro")
            if self.should_reset or self.current_input == err:
                self.current_input = "0."
                self.internal_expr = "0."
                self.should_reset = False
            elif not self.current_input.endswith("."):
                self.current_input += "."
                self.internal_expr += "."
            self._refresh_display()
            self._broadcast_state()
        except Exception:
            traceback.print_exc()

    def _input_sci(self, js_name: str, visible_name: str) -> None:
        try:
            err = _t("Erro")
            if self.should_reset or self.current_input == err:
                self.current_input = "0"
                self.internal_expr = "0"
                self.should_reset = False

            is_const = js_name in ("Math.PI", "Math.E", "Math.random")
            suffix_vis = "" if is_const else "("
            suffix_int = "" if is_const else "("

            if self.current_input == "0":
                self.current_input = visible_name + suffix_vis
                self.internal_expr = js_name + suffix_int
            else:
                self.current_input += visible_name + suffix_vis
                self.internal_expr += js_name + suffix_int
            self._refresh_display()
            self._broadcast_state()
        except Exception:
            traceback.print_exc()

    def _change_sign(self) -> None:
        try:
            if self.should_reset:
                self.should_reset = False
            err = _t("Erro")
            if self.current_input in ("0", err):
                return
            if (self.current_input.startswith("-(")
                    and self.current_input.endswith(")")):
                self.current_input = self.current_input[2:-1]
                self.internal_expr = self.internal_expr[2:-1]
            else:
                self.current_input = "-(" + self.current_input + ")"
                self.internal_expr = "-(" + self.internal_expr + ")"
            self._refresh_display()
            self._broadcast_state()
        except Exception:
            traceback.print_exc()

    def _backspace(self) -> None:
        try:
            if self.should_reset:
                self.should_reset = False
                return
            if len(self.current_input) > 1:
                self.current_input = self.current_input[:-1]
                self.internal_expr = self.internal_expr[:-1]
            else:
                self.current_input = "0"
                self.internal_expr = "0"
            self._refresh_display()
            self._broadcast_state()
        except Exception:
            traceback.print_exc()

    def _clear_current(self) -> None:
        try:
            self.current_input = "0"
            self.internal_expr = "0"
            self.should_reset = False
            self._refresh_display()
            self._broadcast_state()
        except Exception:
            traceback.print_exc()

    def _clear_all(self) -> None:
        try:
            self.current_input = "0"
            self.internal_expr = "0"
            self.should_reset = False
            self.history = []
            self._refresh_display()
            self._broadcast_state()
        except Exception:
            traceback.print_exc()

    # -----------------------------------------------------------------
    # Formatação
    # -----------------------------------------------------------------
    @staticmethod
    def _fmt(v) -> str:
        if isinstance(v, float) and v.is_integer():
            v = int(v)
        s = repr(v) if isinstance(v, float) else str(v)
        return s.replace(".", ",")

    # -----------------------------------------------------------------
    # Cálculo
    # -----------------------------------------------------------------
    def _calculate(self) -> None:
        try:
            err = _t("Erro")
            if self.current_input in ("0", err) or not self.internal_expr:
                return
            equation = self.current_input
            expr = self.internal_expr.replace(",", ".")

            expr = expr.replace("Math.PI", "math.pi")
            expr = expr.replace("Math.E", "math.e")
            expr = expr.replace("Math.random", "random.random()")
            expr = _replace_func1(expr, "Math.pow10", "pow10")

            angular = "1" if self.is_rad else "(math.pi/180)"
            expr = _replace_func1(expr, "Math.sin", "math.sin", f"*{angular}")
            expr = _replace_func1(expr, "Math.cos", "math.cos", f"*{angular}")
            expr = _replace_func1(expr, "Math.tan", "math.tan", f"*{angular}")

            expr = _replace_func1(expr, "Math.log10", "math.log10")
            expr = _replace_func1(expr, "Math.log",   "math.log")
            expr = _replace_func1(expr, "Math.sqrt",  "math.sqrt")

            expr = _replace_pow(expr)
            expr = _replace_postfix(expr, "sqr",  "**2")
            expr = _replace_postfix(expr, "cube", "**3")
            expr = _replace_postfix(expr, "inv",  "**-1")
            expr = _replace_postfix(expr, "fact", "__fact")
            expr = expr.replace("mod", "%")
            expr = _replace_postfix(expr, "pct", "/100")
            expr = _replace_factorial(expr)
            expr = _add_implicit_mul(expr)
            expr = _auto_close_parens(expr)

            result = _safe_eval(expr)
            if result is None:
                raise ValueError("resultado None")
            result = round(float(result), 12)

            line = f"{equation} = {self._fmt(result)}"
            self._push_history(line)
            self.current_input = self._fmt(result)
            self.internal_expr = str(result)
            self.should_reset = True
            self._refresh_display()
            self._broadcast_state()
        except Exception:
            _log("_calculate falhou:\n" + traceback.format_exc())
            try:
                err = _t("Erro")
                equation = getattr(self, "current_input", "?")
                self._push_history(f"{equation} = {err}")
                self.current_input = err
                self.internal_expr = "0"
                self.should_reset = True
                self._refresh_display()
                self._broadcast_state()
            except Exception:
                traceback.print_exc()

    # -----------------------------------------------------------------
    # Histórico / Injetar
    # -----------------------------------------------------------------
    def _copy_history(self) -> None:
        try:
            lines = [l for l in self.history if l] + [self.current_input]
            QApplication.clipboard().setText("\n".join(lines))
            self._flash_button(
                self.btn_hist, _t("Copiado! ✔"), _t("Histórico 📋")
            )
        except Exception:
            traceback.print_exc()

    def _inject(self) -> None:
        try:
            value = self.current_input
            target = _find_active_vcb()
            if target is not None:
                if _inject_into_widget(target, value):
                    self._flash_button(
                        self.btn_inject, _t("Injetado! ✔"), _t("Injetar ↑")
                    )
                    return
                if _inject_via_keyevents(target, value):
                    self._flash_button(
                        self.btn_inject, _t("Injetado! ✔"), _t("Injetar ↑")
                    )
                    return
            QApplication.clipboard().setText(value)
            self._flash_button(
                self.btn_inject, _t("Copiado! ✔"), _t("Injetar ↑")
            )
        except Exception:
            _log("_inject falhou:\n" + traceback.format_exc())

    def _flash_button(self, btn: QPushButton, success_text: str,
                      original_text: str) -> None:
        try:
            btn.setText(success_text)
            btn.setEnabled(False)
        except Exception:
            return

        def _restore():
            try:
                btn.setText(original_text)
                btn.setEnabled(True)
            except Exception:
                pass

        QTimer.singleShot(1200, _restore)

    # -----------------------------------------------------------------
    # Ciclo de vida
    # -----------------------------------------------------------------
    def _mark_dead(self) -> None:
        self._alive = False

# =========================================================================
# DIÁLOGO
# =========================================================================

class CalculatorDialog(_CalculatorBase, QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_state()
        try:
            self.setWindowFlags(
                Qt.Window
                | Qt.WindowTitleHint
                | Qt.WindowCloseButtonHint
                | Qt.WindowMinMaxButtonsHint
            )
        except Exception:
            pass
        self.setWindowTitle(_t("Calculadora"))
        self.resize(320, 520)
        self.setMinimumSize(280, 440)
        self.setMaximumSize(520, 760)
        root = QVBoxLayout(self)
        try:
            self._build_ui(root)
        except Exception:
            _log("CalculatorDialog: _build_ui falhou:\n"
                 + traceback.format_exc())
        _log(f"CalculatorDialog construído (lang={_lang_key()})")

    def closeEvent(self, event):
        # Desconecta do bus para não receber mais sinais
        try:
            _sync_bus.state_changed.disconnect(self._on_remote_state)
        except Exception:
            pass
        self._mark_dead()
        try:
            super().closeEvent(event)
        except Exception:
            event.accept()


# =========================================================================
# PAINEL
# =========================================================================

class CalculatorPanel(_CalculatorBase, QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_state()
        root = QVBoxLayout(self)
        try:
            self._build_ui(root)
        except Exception:
            _log("CalculatorPanel: _build_ui falhou:\n"
                 + traceback.format_exc())
        _log(f"CalculatorPanel construído (lang={_lang_key()})")

    def closeEvent(self, event):
        try:
            _sync_bus.state_changed.disconnect(self._on_remote_state)
        except Exception:
            pass
        self._mark_dead()
        try:
            super().closeEvent(event)
        except Exception:
            event.accept()


# =========================================================================
# RUN
# =========================================================================

def run(main_window=None):
    global _dialog_instance
    _install_vcb_tracker()

    if _dialog_instance is not None:
        try:
            _dialog_instance.isVisible()
        except RuntimeError:
            _dialog_instance = None
        except Exception:
            _dialog_instance = None

    if _dialog_instance is None:
        try:
            _dialog_instance = CalculatorDialog(parent=main_window)
        except Exception:
            try:
                _dialog_instance = CalculatorDialog(parent=None)
            except Exception:
                _log("run(): falha definitiva:\n" + traceback.format_exc())
                return

    dlg = _dialog_instance
    try:
        if dlg.isMinimized():
            dlg.showNormal()
        else:
            dlg.show()
        dlg.raise_()
        dlg.activateWindow()
    except Exception:
        _log("run(): falha ao exibir:\n" + traceback.format_exc())


# =========================================================================
# ÍCONES
# =========================================================================

_HERE = os.path.dirname(os.path.abspath(__file__))
_ICONS_DIR = (
    os.path.join(_HERE, "icons")
    if os.path.isdir(os.path.join(_HERE, "icons"))
    else None
)


def _fallback_icon() -> QIcon:
    try:
        style = QApplication.style()
        if style is not None:
            return style.standardIcon(QStyle.SP_ComputerIcon)
    except Exception:
        pass
    return QIcon()


def _load_themed_icon(base_name: str, main_window) -> QIcon:
    if not _ICONS_DIR:
        return _fallback_icon()
    if base_name.endswith(".svg"):
        base_name = base_name[:-4]

    is_dark = True
    try:
        if main_window is not None:
            palette = main_window.palette()
            bg_color = palette.color(QPalette.Window)
            is_dark = bg_color.lightness() < 128
    except Exception:
        pass

    if not is_dark:
        light_path = os.path.join(_ICONS_DIR, f"{base_name}_light.svg")
        if os.path.isfile(light_path):
            return QIcon(light_path)
    default_path = os.path.join(_ICONS_DIR, f"{base_name}.svg")
    if os.path.isfile(default_path):
        return QIcon(default_path)
    return QIcon()


def _load_icon_with_fallback(base_name: str, main_window,
                             fallback_name: str = "calculator") -> QIcon:
    icon = _load_themed_icon(base_name, main_window)
    if not icon.isNull():
        return icon
    icon = _load_themed_icon(fallback_name, main_window)
    if not icon.isNull():
        return icon
    return _fallback_icon()


# =========================================================================
# PAINEL LATERAL
# =========================================================================

_PANEL_GROUP_TITLES = ("propriedades", "bim", "terreno", "renderiz")


def _titulo_do_grupo(title) -> bool:
    t = (title or "").strip().lower()
    if not t:
        return False
    if t in ("ia", "i.a", "i.a."):
        return True
    return any(k in t for k in _PANEL_GROUP_TITLES)


def _attach_calculator_panel(mw):
    if mw is None:
        return None

    try:
        panel = CalculatorPanel(mw)
    except Exception:
        _log("_attach_calculator_panel: painel não construído:\n"
             + traceback.format_exc())
        return None

    try:
        tabs = list(mw.findChildren(QTabWidget))
    except Exception:
        tabs = []
    melhor, melhor_score = None, 0
    for tw in tabs:
        try:
            labels = [tw.tabText(i) for i in range(tw.count())]
        except Exception:
            labels = []
        score = sum(1 for lbl in labels if _titulo_do_grupo(lbl))
        if score > melhor_score:
            melhor, melhor_score = tw, score
    if melhor is not None:
        try:
            melhor.addTab(panel, _t("Calculadora"))
            melhor.setCurrentWidget(panel)
            _log("Painel Calculadora adicionado como aba em QTabWidget.")
            return panel
        except Exception:
            traceback.print_exc()

    try:
        docks = mw.findChildren(QDockWidget)
    except Exception:
        docks = []
    if docks and hasattr(mw, "tabifyDockWidget"):
        anchor = None
        for d in docks:
            if _titulo_do_grupo(d.windowTitle()):
                anchor = d
                break
        if anchor is None:
            visiveis = [d for d in docks if d.isVisible()]
            anchor = (visiveis or docks)[0]
        area = Qt.RightDockWidgetArea
        try:
            a = mw.dockWidgetArea(anchor)
            if a in (Qt.LeftDockWidgetArea, Qt.RightDockWidgetArea,
                     Qt.TopDockWidgetArea, Qt.BottomDockWidgetArea):
                area = a
        except Exception:
            pass
        try:
            dock = QDockWidget(_t("Calculadora"), mw)
            dock.setObjectName("igz_tb_calculator_dock")
            dock.setWidget(panel)
            dock.setAllowedAreas(
                Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea
            )
            mw.addDockWidget(area, dock)
            mw.tabifyDockWidget(anchor, dock)
            dock.show()
            dock.raise_()
            panel._dock = dock
            _log("Painel Calculadora tabificado junto a dock existente.")
            return panel
        except Exception:
            traceback.print_exc()

    if hasattr(mw, "addDockWidget"):
        try:
            dock = QDockWidget(_t("Calculadora"), mw)
            dock.setObjectName("igz_tb_calculator_dock")
            dock.setWidget(panel)
            dock.setAllowedAreas(
                Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea
            )
            mw.addDockWidget(Qt.RightDockWidgetArea, dock)
            panel._dock = dock
            _log("Painel Calculadora criado como dock próprio (fallback).")
            return panel
        except Exception:
            traceback.print_exc()

    _log("main_window sem addDockWidget/QTabWidget (painel ignorado).")
    return None


# =========================================================================
# TOOLBAR
# =========================================================================

def create_toolbar(main_window, app=None):
    toolbar = QToolBar("Calculadora", main_window)
    toolbar.setObjectName("igz_tb_calculator")
    toolbar.setWindowTitle(_t("Calculadora"))

    try:
        toolbar.setToolButtonStyle(Qt.ToolButtonIconOnly)
    except Exception:
        pass

    # Botão 1 — abre o diálogo
    icon_dlg = _load_icon_with_fallback("calculator", main_window)
    action_dlg = QAction(icon_dlg, _t("Calculadora"), main_window)
    action_dlg.setToolTip(_t("Abre a calculadora em uma janela flutuante."))
    action_dlg.triggered.connect(lambda checked=False: run(main_window))
    toolbar.addAction(action_dlg)

    # Botão 2 — painel lateral
    panel = _attach_calculator_panel(main_window)
    if panel is not None:
        icon_panel = _load_icon_with_fallback(
            "calculator_panel", main_window, fallback_name="calculator"
        )

        # -----------------------------------------------------------------
        # Ação unificada: mostra + traz para frente + foca.
        # - Se estiver escondido → mostra.
        # - Se estiver visível mas atrás → só traz para frente.
        # - Se estiver visível e na frente → esconde (toggle real).
        # -----------------------------------------------------------------
        def _toggle_or_show_panel(checked: bool = False) -> None:
            try:
                dock = getattr(panel, "_dock", None)

                # --- Caso 1: painel virou aba de QTabWidget ------------
                if dock is None:
                    # Encontra o QTabWidget que contém o panel
                    tabs = main_window.findChildren(QTabWidget)
                    target_tab = None
                    for tw in tabs:
                        idx = tw.indexOf(panel)
                        if idx >= 0:
                            target_tab = tw
                            break

                    if target_tab is not None:
                        # Já está na aba visível?
                        already_visible = (
                            target_tab.isVisible()
                            and target_tab.currentWidget() is panel
                        )
                        # Se está visível e na frente → esconde (toggle)
                        if already_visible:
                            target_tab.setCurrentWidget(target_tab.widget(0)
                                                        if target_tab.count() > 1
                                                        else panel)
                            # Fallback: se não há outra aba, não esconde
                            if target_tab.currentWidget() is panel:
                                _bring_tab_to_front(target_tab, panel)
                            return
                        # Senão: mostra + foca
                        _bring_tab_to_front(target_tab, panel)
                        return

                    # Sem QTabWidget: só mostra a janela principal
                    try:
                        main_window.show()
                        main_window.raise_()
                        main_window.activateWindow()
                    except Exception:
                        pass
                    return

                # --- Caso 2: painel virou QDockWidget ------------------
                # Já está visível?
                was_visible = dock.isVisible()
                # Está aba ativa? (se está tabificado, precisa ser a ativa)
                try:
                    is_current = dock.isVisible() and not dock.isFloating() \
                        and dock.visibleRegion().isEmpty() is False
                except Exception:
                    is_current = dock.isVisible()

                if was_visible and is_current:
                    # Visível e na frente → esconde (toggle)
                    dock.hide()
                else:
                    # Escondido OU atrás → mostra e traz para frente
                    dock.show()
                    dock.raise_()

                    # Se está tabificado com outras docks, ativa a aba
                    try:
                        dock.raise_()  # garante que é a aba ativa
                    except Exception:
                        pass

                    # Foca o painel para dar feedback visual
                    try:
                        panel.setFocus()
                    except Exception:
                        pass

                    # Traz a janela principal para frente (se estava atrás)
                    try:
                        main_window.raise_()
                        main_window.activateWindow()
                    except Exception:
                        pass

                # Feedback visual: marca o botão como checked enquanto
                # o painel estiver visível (para o usuário ver o estado).
                try:
                    if hasattr(_toggle_button_ref, "current"):
                        _toggle_button_ref.current.setChecked(
                            dock.isVisible()
                        )
                except Exception:
                    pass
            except Exception:
                _log("_toggle_or_show_panel falhou:\n"
                     + traceback.format_exc())

        # Helper: traz uma aba para frente e foca
        def _bring_tab_to_front(tab_widget, target_widget) -> None:
            try:
                tab_widget.setCurrentWidget(target_widget)
                tab_widget.raise_()
                try:
                    target_widget.setFocus()
                except Exception:
                    pass
                try:
                    main_window.raise_()
                    main_window.activateWindow()
                except Exception:
                    pass
            except Exception:
                traceback.print_exc()

        # Referência mutável para o botão (usada no feedback acima)
        _toggle_button_ref = {"current": None}

        # Cria a QAction
        icon_ok = icon_panel if not icon_panel.isNull() else _fallback_icon()
        action_panel = QAction(icon_ok, _t("Painel Calculadora"),
                               main_window)
        action_panel.setToolTip(
            _t("Mostrar/ocultar a calculadora no painel lateral.")
        )
        action_panel.setCheckable(True)

        # Estado inicial: reflete se o painel está visível
        try:
            dock = getattr(panel, "_dock", None)
            if dock is not None:
                action_panel.setChecked(dock.isVisible())
            else:
                # Achou como aba?
                for tw in main_window.findChildren(QTabWidget):
                    if tw.indexOf(panel) >= 0:
                        action_panel.setChecked(
                            tw.isVisible() and tw.currentWidget() is panel
                        )
                        break
        except Exception:
            pass

        # Connect (usa checked do QAction)
        action_panel.triggered.connect(_toggle_or_show_panel)

        # Se virou dock, ainda escuta o toggleViewAction dele para
        # manter o "checked" sincronizado (o usuário pode fechar o dock
        # pelo X do próprio dock, e o botão precisa refletir isso).
        try:
            dock = getattr(panel, "_dock", None)
            if dock is not None:
                def _sync_checked(visible: bool) -> None:
                    try:
                        action_panel.setChecked(bool(visible))
                    except Exception:
                        pass
                dock.visibilityChanged.connect(_sync_checked)
        except Exception:
            pass

        _toggle_button_ref["current"] = action_panel
        toolbar.addAction(action_panel)

    toolbar.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
    return toolbar


# =========================================================================
# SETUP
# =========================================================================

_TOOLBAR_CREATED = False
_REVERIFY_DONE = False


def _find_main_window(app):
    for attr in ("main_window", "window", "mw"):
        try:
            cand = getattr(app, attr, None)
            if cand is not None and hasattr(cand, "addToolBar"):
                return cand
        except Exception:
            pass
    try:
        qapp = QApplication.instance()
        if qapp is not None:
            for w in qapp.topLevelWidgets():
                if isinstance(w, QMainWindow) and w.isVisible():
                    return w
            for w in qapp.topLevelWidgets():
                if hasattr(w, "addToolBar") and w.isVisible():
                    return w
            for w in qapp.topLevelWidgets():
                if isinstance(w, QMainWindow):
                    return w
    except Exception:
        pass
    if app is not None and hasattr(app, "addToolBar"):
        return app
    return None


def _add_toolbar(mw, app):
    global _TOOLBAR_CREATED
    if _TOOLBAR_CREATED:
        return None
    try:
        existing = mw.findChild(QToolBar, "igz_tb_calculator")
        if existing is not None:
            try:
                mw.removeToolBar(existing)
                existing.deleteLater()
            except Exception:
                pass

        tb = create_toolbar(mw, app=app)
        mw.addToolBar(Qt.TopToolBarArea, tb)
        tb.show()
        _TOOLBAR_CREATED = True
        _log(
            f"toolbar adicionada em {type(mw).__name__}; "
            f"visible={tb.isVisible()}, lang={_lang_key()}"
        )
        return tb
    except Exception:
        _log("_add_toolbar falhou:\n" + traceback.format_exc())
        return None


def _ensure_toolbar(mw, app):
    global _REVERIFY_DONE, _TOOLBAR_CREATED
    if _REVERIFY_DONE:
        return
    _REVERIFY_DONE = True
    try:
        actual_mw = _find_main_window(app) or mw
        tb = actual_mw.findChild(QToolBar, "igz_tb_calculator")
        if tb is None:
            _TOOLBAR_CREATED = False
            _add_toolbar(actual_mw, app)
        elif not tb.isVisible():
            tb.show()
    except Exception:
        _log("_ensure_toolbar falhou:\n" + traceback.format_exc())


def _try_setup(app, attempts: int = 12):
    global _TOOLBAR_CREATED
    if _TOOLBAR_CREATED:
        return
    mw = _find_main_window(app)
    if mw is None:
        if attempts > 0:
            QTimer.singleShot(200, lambda: _try_setup(app, attempts - 1))
        else:
            _log("setup: main window não encontrada após retries.")
        return
    _add_toolbar(mw, app)
    QTimer.singleShot(1500, lambda: _ensure_toolbar(mw, app))


def setup(*args, **kwargs) -> None:
    global _TOOLBAR_CREATED, _REVERIFY_DONE
    _REVERIFY_DONE = False
    app = None
    for a in args:
        if a is None:
            continue
        if (hasattr(a, "main_window") or hasattr(a, "window")
                or hasattr(a, "addToolBar")):
            app = a
            break
    if app is None:
        app = (kwargs.get("app") or kwargs.get("main_window")
               or kwargs.get("window"))
    if app is None and args:
        app = args[0]

    if _TOOLBAR_CREATED:
        return
    QTimer.singleShot(0, lambda: _try_setup(app, attempts=12))


def register(*args, **kwargs):
    return setup(*args, **kwargs)


def init(*args, **kwargs):
    return setup(*args, **kwargs)


def load(*args, **kwargs):
    return setup(*args, **kwargs)


def on_load(*args, **kwargs):
    return setup(*args, **kwargs)


__all__ = [
    "CalculatorDialog",
    "CalculatorPanel",
    "create_toolbar",
    "run",
    "setup",
    "register",
    "init",
    "load",
    "on_load",
]


# =========================================================================
# STANDALONE
# =========================================================================

if __name__ == "__main__":
    app = QApplication(sys.argv)
    dlg = CalculatorDialog()
    dlg.show()
    sys.exit(app.exec())