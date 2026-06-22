"""
_osgeo_runner.py - Wird via OSGeo4W Python aufgerufen (NICHT direkt starten).
Liest Parameter aus einer JSON-Datei und fuehrt GDAL-abhaengige Funktionen aus.
Ausgabe geht auf stdout -> wird vom GUI live im Log angezeigt.

Aktionen:
    info    - Metadaten aus Quelldatei lesen, Ergebnis als JSON auf stdout
    convert - COGTIFF Band-Konvertierung durchfuehren, Fortschritt auf stdout
"""

import sys
import os
import json
import traceback
import time
from pathlib import Path


def _info(cfg: dict) -> None:
    """Liest Datei-Metadaten und gibt sie als JSON-Zeile auf stdout aus."""
    from osgeo import gdal
    gdal.UseExceptions()

    input_path = cfg["input_path"]
    ds = gdal.Open(input_path, gdal.GA_ReadOnly)
    if ds is None:
        raise RuntimeError(f"GDAL konnte die Datei nicht oeffnen: {input_path}")

    bc   = ds.RasterCount
    rx   = ds.RasterXSize
    ry   = ds.RasterYSize
    dt   = gdal.GetDataTypeName(ds.GetRasterBand(1).DataType)
    srs  = ds.GetSpatialRef()
    crs  = srs.GetName() if srs else "nicht gesetzt"
    size = Path(input_path).stat().st_size / (1024 ** 2)

    ci_parts    = []
    alpha_bands = []
    for i in range(1, bc + 1):
        band = ds.GetRasterBand(i)
        ci   = gdal.GetColorInterpretationName(band.GetColorInterpretation())
        ci_parts.append(ci)
        if ci == "Alpha":
            alpha_bands.append(i)

    nd_raw = ds.GetRasterBand(1).GetNoDataValue()
    ds = None

    result = {
        "bands":        bc,
        "colorinterp":  ci_parts,
        "width":        rx,
        "height":       ry,
        "dtype":        dt,
        "crs":          crs,
        "size_mb":      round(size, 1),
        "nodata":       nd_raw,
        "alpha_bands":  alpha_bands,
    }
    print(json.dumps(result, ensure_ascii=False), flush=True)


def _convert(cfg: dict) -> None:
    """Fuehrt die COGTIFF Band-Konvertierung durch. Fortschritt auf stdout."""
    from osgeo import gdal

    input_path          = cfg["input_path"]
    output_path         = cfg["output_path"]
    output_bands        = cfg["output_bands"]
    input_band_labels   = cfg["input_band_labels"]
    compress            = cfg.get("compress",            "DEFLATE")
    blocksize           = cfg.get("blocksize",           "256")
    overviews           = cfg.get("overviews",           "AUTO")
    overview_resampling = cfg.get("overview_resampling", "LANCZOS")
    nodata              = cfg.get("nodata",              "")

    def _log(msg: str) -> None:
        print(msg, flush=True)

    gdal.UseExceptions()

    _log(f"Oeffne Quelldatei: {input_path}")
    src_ds = gdal.Open(input_path, gdal.GA_ReadOnly)
    if src_ds is None:
        raise FileNotFoundError(f"GDAL konnte die Datei nicht oeffnen: {input_path}")

    band_count = src_ds.RasterCount
    dtype      = src_ds.GetRasterBand(1).DataType
    srs        = src_ds.GetSpatialRef()

    _log(f"  Baender gesamt : {band_count}")
    _log(f"  Aufloesung     : {src_ds.RasterXSize} x {src_ds.RasterYSize} px")
    _log(f"  Datentyp      : {gdal.GetDataTypeName(dtype)}")
    _log(f"  Koordinatensys: {srs.GetName() if srs else 'nicht gesetzt'}")

    labels = list(input_band_labels) or [f"Band{i}" for i in range(1, band_count + 1)]
    while len(labels) < band_count:
        labels.append(f"Band{len(labels) + 1}")

    color_interps = [
        gdal.GetColorInterpretationName(src_ds.GetRasterBand(i).GetColorInterpretation())
        for i in range(1, band_count + 1)
    ]

    for b in range(1, band_count + 1):
        if b not in output_bands and color_interps[b - 1] == "Alpha":
            _log(
                "  WARNING       : Band %d hat ColorInterp=Alpha - Transparenzmaske faellt weg. "
                "NoData=%s." % (b, ('<' + str(nodata) + '>' if nodata else 'nicht gesetzt'))
            )

    if any(b < 1 or b > band_count for b in output_bands):
        raise ValueError(
            f"Ungueltige Band-Indizes {output_bands} - "
            f"Quelldatei hat {band_count} Baender (erlaubt: 1-{band_count})."
        )

    out_labels = [labels[b - 1] for b in output_bands]
    _log(f"  Ausgabebaender : {dict(enumerate(out_labels, 1))}  (Quellindizes: {output_bands})")

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    nodata_val  = float(nodata) if str(nodata).strip() else None
    cog_options = [
        f"COMPRESS={compress}",
        "PREDICTOR=2",
        f"BLOCKSIZE={blocksize}",
        f"OVERVIEWS={overviews}",
        f"OVERVIEW_RESAMPLING={overview_resampling}",
        "BIGTIFF=IF_SAFER",
    ]

    _log(f"\nSchreibe COGTIFF: {output_path}")
    _log(f"  Kompression   : {compress}, Kachelgroesse: {blocksize}")
    _log(f"  Overviews     : {overviews}  ({overview_resampling})")
    _log(f"  NoData        : {nodata_val if nodata_val is not None else '(nicht gesetzt)'}")

    translate_options = gdal.TranslateOptions(
        bandList=output_bands,
        format="COG",
        creationOptions=cog_options,
        noData=nodata_val,
    )

    # Progress callback: throttled to avoid slowing the process
    last_emit = {"t": 0.0, "p": -1.0}

    def _progress(complete, message, unknown=None):
        try:
            if complete is None:
                return 1
            pct = float(complete)
            now = time.time()
            # emit at most once per second or when progress changed by >=0.5%
            if (now - last_emit["t"]) >= 1.0 or (pct - last_emit["p"]) >= 0.005:
                print(f"PROGRESS:{pct:.6f}", flush=True)
                last_emit["t"] = now
                last_emit["p"] = pct
        except Exception:
            pass
        return 1

    out_ds = gdal.Translate(output_path, src_ds, options=translate_options, callback=_progress)
    if out_ds is None:
        raise RuntimeError("gdal.Translate hat None zurueckgegeben – Ausgabe fehlgeschlagen.")

    out_ds.FlushCache()
    out_ds = None
    src_ds = None

    verify_ds = gdal.Open(output_path, gdal.GA_ReadOnly)
    if verify_ds is None:
        raise RuntimeError(f"Ausgabedatei konnte nicht geoeffnet werden: {output_path}")

    _log("\nVerifikation:")
    _log(f"  Baender        : {verify_ds.RasterCount}")
    _log(f"  Aufloesung     : {verify_ds.RasterXSize} x {verify_ds.RasterYSize} px")
    _log(f"  Datentyp      : {gdal.GetDataTypeName(verify_ds.GetRasterBand(1).DataType)}")

    size_in  = Path(input_path).stat().st_size  / (1024 ** 2)
    size_out = Path(output_path).stat().st_size / (1024 ** 2)
    _log(f"  Dateigroesse   : {size_in:.1f} MB  ->  {size_out:.1f} MB")

    verify_ds = None
    _log("Fertig.")


def main() -> None:
    if len(sys.argv) < 2:
        print("[FEHLER] Kein Konfigurationspfad uebergeben.", flush=True)
        sys.exit(1)

    with open(sys.argv[1], encoding="utf-8") as f:
        cfg = json.load(f)

    action = cfg.get("action", "")

    try:
        if action == "info":
            _info(cfg)
        elif action == "convert":
            _convert(cfg)
        else:
            print(f"[FEHLER] Unbekannte Aktion: '{action}'", flush=True)
            sys.exit(1)

    except Exception as e:
        print(f"\n[FEHLER] {e}", flush=True)
        print(traceback.format_exc(), flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
