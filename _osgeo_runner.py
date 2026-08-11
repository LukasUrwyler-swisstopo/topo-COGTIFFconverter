"""
_osgeo_runner.py - Wird via OSGeo4W Python aufgerufen (NICHT direkt starten).
Liest Parameter aus einer JSON-Datei und fuehrt GDAL-abhaengige Funktionen aus.
Ausgabe geht auf stdout -> wird vom GUI live im Log angezeigt.

Aktionen:
    info       - Metadaten aus Quelldatei lesen, Ergebnis als JSON auf stdout
    convert    - COGTIFF Band-Konvertierung durchfuehren, Fortschritt auf stdout
    mosaic     - Kachel-TIFFs (+ .tfw) zu VRT mosaikieren und als COGTIFF schreiben
    to_bigtiff - COGTIFF zu klassischem (Big)TIFF + TFW konvertieren:
                 Einzeldatei ("single") oder Kacheln via Grid-Shape ("tiles")
"""

import sys
import os
import glob
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

    bc     = ds.RasterCount
    rx     = ds.RasterXSize
    ry     = ds.RasterYSize
    gdt    = ds.GetRasterBand(1).DataType
    dt     = gdal.GetDataTypeName(gdt)
    bits   = gdal.GetDataTypeSize(gdt)
    srs    = ds.GetSpatialRef()
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

    # Kompression & Layout (COG vs. gekacheltes TIFF vs. gestreiftes TIFF)
    compression = ds.GetMetadataItem("COMPRESSION", "IMAGE_STRUCTURE") or "keine/unbekannt"
    layout      = ds.GetMetadataItem("LAYOUT", "IMAGE_STRUCTURE")  # "COG" falls Cloud-Optimized-GeoTIFF erkannt
    blk_x, blk_y = ds.GetRasterBand(1).GetBlockSize()
    if layout == "COG":
        layout_str = "COG"
    elif blk_x < rx:
        layout_str = f"Tiled TIFF ({blk_x}x{blk_y})"
    else:
        layout_str = "Striped TIFF"

    ds = None

    result = {
        "bands":        bc,
        "colorinterp":  ci_parts,
        "width":        rx,
        "height":       ry,
        "dtype":        dt,
        "bitdepth":     bits,
        "crs":          crs,
        "size_mb":      round(size, 1),
        "nodata":       nd_raw,
        "alpha_bands":  alpha_bands,
        "compression":  compression,
        "layout":       layout_str,
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
    quality             = cfg.get("quality",              "90")
    band4_mode          = cfg.get("band4_mode",           "nir")   # "nir" | "alpha"
    alpha_band          = cfg.get("alpha_band")                    # 1-basierter Quellindex, nur bei band4_mode="alpha"
    mask_nodata_value   = cfg.get("mask_nodata_value",    "0")     # "0" | "255", nur bei band4_mode="nir"

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

    if band4_mode == "alpha":
        if not alpha_band or alpha_band < 1 or alpha_band > band_count:
            raise ValueError(
                f"band4_mode='alpha' erfordert einen gueltigen 'alpha_band'-Index (1-{band_count}), "
                f"erhalten: {alpha_band}"
            )
        if alpha_band in output_bands:
            raise ValueError(
                f"Alpha-Band {alpha_band} darf nicht gleichzeitig in 'output_bands' enthalten sein."
            )
        _log(f"  4. Kanal      : Alpha (Band {alpha_band}) -> wird als interne Maske uebernommen")
    else:
        _log(f"  4. Kanal      : NIR/regulaer -> Maske aus NoData-Bedingung (Wert={mask_nodata_value}, alle Ausgabebaender)")

    if any(b < 1 or b > band_count for b in output_bands):
        raise ValueError(
            f"Ungueltige Band-Indizes {output_bands} - "
            f"Quelldatei hat {band_count} Baender (erlaubt: 1-{band_count})."
        )

    out_labels = [labels[b - 1] for b in output_bands]
    _log(f"  Ausgabebaender : {dict(enumerate(out_labels, 1))}  (Quellindizes: {output_bands})")

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    nodata_val  = float(mask_nodata_value) if band4_mode == "nir" else None
    cog_options = [
        f"COMPRESS={compress}",
        f"BLOCKSIZE={blocksize}",
        f"OVERVIEWS={overviews}",
        f"OVERVIEW_RESAMPLING={overview_resampling}",
        "BIGTIFF=YES",
        "NUM_THREADS=ALL_CPUS",
        "ADD_ALPHA=NO",
    ]
    if compress.upper() == "JPEG":
        cog_options += [f"QUALITY={quality}", f"OVERVIEW_QUALITY={quality}"]
    else:
        cog_options.append("PREDICTOR=2")

    _log(f"\nSchreibe COGTIFF: {output_path}")
    _log(f"  Kompression   : {compress}" + (f" (QUALITY={quality})" if compress.upper() == "JPEG" else "") + f", Kachelgroesse: {blocksize}")
    _log(f"  Overviews     : {overviews}  ({overview_resampling})")
    if band4_mode == "nir":
        _log(f"  NoData (Maske): {nodata_val:g}  (nur zur Maskenberechnung, nicht als Datei-Metadatum gesetzt)")

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

    if band4_mode == "alpha":
        _log(f"  Maske         : aus Alpha-Band {alpha_band} uebernommen (interne Maske)")
        translate_options = gdal.TranslateOptions(
            bandList=output_bands,
            format="COG",
            creationOptions=cog_options,
            maskBand=alpha_band,
        )
        out_ds = gdal.Translate(output_path, src_ds, options=translate_options, callback=_progress)
    else:
        import numpy as np

        _log(f"  Maske         : berechnet aus NoData={nodata_val:g}  "
             f"(Pixel ungueltig, wenn ALLE Ausgabebaender = {nodata_val:g})")
        mem_ds = gdal.Translate("", src_ds, format="MEM", bandList=output_bands)
        arrs = [mem_ds.GetRasterBand(i).ReadAsArray() for i in range(1, mem_ds.RasterCount + 1)]
        invalid = np.ones(arrs[0].shape, dtype=bool)
        for arr in arrs:
            invalid &= (arr == nodata_val)
        mask_arr = np.where(invalid, 0, 255).astype("uint8")
        mem_ds.CreateMaskBand(gdal.GMF_PER_DATASET)
        mem_ds.GetRasterBand(1).GetMaskBand().WriteArray(mask_arr)

        # Hinweis: 'noData' hier NICHT zusaetzlich am Ziel setzen - das erzeugt einen
        # GDAL-internen Konflikt "conflicting mask sources", der die oben berechnete
        # Maske verwirft (Ausgabe waere faelschlich komplett gueltig). Die Maske allein
        # ist hier die massgebliche/vollstaendige Gueltigkeitsinformation.
        translate_options = gdal.TranslateOptions(
            format="COG",
            creationOptions=cog_options,
        )
        out_ds = gdal.Translate(output_path, mem_ds, options=translate_options, callback=_progress)
        mem_ds = None

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


#: Nominal Wertebereiche je Bit-Tiefe, fuer die automatische Skalierung
#: bei einer Bit-Tiefe-Konvertierung (z.B. 16bit -> 8bit).
_BITDEPTH_RANGES = {
    "8bit":  (0, 255),
    "16bit": (0, 65535),
}


def _iter_blocks(width: int, height: int, block: int = 2048):
    """Liefert (x, y, xsize, ysize)-Tupel fuer eine blockweise Rasterverarbeitung."""
    for y in range(0, height, block):
        ys = min(block, height - y)
        for x in range(0, width, block):
            xs = min(block, width - x)
            yield x, y, xs, ys


def _write_nodata_mask(ds, thresholds: list, block: int = 2048) -> None:
    """Berechnet blockweise (speicherschonend, auch fuer sehr grosse Mosaike) eine
    interne GDAL-Gueltigkeitsmaske: ein Pixel gilt nur dann als NoData, wenn ALLE
    Baender gleichzeitig ihrem jeweiligen Schwellwert (Index = Bandposition in
    'thresholds') entsprechen - analog zur Maskenlogik im 'change BANDS'-Tab
    (dort fuer Einzeldateien direkt im Speicher, hier blockweise auf Platte)."""
    from osgeo import gdal
    import numpy as np

    ds.CreateMaskBand(gdal.GMF_PER_DATASET)
    mask_band = ds.GetRasterBand(1).GetMaskBand()
    for x, y, xs, ys in _iter_blocks(ds.RasterXSize, ds.RasterYSize, block):
        invalid = np.ones((ys, xs), dtype=bool)
        for i, thr in enumerate(thresholds, start=1):
            arr = ds.GetRasterBand(i).ReadAsArray(x, y, xs, ys)
            invalid &= (arr == thr)
        mask_band.WriteArray(np.where(invalid, 0, 255).astype("uint8"), x, y)


def _mosaic(cfg: dict) -> None:
    """Mosaikiert Kachel-TIFFs (VRT) und schreibt das Ergebnis als COGTIFF. Fortschritt auf stdout."""
    from osgeo import gdal

    input_dir           = cfg["input_dir"]
    output_dir          = cfg["output_dir"]
    output_name         = cfg["output_name"]
    compress            = cfg.get("compress",            "JPEG")
    quality             = cfg.get("quality",             "90")
    blocksize           = cfg.get("blocksize",           "256")
    overviews           = cfg.get("overviews",           "AUTO")
    overview_resampling = cfg.get("overview_resampling", "AVERAGE")
    nodata              = cfg.get("nodata",              "").strip()
    output_bands        = cfg.get("output_bands",        []) or []
    input_band_labels   = cfg.get("input_band_labels",   []) or []
    output_bitdepth     = cfg.get("output_bitdepth",     "").strip()

    def _log(msg: str) -> None:
        print(msg, flush=True)

    gdal.UseExceptions()

    tiles = sorted(
        {p for pat in ("*.tif", "*.tiff") for p in glob.glob(os.path.join(input_dir, pat))}
    )
    if not tiles:
        raise FileNotFoundError(f"Keine .tif/.tiff Kacheln gefunden in: {input_dir}")

    _log(f"Gefundene Kacheln : {len(tiles)}")
    _log(f"Quellordner       : {input_dir}")

    vrt_dir = Path(output_dir) / "vrt"
    vrt_dir.mkdir(parents=True, exist_ok=True)
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    vrt_path = vrt_dir / f"{output_name}.vrt"
    out_path = Path(output_dir) / f"{output_name}.tif"

    _log(f"\nErstelle VRT-Mosaik: {vrt_path}")
    if nodata:
        _log(f"  NoData (VRT) : {nodata}")
    vrt_options = gdal.BuildVRTOptions(
        srcNodata=nodata or None,
        VRTNodata=nodata or None,
    )
    vrt_ds = gdal.BuildVRT(str(vrt_path), tiles, options=vrt_options)
    if vrt_ds is None:
        raise RuntimeError("gdal.BuildVRT hat None zurueckgegeben - VRT-Erstellung fehlgeschlagen.")
    vrt_ds.FlushCache()
    vrt_ds = None

    cog_options = [
        f"COMPRESS={compress}",
        f"BLOCKSIZE={blocksize}",
        f"OVERVIEWS={overviews}",
        f"OVERVIEW_RESAMPLING={overview_resampling}",
        "NUM_THREADS=ALL_CPUS",
        "BIGTIFF=YES",
        "ADD_ALPHA=NO",
    ]
    if compress.upper() == "JPEG":
        cog_options += [f"QUALITY={quality}", f"OVERVIEW_QUALITY={quality}"]
    else:
        cog_options.append("PREDICTOR=2")

    nodata_tokens = [float(t) for t in nodata.split()] if nodata else []

    src_ds = gdal.Open(str(vrt_path), gdal.GA_ReadOnly)
    if src_ds is None:
        raise RuntimeError(f"GDAL konnte das VRT nicht oeffnen: {vrt_path}")

    band_count = src_ds.RasterCount
    src_dtype  = src_ds.GetRasterBand(1).DataType

    # --- Band-Auswahl (analog zur 'convert'-Aktion) ---
    if any(b < 1 or b > band_count for b in output_bands):
        raise ValueError(
            f"Ungueltige Band-Indizes {output_bands} - "
            f"Mosaik hat {band_count} Baender (erlaubt: 1-{band_count})."
        )
    band_list = output_bands or None
    if output_bands:
        labels = list(input_band_labels) or [f"Band{i}" for i in range(1, band_count + 1)]
        while len(labels) < band_count:
            labels.append(f"Band{len(labels) + 1}")
        out_labels = [labels[b - 1] for b in output_bands]
        _log(f"  Ausgabebaender : {dict(enumerate(out_labels, 1))}  (Quellindizes: {output_bands})")

    # NoData-Schwellwerte je Ausgabeband, aus den Quellband-Positionen der
    # GUI-Angabe (z.B. "0 0 0" -> Band1=0, Band2=0, Band3=0). Fehlt fuer ein
    # gewaehltes Ausgabeband ein eigener Wert (z.B. weniger Werte als Baender),
    # wird der erste Wert als Fallback verwendet.
    mask_bands = output_bands or list(range(1, band_count + 1))
    nodata_thresholds = [
        nodata_tokens[b - 1] if (b - 1) < len(nodata_tokens) else nodata_tokens[0]
        for b in mask_bands
    ] if nodata_tokens else []

    # --- Bit-Tiefe-Konvertierung (Output) ---
    output_type  = None
    scale_params = None
    if output_bitdepth in _BITDEPTH_RANGES:
        dst_min, dst_max = _BITDEPTH_RANGES[output_bitdepth]
        dst_gdal_type = gdal.GDT_Byte if output_bitdepth == "8bit" else gdal.GDT_UInt16
        if dst_gdal_type != src_dtype:
            src_min, src_max = (0, 255) if src_dtype == gdal.GDT_Byte else _BITDEPTH_RANGES["16bit"]
            n_out_bands  = len(output_bands) if output_bands else band_count
            output_type  = dst_gdal_type
            scale_params = [[src_min, src_max, dst_min, dst_max] for _ in range(n_out_bands)]
            _log(f"  Bit-Tiefe     : {gdal.GetDataTypeName(src_dtype)} -> {gdal.GetDataTypeName(dst_gdal_type)} "
                 f"(skaliert {src_min}-{src_max} -> {dst_min}-{dst_max})")

    _log(f"\nSchreibe COGTIFF: {out_path}")
    _log(f"  Kompression   : {compress}" + (f" (QUALITY={quality})" if compress.upper() == "JPEG" else ""))
    _log(f"  Kachelgroesse : {blocksize}")
    _log(f"  Overviews     : {overviews}  ({overview_resampling})")
    if nodata_thresholds:
        _log(f"  NoData-Maske  : Schwellwerte je Ausgabeband {nodata_thresholds}  "
             f"(Pixel ungueltig, wenn ALLE Ausgabebaender gleichzeitig matchen)")
    else:
        _log("  NoData        : (nicht gesetzt)")
    _log("  Koordinatensys: EPSG:2056")

    last_emit = {"t": 0.0, "p": -1.0}

    def _progress(complete, message, unknown=None):
        try:
            if complete is None:
                return 1
            pct = float(complete)
            now = time.time()
            if (now - last_emit["t"]) >= 1.0 or (pct - last_emit["p"]) >= 0.005:
                print(f"PROGRESS:{pct:.6f}", flush=True)
                last_emit["t"] = now
                last_emit["p"] = pct
        except Exception:
            pass
        return 1

    if nodata_thresholds:
        # Zweistufig, damit die Maske speicherschonend (blockweise, auch bei sehr
        # grossen Mosaiken) und ohne verlustbehaftete Rundungsfehler (COMPRESS=JPEG)
        # berechnet werden kann:
        #   1) unkomprimiertes Zwischenraster (Bandauswahl + Bit-Tiefe bereits angewandt)
        #   2) NoData-Maske blockweise berechnen und als interne GDAL-Maske anhaengen
        #   3) als finales COGTIFF komprimieren (Maske wird automatisch uebernommen)
        # 'noData' wird am Ziel bewusst NICHT zusaetzlich gesetzt - das erzeugt einen
        # GDAL-internen Konflikt "conflicting mask sources" und verwirft die Maske.
        scratch_path = vrt_dir / f"{output_name}_scratch.tif"
        _log(f"\nZwischenraster (fuer Maskenberechnung): {scratch_path}")

        scratch_kwargs = dict(
            format="GTiff",
            outputSRS="EPSG:2056",
            # explizit unsetzen: das VRT traegt aus srcNodata/VRTNodata bereits ein
            # NoDataValue je Band - das wuerde sonst mitkopiert und kollidiert mit
            # der unten separat berechneten Maske ("conflicting mask sources").
            noData="none",
            creationOptions=["TILED=YES", "BLOCKXSIZE=512", "BLOCKYSIZE=512",
                              "COMPRESS=LZW", "BIGTIFF=YES"],
        )
        if band_list is not None:
            scratch_kwargs["bandList"] = band_list
        if output_type is not None:
            scratch_kwargs["outputType"]  = output_type
            scratch_kwargs["scaleParams"] = scale_params
        scratch_options = gdal.TranslateOptions(**scratch_kwargs)
        scratch_ds = gdal.Translate(str(scratch_path), src_ds, options=scratch_options, callback=_progress)
        if scratch_ds is None:
            raise RuntimeError("gdal.Translate (Zwischenraster) hat None zurueckgegeben.")
        scratch_ds.FlushCache()
        scratch_ds = None
        src_ds = None

        scratch_ds = gdal.Open(str(scratch_path), gdal.GA_Update)
        if scratch_ds is None:
            raise RuntimeError(f"GDAL konnte das Zwischenraster nicht oeffnen: {scratch_path}")
        _write_nodata_mask(scratch_ds, nodata_thresholds)
        scratch_ds.FlushCache()

        final_options = gdal.TranslateOptions(
            format="COG",
            outputSRS="EPSG:2056",
            creationOptions=cog_options,
        )
        last_emit["t"], last_emit["p"] = 0.0, -1.0
        out_ds = gdal.Translate(str(out_path), scratch_ds, options=final_options, callback=_progress)
        scratch_ds = None
        for candidate in (scratch_path, Path(str(scratch_path) + ".aux.xml")):
            try:
                if candidate.exists():
                    candidate.unlink()
            except OSError:
                pass
    else:
        translate_kwargs = dict(
            format="COG",
            outputSRS="EPSG:2056",
            creationOptions=cog_options,
        )
        if band_list is not None:
            translate_kwargs["bandList"] = band_list
        if output_type is not None:
            translate_kwargs["outputType"]  = output_type
            translate_kwargs["scaleParams"] = scale_params
        translate_options = gdal.TranslateOptions(**translate_kwargs)
        out_ds = gdal.Translate(str(out_path), src_ds, options=translate_options, callback=_progress)

    if out_ds is None:
        raise RuntimeError("gdal.Translate hat None zurueckgegeben - Ausgabe fehlgeschlagen.")

    out_ds.FlushCache()
    out_ds = None
    src_ds = None

    verify_ds = gdal.Open(str(out_path), gdal.GA_ReadOnly)
    if verify_ds is None:
        raise RuntimeError(f"Ausgabedatei konnte nicht geoeffnet werden: {out_path}")

    _log("\nVerifikation:")
    _log(f"  Baender        : {verify_ds.RasterCount}")
    _log(f"  Aufloesung     : {verify_ds.RasterXSize} x {verify_ds.RasterYSize} px")
    _log(f"  Datentyp      : {gdal.GetDataTypeName(verify_ds.GetRasterBand(1).DataType)}")

    size_out = Path(out_path).stat().st_size / (1024 ** 2)
    _log(f"  Dateigroesse   : {size_out:.1f} MB")

    verify_ds = None
    _log("Fertig.")


def _tile_is_empty(ds) -> bool:
    """Prueft, ob eine Kachel keine verwertbaren Bildinformationen enthaelt:
    alle Baender bestehen aus genau einem konstanten Wert (z.B. reine
    Hintergrund-/NoData-Flaeche ausserhalb der eigentlichen Bildkontur).
    Echte Luftbild-Kacheln weisen praktisch nie eine perfekt konstante
    Pixelmatrix auf - dieser Test kommt daher ohne Kenntnis des exakten
    NoData-Werts aus."""
    for i in range(1, ds.RasterCount + 1):
        band = ds.GetRasterBand(i)
        try:
            bmin, bmax = band.ComputeRasterMinMax(0)  # approx_ok=0: exakt
        except RuntimeError:
            # Kein einziges gueltiges Pixel im Sampling (z.B. Band komplett
            # NoData) -> Kachel gilt als leer.
            continue
        if bmin != bmax:
            return False
    return True


def _delete_tile_files(tif_path: str) -> None:
    """Loescht eine Kachel-TIFF samt Begleitdateien (.tfw, .aux.xml)."""
    p = Path(tif_path)
    for candidate in (p, p.with_suffix(".tfw"), Path(str(p) + ".aux.xml")):
        try:
            if candidate.exists():
                candidate.unlink()
        except OSError:
            pass


def _to_bigtiff(cfg: dict) -> None:
    """Konvertiert ein COGTIFF zu klassischem (Big)TIFF + TFW-Weltdatei.
    Modus 'single': gesamtes Raster als eine Ausgabedatei (BIGTIFF=IF_SAFER).
    Modus 'tiles' : Zuschnitt je Feature eines Grid-Shapes (Bounding-Box je Feature);
                    Dateiname aus Attributfeld 'NAME' (+ optional Praefix/Suffix)."""
    from osgeo import gdal, ogr, osr

    mode       = cfg["mode"]                      # "single" | "tiles"
    input_path = cfg["input_path"]
    compress   = cfg.get("compress",  "NONE")
    quality    = cfg.get("quality",   "90")
    blocksize  = cfg.get("blocksize", "256")

    def _log(msg: str) -> None:
        print(msg, flush=True)

    gdal.UseExceptions()
    ogr.UseExceptions()

    _log(f"Oeffne Quelldatei: {input_path}")
    src_ds = gdal.Open(input_path, gdal.GA_ReadOnly)
    if src_ds is None:
        raise FileNotFoundError(f"GDAL konnte die Datei nicht oeffnen: {input_path}")

    _log(f"  Baender gesamt : {src_ds.RasterCount}")
    _log(f"  Aufloesung     : {src_ds.RasterXSize} x {src_ds.RasterYSize} px")

    creation_options = [
        f"COMPRESS={compress}",
        "TILED=YES",
        f"BLOCKXSIZE={blocksize}",
        f"BLOCKYSIZE={blocksize}",
        "TFW=YES",
    ]
    if compress.upper() == "JPEG":
        creation_options.append(f"JPEG_QUALITY={quality}")
    elif compress.upper() in ("LZW", "DEFLATE", "ZSTD"):
        creation_options.append("PREDICTOR=2")

    if mode == "single":
        output_path = cfg["output_path"]
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        _log(f"\nSchreibe BigTIFF: {output_path}")
        _log("  Kompression   : " + compress +
             (f" (JPEG_QUALITY={quality})" if compress.upper() == "JPEG" else ""))
        _log(f"  Kachelgroesse : {blocksize}")
        _log("  Koordinatensys: EPSG:2056")

        translate_options = gdal.TranslateOptions(
            format="GTiff",
            outputSRS="EPSG:2056",
            creationOptions=creation_options + ["BIGTIFF=IF_SAFER"],
        )

        last_emit = {"t": 0.0, "p": -1.0}

        def _progress(complete, message, unknown=None):
            try:
                if complete is None:
                    return 1
                pct = float(complete)
                now = time.time()
                if (now - last_emit["t"]) >= 1.0 or (pct - last_emit["p"]) >= 0.005:
                    print(f"PROGRESS:{pct:.6f}", flush=True)
                    last_emit["t"] = now
                    last_emit["p"] = pct
            except Exception:
                pass
            return 1

        out_ds = gdal.Translate(output_path, src_ds, options=translate_options, callback=_progress)
        if out_ds is None:
            raise RuntimeError("gdal.Translate hat None zurueckgegeben - Ausgabe fehlgeschlagen.")
        out_ds.FlushCache()
        out_ds = None
        src_ds = None

        size_in  = Path(input_path).stat().st_size  / (1024 ** 2)
        size_out = Path(output_path).stat().st_size / (1024 ** 2)
        _log("\nVerifikation:")
        _log(f"  Dateigroesse   : {size_in:.1f} MB  ->  {size_out:.1f} MB")
        _log("Fertig.")
        return

    # --- mode == "tiles" ---
    output_dir      = cfg["output_dir"]
    grid_shape_path = cfg["grid_shape_path"]
    prefix          = (cfg.get("prefix") or "").strip()
    suffix          = (cfg.get("suffix") or "").strip()
    name_field      = "NAME"

    Path(output_dir).mkdir(parents=True, exist_ok=True)

    _log(f"\nOeffne Grid-Shape: {grid_shape_path}")
    shp_ds = ogr.Open(grid_shape_path, 0)
    if shp_ds is None:
        raise FileNotFoundError(f"OGR konnte das Grid-Shape nicht oeffnen: {grid_shape_path}")
    layer = shp_ds.GetLayer()

    field_idx = layer.GetLayerDefn().GetFieldIndex(name_field)
    if field_idx < 0:
        fields = [layer.GetLayerDefn().GetFieldDefn(i).GetName()
                  for i in range(layer.GetLayerDefn().GetFieldCount())]
        raise ValueError(
            f"Grid-Shape enthaelt kein Feld '{name_field}' - vorhandene Felder: {fields}"
        )

    # Grid-Shape auf EPSG:2056 pruefen und bei Bedarf on-the-fly reprojizieren
    target_srs = osr.SpatialReference()
    target_srs.ImportFromEPSG(2056)
    target_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)

    src_layer_srs = layer.GetSpatialRef()
    transform = None
    if src_layer_srs is None:
        _log(f"  WARNUNG       : Grid-Shape hat kein Koordinatensystem gesetzt - wird als EPSG:2056 angenommen.")
    elif not src_layer_srs.IsSame(target_srs):
        src_layer_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        transform = osr.CoordinateTransformation(src_layer_srs, target_srs)
        _log(f"  Grid-Shape CRS : {src_layer_srs.GetName()} -> wird nach EPSG:2056 reprojiziert")
    else:
        _log("  Grid-Shape CRS : EPSG:2056 (passend)")

    # Quell-Extent fuer Ueberlapp-Pruefung/Vorfilterung je Kachel
    gt = src_ds.GetGeoTransform()
    rx, ry  = src_ds.RasterXSize, src_ds.RasterYSize
    src_minx = gt[0]
    src_maxx = gt[0] + rx * gt[1]
    src_maxy = gt[3]
    src_miny = gt[3] + ry * gt[5]

    # Raeumlicher Vorfilter: bei grossen Grid-Shapes (z.B. gesamte Schweiz in 1km2-Kacheln,
    # zehntausende Features) werden so nur die mit dem Quellraster ueberlappenden Features
    # durchlaufen, statt in Python jedes einzelne Feature des gesamten Shapes zu pruefen.
    if transform is not None:
        inv_transform = osr.CoordinateTransformation(target_srs, src_layer_srs)
        xs, ys = [], []
        for cx, cy in ((src_minx, src_miny), (src_minx, src_maxy),
                       (src_maxx, src_miny), (src_maxx, src_maxy)):
            px, py, _ = inv_transform.TransformPoint(cx, cy)
            xs.append(px)
            ys.append(py)
        layer.SetSpatialFilterRect(min(xs), min(ys), max(xs), max(ys))
    else:
        layer.SetSpatialFilterRect(src_minx, src_miny, src_maxx, src_maxy)

    layer.ResetReading()
    total = layer.GetFeatureCount()
    _log(f"\nGefundene Grid-Kacheln (ueberlappend mit Quellraster): {total}")
    _log("Kompression        : " + compress +
         (f" (JPEG_QUALITY={quality})" if compress.upper() == "JPEG" else ""))
    _log(f"Kachelgroesse       : {blocksize}")
    _log("Koordinatensys.     : EPSG:2056")
    if prefix or suffix:
        _log(f"Praefix/Suffix      : '{prefix}' / '{suffix}'")

    written      = 0
    skipped      = 0
    empty_deleted = 0
    for i, feature in enumerate(layer, 1):
        name_val = feature.GetField(name_field)
        if name_val is None or str(name_val).strip() == "":
            _log(f"  [{i}/{total}] UEBERSPRUNGEN - Feld '{name_field}' ist leer.")
            skipped += 1
            continue
        tile_name = f"{prefix}{str(name_val).strip()}{suffix}.tif"

        geom = feature.GetGeometryRef()
        if geom is None:
            _log(f"  [{i}/{total}] UEBERSPRUNGEN ({tile_name}) - keine Geometrie.")
            skipped += 1
            continue
        geom = geom.Clone()
        if transform is not None:
            geom.Transform(transform)

        minx, maxx, miny, maxy = geom.GetEnvelope()

        if maxx <= src_minx or minx >= src_maxx or maxy <= src_miny or miny >= src_maxy:
            _log(f"  [{i}/{total}] UEBERSPRUNGEN ({tile_name}) - ausserhalb des Quellraster-Extents.")
            skipped += 1
            continue

        out_path = str(Path(output_dir) / tile_name)
        translate_options = gdal.TranslateOptions(
            format="GTiff",
            outputSRS="EPSG:2056",
            projWin=[minx, maxy, maxx, miny],
            creationOptions=creation_options,
        )
        out_ds = gdal.Translate(out_path, src_ds, options=translate_options)
        if out_ds is None:
            _log(f"  [{i}/{total}] FEHLER beim Schreiben von {tile_name}")
            skipped += 1
            continue
        out_ds.FlushCache()

        if _tile_is_empty(out_ds):
            out_ds = None
            _delete_tile_files(out_path)
            empty_deleted += 1
            print(f"PROGRESS:{i/total:.6f}", flush=True)
            _log(f"  [{i}/{total}] {tile_name} - GELOESCHT (100% NoData/Hintergrund)")
            continue

        out_ds = None
        written += 1

        print(f"PROGRESS:{i/total:.6f}", flush=True)
        _log(f"  [{i}/{total}] {tile_name}")

    src_ds = None
    shp_ds = None

    _log(f"\nFertig. {written} Kachel(n) geschrieben, {skipped} uebersprungen, "
         f"{empty_deleted} leere Kachel(n) (100% NoData) nachtraeglich geloescht.")
    if written == 0:
        raise RuntimeError(
            "Keine Kachel wurde geschrieben - Grid-Shape und Quellraster pruefen (Extent/Feld 'NAME')."
        )


def main() -> None:
    if len(sys.argv) < 2:
        print("[FEHLER] Kein Konfigurationspfad uebergeben.", flush=True)
        sys.exit(1)

    with open(sys.argv[1], encoding="utf-8") as f:
        cfg = json.load(f)

    action = cfg.get("action", "")

    # Interne Maske statt .msk-Begleitdatei bei allen TIFF/COG-Schreibvorgaengen
    from osgeo import gdal
    gdal.SetConfigOption("GDAL_TIFF_INTERNAL_MASK", "YES")

    try:
        if action == "info":
            _info(cfg)
        elif action == "convert":
            _convert(cfg)
        elif action == "mosaic":
            _mosaic(cfg)
        elif action == "to_bigtiff":
            _to_bigtiff(cfg)
        else:
            print(f"[FEHLER] Unbekannte Aktion: '{action}'", flush=True)
            sys.exit(1)

    except Exception as e:
        print(f"\n[FEHLER] {e}", flush=True)
        print(traceback.format_exc(), flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
