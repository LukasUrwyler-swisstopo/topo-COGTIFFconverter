"""
COGTIFF Band-Konverter (flexibles Band-Mapping)
------------------------------------------------
Liest ein Cloud-Optimized GeoTIFF (beliebig viele Bänder) und schreibt
ein neues COGTIFF mit einer frei wählbaren Auswahl und Reihenfolge der Bänder.

Typische Anwendungsfälle:
    RGBN (1=R, 2=G, 3=B, 4=N)  -->  RGB  : OUTPUT_BANDS = [1, 2, 3]
    RGBN (1=R, 2=G, 3=B, 4=N)  -->  NRG  : OUTPUT_BANDS = [4, 1, 2]
    NRGB (1=N, 2=R, 3=G, 4=B)  -->  RGB  : OUTPUT_BANDS = [2, 3, 4]
    NRGB (1=N, 2=R, 3=G, 4=B)  -->  NRG  : OUTPUT_BANDS = [1, 2, 3]

Anforderungen:
    Python + GDAL (osgeo4w): gdal >= 3.1 (COG-Driver)

Verwendung:
    python convertDATA_cogtiff_4band_to_3band.py
    oder als Modul: convert(input_path, output_path, output_bands, ...)
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from osgeo import gdal

# ---------------------------------------------------------------------------
# Konfiguration – hier anpassen
# ---------------------------------------------------------------------------

INPUT_PATH  = r"C:\pfad\zum\input\dop_4band.tif"
OUTPUT_PATH = r"C:\pfad\zum\output\dop_3band.tif"

# Bandreihenfolge der Quelldatei (nur für Logging, beeinflusst keine Verarbeitung)
#   Beispiel RGBN:  INPUT_BAND_LABELS = ["R", "G", "B", "N"]
#   Beispiel NRGB:  INPUT_BAND_LABELS = ["N", "R", "G", "B"]
INPUT_BAND_LABELS = ["R", "G", "B", "N"]

# Auswahl und Reihenfolge der Ausgabebänder (1-basierte Quellband-Indizes)
#   Beispiele für RGBN-Quelle:
#     RGB  -->  [1, 2, 3]
#     NRG  -->  [4, 1, 2]
#   Beispiele für NRGB-Quelle:
#     RGB  -->  [2, 3, 4]
#     NRG  -->  [1, 2, 3]
OUTPUT_BANDS = [1, 2, 3]

# NoData-Wert für die Ausgabedatei (leer = kein NoData gesetzt)
#   Hintergrund: Wenn Band 4 von GDAL als Alpha-Kanal interpretiert wird
#   (ColorInterp=Alpha, Mask Flags: PER_DATASET ALPHA), geht beim Extrahieren
#   von Bändern 1-3 die Transparenzmaske verloren. NoData="0" markiert dann
#   schwarze Hintergrundpixel (Wert=0) explizit als NoData.
#   8bit  (Byte)  schwarzer Hintergrund: NODATA_VALUE = "0"
#   16bit (UInt16) schwarzer Hintergrund: NODATA_VALUE = "0"
#   kein NoData gewünscht:               NODATA_VALUE = ""
NODATA_VALUE = "0"

# COG-Erstellungsoptionen
COG_OPTIONS = {
    "COMPRESS":           "DEFLATE",  # verlustfrei; alternativ: LZW, ZSTD
    "PREDICTOR":          "2",        # Horizontal-Differenz-Predictor (gut für 8/16bit)
    "BLOCKSIZE":          "512",      # Kachelgrösse (COG-Standard: 512)
    "OVERVIEWS":          "AUTO",     # Overviews automatisch berechnen
    "OVERVIEW_RESAMPLING":"LANCZOS",  # Qualitativ hochwertige Übersicht
    "BIGTIFF":            "IF_SAFER", # BigTIFF bei Bedarf (>4 GB)
}

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Konvertierungsfunktion
# ---------------------------------------------------------------------------

def convert(
    input_path: str | Path,
    output_path: str | Path,
    output_bands: list[int],
    input_band_labels: list[str] | None = None,
    nodata: str = "",
) -> None:
    """
    Schreibt ein neues COGTIFF mit gewählter Band-Auswahl und -Reihenfolge.

    Args:
        input_path:         Pfad zur Quelldatei (beliebig viele Bänder)
        output_path:        Pfad zur Ausgabedatei (wird überschrieben)
        output_bands:       1-basierte Quellband-Indizes in gewünschter Ausgabereihenfolge
                            z.B. [1, 2, 3] oder [4, 1, 2]
        input_band_labels:  Optionale Bezeichnungen der Quellbänder (nur für Logging)
                            z.B. ["R", "G", "B", "N"] oder ["N", "R", "G", "B"]
        nodata:             NoData-Wert für die Ausgabedatei als String (z.B. "0").
                            Leer lassen wenn kein NoData gesetzt werden soll.
    """
    input_path  = str(input_path)
    output_path = str(output_path)

    gdal.UseExceptions()

    # --- Quelldatei öffnen und prüfen ---
    log.info(f"Öffne Quelldatei: {input_path}")
    src_ds = gdal.Open(input_path, gdal.GA_ReadOnly)
    if src_ds is None:
        raise FileNotFoundError(f"GDAL konnte die Datei nicht öffnen: {input_path}")

    band_count = src_ds.RasterCount
    dtype      = src_ds.GetRasterBand(1).DataType
    srs        = src_ds.GetSpatialRef()

    log.info(f"  Bänder gesamt : {band_count}")
    log.info(f"  Auflösung     : {src_ds.RasterXSize} x {src_ds.RasterYSize} px")
    log.info(f"  Datentyp      : {gdal.GetDataTypeName(dtype)}")
    log.info(f"  Koordinatensys: {srs.GetName() if srs else 'nicht gesetzt'}")

    # Band-Labels und ColorInterp für Logging aufbereiten
    labels = input_band_labels or [f"Band{i}" for i in range(1, band_count + 1)]
    if len(labels) < band_count:
        labels += [f"Band{i}" for i in range(len(labels) + 1, band_count + 1)]

    color_interps = [
        gdal.GetColorInterpretationName(src_ds.GetRasterBand(i).GetColorInterpretation())
        for i in range(1, band_count + 1)
    ]
    log.info(f"  Quellbänder   : { {i+1: f'{labels[i]} ({color_interps[i]})' for i in range(band_count)} }")

    # Warnung wenn ein wegfallendes Band als Alpha interpretiert wird
    dropped = [b for b in range(1, band_count + 1) if b not in output_bands]
    for b in dropped:
        if color_interps[b - 1] == "Alpha":
            log.warning(
                f"  Band {b} hat ColorInterp=Alpha und wird nicht in die Ausgabe übernommen. "
                f"Die Transparenzmaske geht verloren. "
                f"NoData={'«' + nodata + '»' if nodata else 'nicht gesetzt'} kompensiert dies."
            )

    # Eingabe validieren
    if any(b < 1 or b > band_count for b in output_bands):
        raise ValueError(
            f"OUTPUT_BANDS {output_bands} enthält ungültige Indizes "
            f"(Quelldatei hat {band_count} Bänder, erlaubt: 1–{band_count})."
        )

    output_labels = [labels[b - 1] for b in output_bands]
    log.info(f"  Ausgabebänder : {dict(enumerate(output_labels, 1))}  (Quellindizes: {output_bands})")

    # Zielverzeichnis anlegen
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    # --- gdal.Translate: Bändauswahl + COG-Ausgabe ---
    nodata_val = float(nodata) if nodata.strip() else None
    translate_options = gdal.TranslateOptions(
        bandList=output_bands,
        format="COG",
        creationOptions=[f"{k}={v}" for k, v in COG_OPTIONS.items()],
        noData=nodata_val,
    )

    log.info(f"Schreibe COGTIFF: {output_path}")
    log.info(f"  Kompression   : {COG_OPTIONS['COMPRESS']}, Kachelgrösse: {COG_OPTIONS['BLOCKSIZE']}")
    log.info(f"  NoData        : {nodata_val if nodata_val is not None else '(nicht gesetzt)'}")

    out_ds = gdal.Translate(output_path, src_ds, options=translate_options)

    if out_ds is None:
        raise RuntimeError("gdal.Translate hat None zurückgegeben – Ausgabe fehlgeschlagen.")

    out_ds.FlushCache()
    out_ds = None
    src_ds = None

    # --- Ergebnis verifizieren ---
    verify_ds = gdal.Open(output_path, gdal.GA_ReadOnly)
    if verify_ds is None:
        raise RuntimeError(f"Ausgabedatei konnte nicht geöffnet werden: {output_path}")

    log.info("Verifikation:")
    log.info(f"  Bänder        : {verify_ds.RasterCount}")
    log.info(f"  Auflösung     : {verify_ds.RasterXSize} x {verify_ds.RasterYSize} px")
    log.info(f"  Datentyp      : {gdal.GetDataTypeName(verify_ds.GetRasterBand(1).DataType)}")

    size_in  = Path(input_path).stat().st_size  / (1024 ** 2)
    size_out = Path(output_path).stat().st_size / (1024 ** 2)
    log.info(f"  Dateigrösse   : {size_in:.1f} MB  →  {size_out:.1f} MB")

    verify_ds = None
    log.info("Fertig.")


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    try:
        convert(
            input_path=INPUT_PATH,
            output_path=OUTPUT_PATH,
            output_bands=OUTPUT_BANDS,
            input_band_labels=INPUT_BAND_LABELS,
            nodata=NODATA_VALUE,
        )
    except Exception as exc:
        log.error(f"Fehler: {exc}")
        sys.exit(1)
