"""
GUI_cogtiff_4band_to_3band.py  –  COGTIFF Band-Konverter GUI
Tkinter-Oberfläche für den flexiblen Band-Konverter (RGBN → RGB / NRG usw.).
Styling analog zu 0_main_GDWH_import_GUI.py.

Anforderungen:
    Python + GDAL (osgeo4w): gdal >= 3.1 (COG-Driver)
"""

from __future__ import annotations

import ctypes
import logging
import os
import queue
import sys
import threading
import traceback
import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext
from pathlib import Path

from osgeo import gdal

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


class _QueueLoggingHandler(logging.Handler):
    def __init__(self, q: queue.Queue):
        super().__init__()
        self.q = q

    def emit(self, record):
        self.q.put(self.format(record) + "\n")


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

        # Fortschrittsbalken (versteckt bis Import läuft)
        self._progress_frame = ttk.Frame(self)
        self._progress_bar   = ttk.Progressbar(self._progress_frame, mode="indeterminate")
        self._progress_bar.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self._progress_lbl = ttk.Label(self._progress_frame,
                                        text="Konvertierung läuft…", font=("", 9))
        self._progress_lbl.pack(side="left")

        # Buttons
        self._btn_row = ttk.Frame(self)
        self._btn_row.pack(fill="x", padx=12, pady=(0, 10))
        self._start_btn = ttk.Button(self._btn_row, text="▶   KONVERTIEREN",
                                      command=self._start)
        self._start_btn.pack(side="right", ipadx=22, ipady=7)
        ttk.Button(self._btn_row, text="Log löschen",
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

        in_hint = ttk.Label(sec, text="COG-TIFF, GeoTIFF  (.tif / .tiff)",
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
            ("Bänder:",           "_info_bands"),
            ("ColorInterp:",      "_info_colorinterp"),
            ("Auflösung:",        "_info_res"),
            ("Datentyp:",         "_info_dtype"),
            ("Koordinatensys.:",  "_info_crs"),
            ("Dateigrösse:",      "_info_size"),
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
            text="⚠  Band 4 hat ColorInterp=Alpha → Transparenzmaske fällt beim Extrahieren weg."
                 "  NoData=0 wird automatisch gesetzt.",
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
        h1 = ttk.Label(sec, text="Kommagetrennte Bezeichnungen der Quellbänder  (z.B.  R, G, B, N  oder  N, R, G, B)",
                        font=("", 8))
        h1.grid(row=2, column=1, sticky="w", padx=(8, 0))
        self._dim_labels.append(h1)

        # Ausgabebänder
        lbl2 = ttk.Label(sec, text="Ausgabebänder (Quellindizes):", font=("Segoe UI", 9, "bold"))
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

        self._blocksize_var = tk.StringVar(value="512")
        _row(0, 1, "Kachelgrösse:", lambda: ttk.Combobox(
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
            text='Leer = kein NoData  |  wird beim Öffnen der Quelldatei automatisch erkannt',
            font=("", 8))
        nd_hint.grid(row=3, column=0, columnspan=4, sticky="w")
        self._dim_labels.append(nd_hint)

        hint = ttk.Label(sec,
            text="DEFLATE + Predictor=2 = verlustfreie Kompression  |  ZSTD schneller bei ähnlicher Kompressionsrate",
            font=("", 8))
        hint.grid(row=4, column=0, columnspan=4, sticky="w", pady=(2, 0))
        self._dim_labels.append(hint)

    # ── Hilfsfunktionen ────────────────────────────────────────────────────────
    def _fwd_wheel(self, event):
        self._canvas.yview_scroll(-1*(event.delta//120), "units")
        return "break"

    def _apply_preset(self, labels: list, bands: list):
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
            title="Input-TIFF auswählen",
            filetypes=[("GeoTIFF", "*.tif *.tiff"), ("Alle Dateien", "*.*")],
        )
        if path:
            path = path.replace("/", "\\")
            self._in_var.set(path)
            # Output-Pfad automatisch vorschlagen
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

    def _refresh_info(self):
        src = self._in_var.get().strip()
        if not src or not os.path.isfile(src):
            for attr in ("_info_bands", "_info_colorinterp", "_info_res",
                         "_info_dtype", "_info_crs", "_info_size"):
                getattr(self, attr).config(text="–")
            self._warn_alpha.grid_remove()
            return
        try:
            gdal.UseExceptions()
            ds = gdal.Open(src, gdal.GA_ReadOnly)
            if ds is None:
                raise RuntimeError("GDAL konnte die Datei nicht öffnen.")
            bc   = ds.RasterCount
            rx   = ds.RasterXSize
            ry   = ds.RasterYSize
            dt   = gdal.GetDataTypeName(ds.GetRasterBand(1).DataType)
            srs  = ds.GetSpatialRef()
            crs  = srs.GetName() if srs else "nicht gesetzt"
            size = os.path.getsize(src) / (1024**2)

            # ColorInterp je Band ermitteln + Alpha-Bänder identifizieren
            ci_parts    = []
            alpha_bands = []
            for i in range(1, bc + 1):
                band = ds.GetRasterBand(i)
                ci   = gdal.GetColorInterpretationName(band.GetColorInterpretation())
                ci_parts.append(f"B{i}:{ci}")
                if ci == "Alpha":
                    alpha_bands.append(i)

            # NoData aus Band 1 lesen – vor ds=None
            nd_raw = ds.GetRasterBand(1).GetNoDataValue()
            ds = None

            self._info_bands.config(text=str(bc))
            self._info_colorinterp.config(text="  ".join(ci_parts))
            self._info_res.config(text=f"{rx} × {ry} px")
            self._info_dtype.config(text=dt)
            self._info_crs.config(text=crs)
            self._info_size.config(text=f"{size:.1f} MB")

            # NoData auto-erkennung: nd_raw wurde oben vor ds=None gelesen
            T = DARK if self._dark else LIGHT
            nd_val = nd_raw

            if nd_val is not None:
                # Ganzzahligen Wert ohne Nachkommastellen anzeigen
                nd_str = str(int(nd_val)) if nd_val == int(nd_val) else str(nd_val)
                self._nodata_var.set(nd_str)
                self._nodata_status_lbl.config(
                    text=f"✔ aus Quelldatei erkannt ({nd_str})",
                    foreground=T["ok"])
            elif alpha_bands:
                self._nodata_var.set("0")
                self._nodata_status_lbl.config(
                    text="⚠ Alpha-Band erkannt → 0 empfohlen",
                    foreground=T["hint"])
            else:
                self._nodata_status_lbl.config(
                    text="nicht in Datei gesetzt – bitte manuell prüfen",
                    foreground=T["fg_dim"])

            # Alpha-Warnung anzeigen
            if alpha_bands:
                self._warn_alpha.grid()
            else:
                self._warn_alpha.grid_remove()

        except Exception as e:
            self._info_bands.config(text=f"Fehler: {e}")

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

    # ── Validierung ───────────────────────────────────────────────────────────
    def _validate(self) -> tuple[bool, str, list[int], list[str]]:
        errors = []
        inp = self._in_var.get().strip()
        out = self._out_var.get().strip()

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
            errors.append("Input-Bandbeschriftungen ungültig.")

        try:
            bands = [int(s.strip()) for s in self._bands_var.get().split(",")
                     if s.strip()]
            if not bands:
                raise ValueError
        except Exception:
            bands = []
            errors.append("Ausgabebänder ungültig  (kommagetrennte Ganzzahlen erwartet, z.B.  1, 2, 3).")

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
        # Logging auf Queue umleiten
        handler = _QueueLoggingHandler(self._log_q)
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        root_logger = logging.getLogger()
        root_logger.addHandler(handler)
        root_logger.setLevel(logging.INFO)

        try:
            _convert(
                input_path=inp,
                output_path=out,
                output_bands=bands,
                input_band_labels=labels,
                compress=compress,
                blocksize=block,
                overviews=ovr,
                overview_resampling=resamp,
                nodata=nodata,
                log_queue=self._log_q,
            )
            self.after(0, self._on_done, True)
        except Exception as e:
            self._log_q.put(f"\n[FEHLER] {e}\n")
            self._log_q.put(traceback.format_exc())
            self.after(0, self._on_done, False)
        finally:
            root_logger.removeHandler(handler)


# ─── Konvertierungsfunktion (standalone, GUI-unabhängig) ──────────────────────
def _convert(
    input_path: str,
    output_path: str,
    output_bands: list,
    input_band_labels: list,
    compress: str = "DEFLATE",
    blocksize: str = "512",
    overviews: str = "AUTO",
    overview_resampling: str = "LANCZOS",
    nodata: str = "",
    log_queue: queue.Queue | None = None,
) -> None:

    def _log(msg: str):
        if log_queue:
            log_queue.put(msg + "\n")

    gdal.UseExceptions()

    _log(f"Öffne Quelldatei: {input_path}")
    src_ds = gdal.Open(input_path, gdal.GA_ReadOnly)
    if src_ds is None:
        raise FileNotFoundError(f"GDAL konnte die Datei nicht öffnen: {input_path}")

    band_count = src_ds.RasterCount
    dtype      = src_ds.GetRasterBand(1).DataType
    srs        = src_ds.GetSpatialRef()

    _log(f"  Bänder gesamt : {band_count}")
    _log(f"  Auflösung     : {src_ds.RasterXSize} × {src_ds.RasterYSize} px")
    _log(f"  Datentyp      : {gdal.GetDataTypeName(dtype)}")
    _log(f"  Koordinatensys: {srs.GetName() if srs else 'nicht gesetzt'}")

    labels = list(input_band_labels) or [f"Band{i}" for i in range(1, band_count + 1)]
    while len(labels) < band_count:
        labels.append(f"Band{len(labels)+1}")

    # ColorInterp je Band + Warnung bei wegfallendem Alpha-Band
    color_interps = [
        gdal.GetColorInterpretationName(src_ds.GetRasterBand(i).GetColorInterpretation())
        for i in range(1, band_count + 1)
    ]
    _log(f"  Quellbänder   : { {i+1: f'{labels[i]} ({color_interps[i]})' for i in range(band_count)} }")

    dropped = [b for b in range(1, band_count + 1) if b not in output_bands]
    for b in dropped:
        if color_interps[b - 1] == "Alpha":
            _log(f"  ⚠ WARNUNG     : Band {b} hat ColorInterp=Alpha – Transparenzmaske fällt weg. "
                 f"NoData={'«' + nodata + '»' if nodata else 'nicht gesetzt'}.")

    if any(b < 1 or b > band_count for b in output_bands):
        raise ValueError(
            f"Ungültige Band-Indizes {output_bands} – "
            f"Quelldatei hat {band_count} Bänder (erlaubt: 1–{band_count})."
        )

    out_labels = [labels[b-1] for b in output_bands]
    _log(f"  Ausgabebänder : {dict(enumerate(out_labels, 1))}  (Quellindizes: {output_bands})")

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    nodata_val = float(nodata) if nodata.strip() else None
    cog_options = [
        f"COMPRESS={compress}",
        "PREDICTOR=2",
        f"BLOCKSIZE={blocksize}",
        f"OVERVIEWS={overviews}",
        f"OVERVIEW_RESAMPLING={overview_resampling}",
        "BIGTIFF=IF_SAFER",
    ]

    _log(f"\nSchreibe COGTIFF: {output_path}")
    _log(f"  Kompression   : {compress}, Kachelgrösse: {blocksize}")
    _log(f"  Overviews     : {overviews}  ({overview_resampling})")
    _log(f"  NoData        : {nodata_val if nodata_val is not None else '(nicht gesetzt)'}")

    translate_options = gdal.TranslateOptions(
        bandList=output_bands,
        format="COG",
        creationOptions=cog_options,
        noData=nodata_val,
    )

    out_ds = gdal.Translate(output_path, src_ds, options=translate_options)
    if out_ds is None:
        raise RuntimeError("gdal.Translate hat None zurückgegeben – Ausgabe fehlgeschlagen.")

    out_ds.FlushCache()
    out_ds = None
    src_ds = None

    # Verifikation
    verify_ds = gdal.Open(output_path, gdal.GA_ReadOnly)
    if verify_ds is None:
        raise RuntimeError(f"Ausgabedatei konnte nicht geöffnet werden: {output_path}")

    _log("\nVerifikation:")
    _log(f"  Bänder        : {verify_ds.RasterCount}")
    _log(f"  Auflösung     : {verify_ds.RasterXSize} × {verify_ds.RasterYSize} px")
    _log(f"  Datentyp      : {gdal.GetDataTypeName(verify_ds.GetRasterBand(1).DataType)}")

    size_in  = Path(input_path).stat().st_size  / (1024**2)
    size_out = Path(output_path).stat().st_size / (1024**2)
    _log(f"  Dateigrösse   : {size_in:.1f} MB  →  {size_out:.1f} MB")

    verify_ds = None
    _log("Fertig.")


# ─── Entry Point ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = BandKonverterApp()
    app.mainloop()
