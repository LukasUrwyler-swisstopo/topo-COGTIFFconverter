"""
01_GUI_cogtiff_4band_to_3band.py  –  COGTIFF Band-Konverter GUI
Tkinter-Oberflaeche fuer den flexiblen Band-Konverter (RGBN → RGB / NRG usw.).
Styling analog zu 0_main_GDWH_import_GUI.py.

Das GUI laeuft mit Standard-Python (kein osgeo erforderlich).
GDAL-Operationen werden via _osgeo_runner.py als Subprocess ausgefuehrt.
"""

import ctypes
import datetime
import time
import glob as _glob
import importlib.util
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import traceback
import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext
from pathlib import Path
from typing import List, Tuple, Dict

# ─── Pfade ────────────────────────────────────────────────────────────────────
SCRIPT_DIR    = os.path.dirname(os.path.abspath(__file__))
RUNNER_SCRIPT = os.path.join(SCRIPT_DIR, "_osgeo_runner.py")
CONFIG_FILE   = os.path.join(SCRIPT_DIR, "_cogtiff_config.json")

# ─── OSGeo4W Python Erkennung ─────────────────────────────────────────────────
def _detect_osgeo_python() -> str:
    """Gibt den Pfad zum OSGeo4W Python zurueck (aus Config, System-Python oder bekannten Pfaden)."""
    # 1. Gespeicherte Konfiguration
    if os.path.isfile(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, encoding="utf-8") as f:
                path = json.load(f).get("osgeo_python", "")
            if path and os.path.isfile(path):
                return path
        except Exception:
            pass

    # 2. osgeo im aktuellen Python verfuegbar → kein Subprocess noetig
    try:
        if importlib.util.find_spec("osgeo") is not None:
            return sys.executable
    except Exception:
        pass

    # 3. Bekannte Installationspfade
    kandidaten: List[str] = []
    osgeo_root = os.environ.get("OSGEO4W_ROOT")
    if osgeo_root:
        kandidaten.append(str(Path(osgeo_root) / "bin" / "python3.exe"))
    kandidaten += [
        r"C:\OSGeo4W\bin\python3.exe",
        r"C:\OSGeo4W64\bin\python3.exe",
    ]
    for pat in [
        r"C:\Program Files\QGIS*\bin\python3.exe",
        r"C:\Program Files (x86)\QGIS*\bin\python3.exe",
    ]:
        kandidaten.extend(sorted(_glob.glob(pat), reverse=True))

    return next((p for p in kandidaten if Path(p).is_file()), "")


def _detect_python_home(python_exe: str) -> str:
    """Leitet PYTHONHOME vom Python-Executable ab (QGIS: apps\\PythonXXX, OSGeo4W: root)."""
    bin_dir  = os.path.dirname(python_exe)
    root_dir = os.path.dirname(bin_dir)
    apps_dir = os.path.join(root_dir, "apps")
    if os.path.isdir(apps_dir):
        for name in sorted(os.listdir(apps_dir), reverse=True):
            if name.lower().startswith("python"):
                candidate = os.path.join(apps_dir, name)
                if os.path.isdir(candidate):
                    return candidate
    return root_dir


def _save_osgeo_config(path: str) -> None:
    try:
        cfg: Dict = {}
        if os.path.isfile(CONFIG_FILE):
            with open(CONFIG_FILE, encoding="utf-8") as f:
                cfg = json.load(f)
        cfg["osgeo_python"] = path
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


# ─── Farbpaletten (identisch zu GDWH GUI) ─────────────────────────────────────
LIGHT = {
    "root":      "#f0f0f0",
    "panel":     "#f5f5f5",
    "input":     "#ffffff",
    "fg":        "#1a1a1a",
    "fg_dim":    "#666666",
    "accent":    "#0063b1",
    "hdr_bg":    "#1a3a5c",
    "hdr_fg":    "#ffffff",
    "btn":       "#e1e1e1",
    "btn_hover": "#c8c8c8",
    "list":      "#ffffff",
    "log_bg":    "#1e1e1e",
    "log_fg":    "#d4d4d4",
    "sep":       "#c0c0c0",
    "sel_bg":    "#0078d4",
    "sel_fg":    "#ffffff",
    "ok":        "#2e7d32",
    "err":       "#c62828",
    "hint":      "#8a6f2e",
}

DARK = {
    "root":      "#1e1e1e",
    "panel":     "#252526",
    "input":     "#3c3c3c",
    "fg":        "#cccccc",
    "fg_dim":    "#7a7a7a",
    "accent":    "#4fc3f7",
    "hdr_bg":    "#1a1a1a",
    "hdr_fg":    "#cccccc",
    "btn":       "#3c3c3c",
    "btn_hover": "#505050",
    "list":      "#2d2d30",
    "log_bg":    "#1e1e1e",
    "log_fg":    "#d4d4d4",
    "sep":       "#3c3c3c",
    "sel_bg":    "#094771",
    "sel_fg":    "#cccccc",
    "ok":        "#66bb6a",
    "err":       "#ef5350",
    "hint":      "#c9a84c",
}

# ─── Schnellauswahl-Presets ────────────────────────────────────────────────────
PRESETS = [
    ("RGBN → RGB",  ["R", "G", "B", "N"], [1, 2, 3]),
    ("RGBN → NRG",  ["R", "G", "B", "N"], [4, 1, 2]),
    ("NRGB → RGB",  ["N", "R", "G", "B"], [2, 3, 4]),
    ("NRGB → NRG",  ["N", "R", "G", "B"], [1, 2, 3]),
]

# ─── Log-Queue Writer ──────────────────────────────────────────────────────────
class _QueueWriter:
    def __init__(self, q: queue.Queue):
        self.q = q

    def write(self, text):
        if text:
            self.q.put(text)

    def flush(self):
        pass


# ─── Haupt-App ─────────────────────────────────────────────────────────────────
class BandKonverterApp(tk.Tk):

    def __init__(self):
        super().__init__()
        self.title("COGTIFF Band-Konverter")
        screen_h = self.winfo_screenheight()
        win_h    = min(880, screen_h - 80)
        self.geometry(f"820x{win_h}")
        self.minsize(680, min(760, win_h))
        self.resizable(True, True)

        self._dark    = False
        self._running = False
        self._log_q   = queue.Queue()

        self._dim_labels    = []
        self._accent_labels = []

        self._osgeo_python = _detect_osgeo_python()
        self._osgeo_lbl    = None
        self._osgeo_status = None

        self._build_ui()
        self._apply_theme(True)   # Dark Mode als Standard
        self.after(100, self._poll_log)
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    # ── UI Aufbau ──────────────────────────────────────────────────────────────
    def _build_ui(self):
        # Header
        self._hdr = tk.Frame(self, height=52)
        self._hdr.pack(fill="x")
        self._hdr.pack_propagate(False)
        self._hdr_lbl = tk.Label(self._hdr, text="COGTIFF Band-Konverter",
                                  font=("Segoe UI", 15, "bold"))
        self._hdr_lbl.pack(side="left", padx=16, pady=12)
        self._theme_btn = tk.Button(self._hdr, text="Dark",
                                     command=self._toggle_theme,
                                     relief="flat", borderwidth=0,
                                     font=("", 9), cursor="hand2",
                                     padx=10, pady=4)
        self._theme_btn.pack(side="right", padx=12)

        # OSGeo4W Python Zeile
        self._osgeo_frame = ttk.Frame(self)
        self._osgeo_frame.pack(fill="x", padx=12, pady=(6, 0))
        osgeo_lbl_static = ttk.Label(self._osgeo_frame, text="OSGeo4W Python:",
                                      font=("Segoe UI", 9))
        osgeo_lbl_static.pack(side="left")
        self._dim_labels.append(osgeo_lbl_static)
        self._osgeo_lbl = ttk.Label(self._osgeo_frame, font=("Courier New", 8),
                                     text=self._osgeo_python or "(nicht gefunden)")
        self._osgeo_lbl.pack(side="left", padx=(6, 0))
        self._osgeo_status = ttk.Label(self._osgeo_frame, font=("Segoe UI", 8, "bold"))
        self._osgeo_status.pack(side="left", padx=(6, 0))
        ttk.Button(self._osgeo_frame, text="Aendern…",
                    command=self._set_osgeo_python).pack(side="right")

        # Scrollbarer Formular-Bereich
        outer = ttk.Frame(self)
        outer.pack(fill="both", expand=True, padx=12, pady=6)
        self._canvas = tk.Canvas(outer, highlightthickness=0)
        vsb = ttk.Scrollbar(outer, orient="vertical", command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)
        self._sf  = ttk.Frame(self._canvas)
        win_id    = self._canvas.create_window((0, 0), window=self._sf, anchor="nw")
        self._sf.bind("<Configure>",
                      lambda e: self._canvas.configure(scrollregion=self._canvas.bbox("all")))
        self._canvas.bind("<Configure>",
                          lambda e: self._canvas.itemconfig(win_id, width=e.width))
        self._canvas.bind_all("<MouseWheel>",
                              lambda e: self._canvas.yview_scroll(-1*(e.delta//120), "units"))
        self.bind_class("TCombobox", "<MouseWheel>", self._fwd_wheel)

        self._build_dateien(self._sf)
        self._build_dateiinfo(self._sf)
        self._build_bandconfig(self._sf)
        self._build_cog_optionen(self._sf)

        # Log
        ttk.Separator(self).pack(fill="x", padx=12, pady=4)
        log_frame = ttk.LabelFrame(self, text="Log-Ausgabe", padding=4,
                                    style="Section.TLabelframe")
        log_frame.pack(fill="x", padx=12, pady=(0, 4))
        self._log_box = scrolledtext.ScrolledText(
            log_frame, height=10, wrap="word", state="disabled",
            font=("Courier New", 9))
        self._log_box.pack(fill="both", expand=True)

        # Fortschrittsbalken (versteckt bis Import laeuft)
        self._progress_frame = ttk.Frame(self)
        self._progress_bar   = ttk.Progressbar(self._progress_frame, mode="indeterminate")
        self._progress_bar.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self._progress_lbl = ttk.Label(self._progress_frame,
                                        text="Konvertierung laeuft…", font=("", 9))
        self._progress_lbl.pack(side="left")

        # Buttons
        self._btn_row = ttk.Frame(self)
        self._btn_row.pack(fill="x", padx=12, pady=(0, 10))
        self._start_btn = ttk.Button(self._btn_row, text="▶   KONVERTIEREN",
                                      command=self._start)
        self._start_btn.pack(side="right", ipadx=22, ipady=7)
        ttk.Button(self._btn_row, text="Log loeschen",
                    command=self._clear_log).pack(side="right", padx=(0, 10))

    def _build_dateien(self, parent):
        sec = ttk.LabelFrame(parent, text="Dateien", padding=10,
                              style="Section.TLabelframe")
        sec.pack(fill="x", pady=(0, 6))
        sec.columnconfigure(1, weight=1)

        # Input
        lbl = ttk.Label(sec, text="Input-Datei (4-Band):", font=("Segoe UI", 9, "bold"))
        lbl.grid(row=0, column=0, sticky="w", pady=3)
        self._in_var = tk.StringVar()
        ttk.Entry(sec, textvariable=self._in_var
                   ).grid(row=0, column=1, sticky="ew", padx=(8, 4), pady=3)
        ttk.Button(sec, text="Datei…",
                    command=self._browse_input
                    ).grid(row=0, column=2, pady=3)

        in_hint = ttk.Label(sec, text="COG-TIFF  (.tif / .tiff)",
                             font=("", 8))
        in_hint.grid(row=1, column=1, sticky="w", padx=(8, 0))
        self._dim_labels.append(in_hint)

        # Output
        lbl2 = ttk.Label(sec, text="Output-Datei (3-Band):", font=("Segoe UI", 9, "bold"))
        lbl2.grid(row=2, column=0, sticky="w", pady=(8, 3))
        self._out_var = tk.StringVar()
        ttk.Entry(sec, textvariable=self._out_var
                   ).grid(row=2, column=1, sticky="ew", padx=(8, 4), pady=(8, 3))
        ttk.Button(sec, text="Speichern…",
                    command=self._browse_output
                    ).grid(row=2, column=2, pady=(8, 3))

        out_hint = ttk.Label(sec, text="Wird als Cloud-Optimized GeoTIFF (COG) geschrieben",
                              font=("", 8))
        out_hint.grid(row=3, column=1, sticky="w", padx=(8, 0))
        self._dim_labels.append(out_hint)

    def _build_dateiinfo(self, parent):
        sec = ttk.LabelFrame(parent, text="Datei-Info  (aus Quelldatei gelesen)",
                              padding=10, style="Section.TLabelframe")
        sec.pack(fill="x", pady=(0, 6))
        sec.columnconfigure(1, weight=1)

        fields = [
            ("Baender:",           "_info_bands"),
            ("ColorInterp:",      "_info_colorinterp"),
            ("Aufloesung:",        "_info_res"),
            ("Datentyp:",         "_info_dtype"),
            ("Koordinatensys.:",  "_info_crs"),
            ("Dateigroesse:",      "_info_size"),
        ]
        for row, (label, attr) in enumerate(fields):
            lbl = ttk.Label(sec, text=label, font=("Segoe UI", 9, "bold"))
            lbl.grid(row=row, column=0, sticky="w", pady=1)
            val = ttk.Label(sec, text="–", font=("Segoe UI", 9))
            val.grid(row=row, column=1, sticky="w", padx=(8, 0), pady=1)
            setattr(self, attr, val)
            self._accent_labels.append(val)

        # Alpha-Warnung (anfangs versteckt)
        self._warn_alpha = ttk.Label(
            sec,
            text="⚠  NoData-Wert '0 0 0' oder '255 255 255'; pruefen"
                 "  NoData '0 0 0' wird automatisch gesetzt. Allenfalls unter COG-Optionen anpassen.",
            font=("Segoe UI", 8, "italic"), wraplength=560, justify="left",
        )
        self._warn_alpha.grid(row=len(fields), column=0, columnspan=2,
                               sticky="w", padx=(0, 0), pady=(4, 0))
        self._warn_alpha.grid_remove()
        self._hint_labels = []
        self._hint_labels.append(self._warn_alpha)

        refresh_btn = ttk.Button(sec, text="Datei-Info aktualisieren",
                                  command=self._refresh_info)
        refresh_btn.grid(row=len(fields) + 1, column=0, columnspan=2,
                          sticky="w", pady=(8, 0))

    def _build_bandconfig(self, parent):
        sec = ttk.LabelFrame(parent, text="Band-Konfiguration", padding=10,
                              style="Section.TLabelframe")
        sec.pack(fill="x", pady=(0, 6))
        sec.columnconfigure(1, weight=1)

        # Schnellauswahl-Buttons
        preset_lbl = ttk.Label(sec, text="Schnellauswahl:", font=("Segoe UI", 9, "bold"))
        preset_lbl.grid(row=0, column=0, sticky="w", pady=(0, 6))
        btn_frame = ttk.Frame(sec)
        btn_frame.grid(row=0, column=1, sticky="w", padx=(8, 0), pady=(0, 6))
        for name, labels, bands in PRESETS:
            ttk.Button(btn_frame, text=name,
                        command=lambda lb=labels, bd=bands: self._apply_preset(lb, bd)
                        ).pack(side="left", padx=(0, 6))

        # Input-Bandbeschriftungen
        lbl1 = ttk.Label(sec, text="Input-Bandbeschriftungen:", font=("Segoe UI", 9, "bold"))
        lbl1.grid(row=1, column=0, sticky="w", pady=3)
        self._labels_var = tk.StringVar(value="R, G, B, N")
        ttk.Entry(sec, textvariable=self._labels_var, width=30
                   ).grid(row=1, column=1, sticky="w", padx=(8, 0), pady=3)
        h1 = ttk.Label(sec, text="Kommagetrennte Bezeichnungen der Quellbaender  (z.B.  R, G, B, N  oder  N, R, G, B)",
                        font=("", 8))
        h1.grid(row=2, column=1, sticky="w", padx=(8, 0))
        self._dim_labels.append(h1)

        # Ausgabebaender
        lbl2 = ttk.Label(sec, text="Ausgabebaender (Quellindizes):", font=("Segoe UI", 9, "bold"))
        lbl2.grid(row=3, column=0, sticky="w", pady=(8, 3))
        self._bands_var = tk.StringVar(value="1, 2, 3")
        entry = ttk.Entry(sec, textvariable=self._bands_var, width=20)
        entry.grid(row=3, column=1, sticky="w", padx=(8, 0), pady=(8, 3))
        entry.bind("<KeyRelease>", lambda _: self._update_preview())
        h2 = ttk.Label(sec,
            text="1-basierte Quellband-Indizes, kommagetrennt  (z.B.  1, 2, 3  oder  4, 1, 2)",
            font=("", 8))
        h2.grid(row=4, column=1, sticky="w", padx=(8, 0))
        self._dim_labels.append(h2)

        # Vorschau
        lbl3 = ttk.Label(sec, text="Band-Mapping Vorschau:", font=("Segoe UI", 9, "bold"))
        lbl3.grid(row=5, column=0, sticky="nw", pady=(10, 3))
        self._preview_lbl = ttk.Label(sec, text="–", font=("Courier New", 9),
                                       justify="left", wraplength=500)
        self._preview_lbl.grid(row=5, column=1, sticky="w", padx=(8, 0), pady=(10, 3))
        self._accent_labels.append(self._preview_lbl)

        self._labels_var.trace_add("write", lambda *_: self._update_preview())
        self._bands_var.trace_add("write",  lambda *_: self._update_preview())
        self._update_preview()

    def _build_cog_optionen(self, parent):
        sec = ttk.LabelFrame(parent, text="COG-Optionen", padding=10,
                              style="Section.TLabelframe")
        sec.pack(fill="x", pady=(0, 6))
        sec.columnconfigure(1, weight=0)
        sec.columnconfigure(3, weight=0)

        def _row(r, c, label, widget_cb):
            lbl = ttk.Label(sec, text=label, font=("Segoe UI", 9, "bold"))
            lbl.grid(row=r, column=c*2, sticky="w", pady=3, padx=(0 if c == 0 else 20, 0))
            w = widget_cb()
            w.grid(row=r, column=c*2+1, sticky="w", padx=(6, 0), pady=3)
            return w

        self._compress_var = tk.StringVar(value="DEFLATE")
        _row(0, 0, "Kompression:", lambda: ttk.Combobox(
            sec, textvariable=self._compress_var,
            values=["DEFLATE", "LZW", "ZSTD", "NONE"], state="readonly", width=10))

        self._blocksize_var = tk.StringVar(value="256")
        _row(0, 1, "Kachelgroesse:", lambda: ttk.Combobox(
            sec, textvariable=self._blocksize_var,
            values=["256", "512", "1024"], state="readonly", width=8))

        self._overviews_var = tk.StringVar(value="AUTO")
        _row(1, 0, "Overviews:", lambda: ttk.Combobox(
            sec, textvariable=self._overviews_var,
            values=["AUTO", "NONE"], state="readonly", width=10))

        self._resampling_var = tk.StringVar(value="LANCZOS")
        _row(1, 1, "Ov.-Resampling:", lambda: ttk.Combobox(
            sec, textvariable=self._resampling_var,
            values=["LANCZOS", "BILINEAR", "CUBIC", "AVERAGE", "NEAREST"],
            state="readonly", width=10))

        # NoData
        nd_lbl = ttk.Label(sec, text="NoData-Wert:", font=("Segoe UI", 9, "bold"))
        nd_lbl.grid(row=2, column=0, sticky="w", pady=(8, 3))
        nd_row = ttk.Frame(sec)
        nd_row.grid(row=2, column=1, columnspan=3, sticky="w", padx=(6, 0), pady=(8, 3))
        self._nodata_var = tk.StringVar(value="")
        ttk.Entry(nd_row, textvariable=self._nodata_var, width=12).pack(side="left")
        self._nodata_status_lbl = ttk.Label(nd_row, text="", font=("Segoe UI", 8, "italic"))
        self._nodata_status_lbl.pack(side="left", padx=(8, 0))
        nd_hint = ttk.Label(sec,
            text='Leer = kein NoData  |  wird beim Oeffnen der Quelldatei automatisch erkannt',
            font=("", 8))
        nd_hint.grid(row=3, column=0, columnspan=4, sticky="w")
        self._dim_labels.append(nd_hint)

        hint = ttk.Label(sec,
            text="DEFLATE + Predictor=2 = verlustfreie Kompression  |  ZSTD schneller bei aehnlicher Kompressionsrate",
            font=("", 8))
        hint.grid(row=4, column=0, columnspan=4, sticky="w", pady=(2, 0))
        self._dim_labels.append(hint)

    # ── Hilfsfunktionen ────────────────────────────────────────────────────────
    def _fwd_wheel(self, event):
        self._canvas.yview_scroll(-1*(event.delta//120), "units")
        return "break"

    def _apply_preset(self, labels: List, bands: List):
        self._labels_var.set(", ".join(labels))
        self._bands_var.set(", ".join(str(b) for b in bands))
        self._update_preview()

    def _update_preview(self):
        try:
            labels = [s.strip() for s in self._labels_var.get().split(",") if s.strip()]
            bands  = [int(s.strip()) for s in self._bands_var.get().split(",")
                      if s.strip().isdigit()]
            if not labels or not bands:
                self._preview_lbl.config(text="–")
                return
            parts = []
            for i, b in enumerate(bands, 1):
                src_name = labels[b-1] if 0 < b <= len(labels) else f"Band{b}"
                parts.append(f"Out{i} ← Quelle Band {b}  ({src_name})")
            self._preview_lbl.config(text="\n".join(parts))
        except Exception:
            self._preview_lbl.config(text="–")

    def _browse_input(self):
        path = filedialog.askopenfilename(
            title="Input-TIFF auswaehlen",
            filetypes=[("GeoTIFF", "*.tif *.tiff"), ("Alle Dateien", "*.*")],
        )
        if path:
            path = path.replace("/", "\\")
            self._in_var.set(path)
            p = Path(path)
            self._out_var.set(str(p.parent / (p.stem + "_RGB" + p.suffix)))
            self._refresh_info()

    def _browse_output(self):
        init = self._out_var.get() or self._in_var.get()
        p    = Path(init) if init else Path.home()
        path = filedialog.asksaveasfilename(
            title="Output-TIFF speichern unter",
            initialdir=str(p.parent),
            initialfile=p.name,
            defaultextension=".tif",
            filetypes=[("GeoTIFF", "*.tif *.tiff"), ("Alle Dateien", "*.*")],
        )
        if path:
            self._out_var.set(path.replace("/", "\\"))

    # ── OSGeo4W Python Verwaltung ──────────────────────────────────────────────
    def _update_osgeo_label(self):
        T = DARK if self._dark else LIGHT
        if self._osgeo_python and os.path.isfile(self._osgeo_python):
            self._osgeo_lbl.config(text=self._osgeo_python)
            self._osgeo_status.config(text="✓", foreground=T["ok"])
        else:
            self._osgeo_lbl.config(text=self._osgeo_python or "(nicht gefunden)")
            self._osgeo_status.config(text="✗ nicht gefunden", foreground=T["err"])

    def _set_osgeo_python(self):
        init_dir = os.path.dirname(self._osgeo_python) if self._osgeo_python else r"C:\OSGeo4W\bin"
        if not os.path.isdir(init_dir):
            init_dir = "C:\\"
        path = filedialog.askopenfilename(
            title="OSGeo4W Python auswaehlen",
            initialdir=init_dir,
            filetypes=[("Python", "python*.exe"), ("Executable", "*.exe"), ("Alle", "*.*")],
        )
        if path:
            path = path.replace("/", "\\")
            self._osgeo_python = path
            _save_osgeo_config(path)
            self._update_osgeo_label()

    # ── Datei-Info via Runner ──────────────────────────────────────────────────
    def _refresh_info(self):
        src = self._in_var.get().strip()
        if not src or not os.path.isfile(src):
            for attr in ("_info_bands", "_info_colorinterp", "_info_res",
                         "_info_dtype", "_info_crs", "_info_size"):
                getattr(self, attr).config(text="–")
            self._warn_alpha.grid_remove()
            return

        if not self._osgeo_python or not os.path.isfile(self._osgeo_python):
            self._info_bands.config(text="OSGeo4W Python nicht gefunden – bitte Pfad setzen")
            return

        def ui_error(msg):
            try:
                from tkinter import messagebox
                messagebox.showerror("Datei-Info Fehler", msg, parent=self)
            except Exception:
                pass
            for attr in ("_info_bands", "_info_colorinterp", "_info_res",
                         "_info_dtype", "_info_crs", "_info_size"):
                try:
                    getattr(self, attr).config(text="–")
                except Exception:
                    pass
            try:
                self._warn_alpha.grid_remove()
            except Exception:
                pass

        def ui_info(info):
            try:
                bc = info.get("bands")
                ci = info.get("colorinterp", [])
                ci_parts = ["B{}:{}".format(i+1, c) for i, c in enumerate(ci)]
                alpha_bands = info.get("alpha_bands", [])
                nd_raw = info.get("nodata")

                self._info_bands.config(text=str(bc))
                if bc != 4:
                    try:
                        from tkinter import messagebox
                        messagebox.showerror("Input-Fehler: falsche Bandanzahl",
                                             "Input-Datei enthaelt {} Band(ae) — erwartet werden 4 Baender.".format(bc),
                                             parent=self)
                    except Exception:
                        pass
                    try:
                        T = DARK if self._dark else LIGHT
                        self._info_bands.config(foreground=T["err"])
                    except Exception:
                        pass
                    return

                self._info_colorinterp.config(text="  ".join(ci_parts))
                self._info_res.config(text="{} × {} px".format(info.get('width'), info.get('height')))
                self._info_dtype.config(text=info.get("dtype", "–"))
                self._info_crs.config(text=info.get("crs", "–"))
                try:
                    self._info_size.config(text="{:.1f} MB".format(info.get('size_mb', 0.0)))
                except Exception:
                    pass

                T = DARK if self._dark else LIGHT
                if nd_raw is not None:
                    try:
                        nd_val = float(nd_raw)
                        nd_str = str(int(nd_val)) if nd_val == int(nd_val) else str(nd_val)
                        self._nodata_var.set(nd_str)
                        self._nodata_status_lbl.config(text="✔ aus Quelldatei erkannt ({})".format(nd_str), foreground=T["ok"])
                    except Exception:
                        pass
                elif alpha_bands:
                    try:
                        self._nodata_var.set("0")
                        self._nodata_status_lbl.config(text="⚠ Background Pixel → 0 (default 0 0 0): Pruefen welche Background-Pixel das Input-COG enthaelt", foreground=T["hint"])
                    except Exception:
                        pass
                else:
                    try:
                        self._nodata_status_lbl.config(text="nicht in Datei gesetzt – bitte manuell pruefen", foreground=T["fg_dim"])
                    except Exception:
                        pass

                if alpha_bands:
                    try:
                        self._warn_alpha.grid()
                    except Exception:
                        pass
                else:
                    try:
                        self._warn_alpha.grid_remove()
                    except Exception:
                        pass
            except Exception:
                ui_error("Fehler beim Darstellen der Datei-Info")

        def worker():
            tmp_name = None
            try:
                cfg = {"action": "info", "input_path": src}
                with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as tmp:
                    json.dump(cfg, tmp, ensure_ascii=False)
                    tmp_name = tmp.name
                env = os.environ.copy()
                env["PYTHONHOME"] = _detect_python_home(self._osgeo_python)
                result = subprocess.run([self._osgeo_python, RUNNER_SCRIPT, tmp_name], stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, env=env)
                try:
                    if tmp_name and os.path.exists(tmp_name):
                        os.unlink(tmp_name)
                except Exception:
                    pass
                if result.returncode != 0:
                    err = (result.stdout or "") + "\n" + (result.stderr or "")
                    self.after(0, ui_error, err.strip())
                    return
                info = json.loads(result.stdout.strip() or "{}")
                self.after(0, ui_info, info)
            except Exception as e:
                try:
                    if tmp_name and os.path.exists(tmp_name):
                        os.unlink(tmp_name)
                except Exception:
                    pass
                self.after(0, ui_error, str(e))

        threading.Thread(target=worker, daemon=True).start()

    # ── Theme ──────────────────────────────────────────────────────────────────
    def _toggle_theme(self):
        self._apply_theme(not self._dark)

    def _apply_theme(self, dark: bool):
        self._dark = dark
        T = DARK if dark else LIGHT
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure(".",
            background=T["panel"], foreground=T["fg"],
            fieldbackground=T["input"],
            selectbackground=T["sel_bg"], selectforeground=T["sel_fg"],
            bordercolor=T["sep"], lightcolor=T["panel"], darkcolor=T["sep"],
            insertcolor=T["fg"], troughcolor=T["root"],
        )
        s.configure("TFrame",      background=T["panel"])
        s.configure("TLabelframe", background=T["panel"], bordercolor=T["sep"])
        s.configure("TLabelframe.Label",
                    background=T["panel"], foreground=T["fg"],
                    font=("Segoe UI", 9, "bold"))
        s.configure("Section.TLabelframe",
                    background=T["panel"], bordercolor=T["sep"])
        s.configure("Section.TLabelframe.Label",
                    background=T["panel"], foreground=T["accent"],
                    font=("Segoe UI", 10, "bold"))
        s.configure("TLabel",  background=T["panel"], foreground=T["fg"])
        s.configure("TButton",
            background=T["btn"], foreground=T["fg"],
            bordercolor=T["sep"], relief="flat",
            padding=(8, 4), focuscolor=T["panel"])
        s.map("TButton",
            background=[("active", T["btn_hover"]), ("pressed", T["sep"])],
            foreground=[("active", T["fg"])],
            relief=[("pressed", "flat")])
        s.configure("TCombobox",
            fieldbackground=T["input"], background=T["btn"],
            foreground=T["fg"], arrowcolor=T["fg"],
            selectbackground=T["sel_bg"], selectforeground=T["sel_fg"],
            bordercolor=T["sep"], insertcolor=T["fg"])
        s.map("TCombobox",
            fieldbackground=[("readonly", T["input"]), ("disabled", T["panel"])],
            selectbackground=[("readonly", T["input"])],
            selectforeground=[("readonly", T["fg"])],
            foreground=[("readonly", T["fg"]), ("disabled", T["fg_dim"])],
            background=[("active", T["btn_hover"])])
        s.configure("TEntry",
            fieldbackground=T["input"], foreground=T["fg"],
            bordercolor=T["sep"], insertcolor=T["fg"],
            selectbackground=T["sel_bg"], selectforeground=T["sel_fg"])
        s.configure("Vertical.TScrollbar",
            background=T["btn"], troughcolor=T["root"],
            bordercolor=T["sep"], arrowcolor=T["fg"])
        s.configure("TSeparator",  background=T["sep"])
        s.configure("TProgressbar",
            background=T["accent"], troughcolor=T["root"],
            bordercolor=T["sep"])

        self.option_add("*TCombobox*Listbox.background",       T["list"])
        self.option_add("*TCombobox*Listbox.foreground",       T["fg"])
        self.option_add("*TCombobox*Listbox.selectBackground", T["sel_bg"])
        self.option_add("*TCombobox*Listbox.selectForeground", T["sel_fg"])

        self.configure(bg=T["root"])
        self._canvas.configure(bg=T["panel"], highlightbackground=T["sep"])

        self._hdr.configure(bg=T["hdr_bg"])
        self._hdr_lbl.configure(bg=T["hdr_bg"], fg=T["hdr_fg"])
        self._theme_btn.configure(
            bg=T["hdr_bg"], fg=T["hdr_fg"],
            activebackground=T["btn"], activeforeground=T["fg"],
            text="Hell" if dark else "Dark")

        self._log_box.configure(bg=T["log_bg"], fg=T["log_fg"],
                                 insertbackground=T["log_fg"])

        for lbl in self._dim_labels:
            try: lbl.configure(foreground=T["fg_dim"])
            except tk.TclError: pass
        for lbl in self._accent_labels:
            try: lbl.configure(foreground=T["accent"])
            except tk.TclError: pass
        for lbl in self._hint_labels:
            try: lbl.configure(foreground=T["hint"])
            except tk.TclError: pass

        if self._osgeo_lbl is not None:
            self._update_osgeo_label()

        self._set_titlebar_dark(dark)

    def _set_titlebar_dark(self, dark: bool):
        if not self.winfo_ismapped():
            self.after(50, lambda: self._set_titlebar_dark(dark))
            return
        try:
            hwnd  = int(self.wm_frame(), 16)
            value = ctypes.c_int(1 if dark else 0)
            for attr in (20, 19):
                if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                        hwnd, attr, ctypes.byref(value), ctypes.sizeof(value)) == 0:
                    break
            ctypes.windll.user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0027)
        except Exception:
            pass

    # ── Log ───────────────────────────────────────────────────────────────────
    def _log(self, text: str):
        self._log_box.config(state="normal")
        self._log_box.insert("end", text)
        self._log_box.see("end")
        self._log_box.config(state="disabled")

    def _clear_log(self):
        self._log_box.config(state="normal")
        self._log_box.delete("1.0", "end")
        self._log_box.config(state="disabled")

    def _poll_log(self):
        try:
            while True:
                msg = self._log_q.get_nowait()
                self._log(msg)
        except queue.Empty:
            pass
        self.after(100, self._poll_log)

    def _on_done(self, success: bool):
        self._running = False
        self._start_btn.config(state="normal")
        self._progress_bar.stop()
        self._progress_frame.pack_forget()
        if success:
            self._log("\n✔  Konvertierung erfolgreich abgeschlossen.\n")
        else:
            self._log("\n✘  Konvertierung fehlgeschlagen.\n")

    def _update_progress(self, fraction: float):
        """Update progressbar and ETA label. fraction in [0.0 .. 1.0]."""
        try:
            if not hasattr(self, "_progress_start_time"):
                self._progress_start_time = time.time()
                self._progress_last_val = 0.0
                # switch to determinate mode
                try:
                    self._progress_bar.stop()
                    self._progress_bar.config(mode="determinate", maximum=100)
                except Exception:
                    pass
            pct = max(0.0, min(1.0, fraction))
            try:
                self._progress_bar['value'] = pct * 100.0
            except Exception:
                pass
            now = time.time()
            elapsed = now - getattr(self, "_progress_start_time", now)
            eta_str = "--:--"
            if pct > 0:
                remaining = elapsed * (1.0 - pct) / pct
                m = int(remaining // 60)
                s = int(remaining % 60)
                eta_str = f"{m:d}m {s:02d}s"
            try:
                self._progress_lbl.config(text=f"{pct*100:5.1f}% — verbleibend: {eta_str}")
            except Exception:
                pass
            self._progress_last_val = pct
        except Exception:
            pass

    # ── Validierung ───────────────────────────────────────────────────────────
    def _validate(self) -> Tuple[bool, str, List[int], List[str]]:
        errors = []
        inp = self._in_var.get().strip()
        out = self._out_var.get().strip()

        if not self._osgeo_python or not os.path.isfile(self._osgeo_python):
            errors.append(
                "OSGeo4W Python nicht gefunden.\n"
                "Bitte Pfad via 'Aendern…' festlegen  (z.B. C:\\OSGeo4W\\bin\\python3.exe)."
            )

        if not inp:
            errors.append("Input-Datei fehlt.")
        elif not os.path.isfile(inp):
            errors.append(f"Input-Datei nicht gefunden:\n  {inp}")

        if not out:
            errors.append("Output-Datei fehlt.")

        try:
            labels = [s.strip() for s in self._labels_var.get().split(",") if s.strip()]
        except Exception:
            labels = []
            errors.append("Input-Bandbeschriftungen ungueltig.")

        try:
            bands = [int(s.strip()) for s in self._bands_var.get().split(",")
                     if s.strip()]
            if not bands:
                raise ValueError
        except Exception:
            bands = []
            errors.append("Ausgabebaender ungueltig  (kommagetrennte Ganzzahlen erwartet, z.B.  1, 2, 3).")

        if errors:
            from tkinter import messagebox
            messagebox.showerror("Eingabe-Fehler",
                                  "\n\n".join(f"• {e}" for e in errors), parent=self)
            return False, inp, bands, labels
        return True, inp, bands, labels

    # ── Konvertierung starten ─────────────────────────────────────────────────
    def _start(self):
        if self._running:
            return
        ok, inp, bands, labels = self._validate()
        if not ok:
            return

        out      = self._out_var.get().strip()
        compress = self._compress_var.get()
        block    = self._blocksize_var.get()
        ovr      = self._overviews_var.get()
        resamp   = self._resampling_var.get()
        nodata   = self._nodata_var.get().strip()

        self._running = True
        self._start_btn.config(state="disabled")
        self._progress_frame.pack(fill="x", padx=12, pady=(0, 4), before=self._btn_row)
        self._progress_bar.start(10)
        self._clear_log()
        self._log("=== COGTIFF Band-Konvertierung gestartet ===\n\n")

        threading.Thread(
            target=self._run_thread,
            args=(inp, out, bands, labels, compress, block, ovr, resamp, nodata),
            daemon=True,
        ).start()

    def _run_thread(self, inp, out, bands, labels,
                    compress, block, ovr, resamp, nodata):
        try:
            self._exec_with_osgeo(inp, out, bands, labels,
                                   compress, block, ovr, resamp, nodata)
            self.after(0, self._on_done, True)
        except Exception as e:
            self._log_q.put(f"\n[FEHLER] {e}\n")
            self._log_q.put(traceback.format_exc())
            self.after(0, self._on_done, False)

    def _exec_with_osgeo(self, inp, out, bands, labels,
                          compress, block, ovr, resamp, nodata):
        """Startet _osgeo_runner.py als Subprocess mit OSGeo4W Python."""
        cfg = {
            "action":               "convert",
            "input_path":           inp,
            "output_path":          out,
            "output_bands":         bands,
            "input_band_labels":    labels,
            "compress":             compress,
            "blocksize":            block,
            "overviews":            ovr,
            "overview_resampling":  resamp,
            "nodata":               nodata,
        }

        # Log-Datei vorbereiten
        logs_dir  = Path(SCRIPT_DIR) / "logs"
        logs_dir.mkdir(exist_ok=True)
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
        log_path  = logs_dir / f"{Path(out).stem}_{timestamp}.log"

        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                         encoding="utf-8") as tmp:
            json.dump(cfg, tmp, ensure_ascii=False, indent=2)
            tmp_name = tmp.name
        try:
            env = os.environ.copy()
            env["PYTHONHOME"] = _detect_python_home(self._osgeo_python)
            # Ensure subprocess prints UTF-8 so Windows cp1252 won't raise on special chars
            env["PYTHONIOENCODING"] = "utf-8"
            header = f"[Subprocess] {self._osgeo_python}\n\n"
            self._log_q.put(header)
            proc = subprocess.Popen(
                [self._osgeo_python, RUNNER_SCRIPT, tmp_name],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                encoding="utf-8",
                errors="replace",
                env=env,
            )
            with open(log_path, "w", encoding="utf-8") as lf:
                lf.write(header)
                for line in proc.stdout:
                    stripped = line.strip()
                    if stripped.startswith("PROGRESS:"):
                        # runner emits PROGRESS:0.123456
                        try:
                            val = float(stripped.split(":", 1)[1])
                        except Exception:
                            val = None
                        if val is not None:
                            self.after(0, self._update_progress, float(val))
                        # still write log and show line
                        self._log_q.put(line)
                        lf.write(line)
                    else:
                        self._log_q.put(line)
                        lf.write(line)
            proc.wait()
            self._log_q.put(f"\nLog gespeichert: {log_path}\n")
            if proc.returncode != 0:
                raise RuntimeError(
                    f"OSGeo4W Subprocess beendet mit Exit-Code {proc.returncode}"
                )
        finally:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass


# ─── Entry Point ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = BandKonverterApp()
    app.mainloop()
