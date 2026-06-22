# COGTIFF Band-Konverter — 4-Band → 3-Band

Konvertiert Cloud-Optimized GeoTIFFs (COG) mit beliebiger Bandanzahl in ein neues 3-Band-COG mit frei konfigurierbarem Band-Mapping.

Typische Anwendungsfälle mit swisstopo-Luftbildern (DOP):

| Quelle | Ausgabe | Bandauswahl |
|--------|---------|-------------|
| RGBN (B1=R, B2=G, B3=B, B4=N) | RGB | `1, 2, 3` |
| RGBN (B1=R, B2=G, B3=B, B4=N) | NRG (CIR) | `4, 1, 2` |
| NRGB (B1=N, B2=R, B3=G, B4=B) | RGB | `2, 3, 4` |
| NRGB (B1=N, B2=R, B3=G, B4=B) | NRG (CIR) | `1, 2, 3` |

---

## Dateien

| Datei | Beschreibung |
|-------|-------------|
| `GUI_cogtiff_4band_to_3band.py` | Tkinter-GUI — startet mit Standard-Python |
| `_osgeo_runner.py` | GDAL-Worker — wird intern via OSGeo4W Python als Subprocess gestartet |
| `convertDATA_cogtiff_4band_to_3band.py` | Standalone-Script für die Kommandozeile (erfordert OSGeo4W Python direkt) |

---

## Voraussetzungen

- **GUI:** Python 3.x (Standard-Installation, nur `tkinter` benötigt)
- **GDAL-Verarbeitung:** [OSGeo4W](https://trac.osgeo.org/osgeo4w/) oder QGIS-Installation mit `python3.exe` und `osgeo`-Paket
  - Standardpfad: `C:\OSGeo4W\bin\python3.exe`
  - GDAL >= 3.1 (COG-Driver erforderlich)

---

## GUI starten

```bash
python GUI_cogtiff_4band_to_3band.py
```

Beim ersten Start erkennt das GUI automatisch die OSGeo4W-Installation. Der Pfad kann über die Schaltfläche **Ändern…** manuell gesetzt und wird in `_cogtiff_config.json` gespeichert.

![GUI Screenshot — Dark Mode](docs/screenshot_dark.png)

---

## Bedienung

1. **Input-Datei** auswählen (4-Band COG-TIFF oder GeoTIFF)
2. **Output-Datei** festlegen (wird automatisch vorgeschlagen)
3. **Datei-Info** liest Bandanzahl, ColorInterp, Auflösung, CRS und NoData automatisch aus
4. **Band-Konfiguration** über Schnellauswahl-Preset oder manuelle Eingabe
5. **COG-Optionen** anpassen (Kompression, Kachelgrösse, Overviews, Resampling, NoData)
6. **KONVERTIEREN** starten

---

## COG-Optionen

| Option | Standard | Beschreibung |
|--------|----------|-------------|
| Kompression | `DEFLATE` | Verlustfreie Kompression mit Predictor=2 |
| Kachelgrösse | `256` | Interne Kachelgrösse in Pixel (256 oder 512) |
| Overviews | `AUTO` | Eingebettete Übersichtsebenen (COG-intern, keine .ovr-Datei) |
| OV-Resampling | `LANCZOS` | Interpolation für Overviews — LANCZOS empfohlen für Luftbilder |
| NoData | auto | Wird aus Quelldatei erkannt; bei Alpha-Band automatisch auf 0 gesetzt |

> **Hinweis Kachelgrösse:** 256 ist der Standard für DOP-Publikation (z.B. STAC, WMTS). 512 bietet bessere Kompressionsrate bei weniger HTTP-Requests, ist aber weniger kompatibel mit Standard-Tile-Clients.

> **Hinweis Overviews:** Bei COG sind Overviews intern eingebettet — es entsteht keine separate `.ovr`-Datei. `LANCZOS`-Resampling liefert die schärfsten Ergebnisse für RGB-Luftbilder.

---

## Log-Ausgabe

Jede Konvertierung schreibt automatisch eine Logdatei in den Unterordner `logs/`:

```
logs/
└── dateiname_RGB_2025-06-22_143022.log
```

Der Ordner wird beim ersten Start automatisch erstellt.

---

## Koordinatensystem

Das Koordinatensystem wird aus der Quelldatei übernommen und unverändert in die Ausgabedatei geschrieben. Für swisstopo-Daten: **EPSG:2056** (LV95 / LHN95).

---

## Standalone-Script (ohne GUI)

Für Batch-Verarbeitung kann `convertDATA_cogtiff_4band_to_3band.py` direkt mit OSGeo4W Python ausgeführt werden:

```bash
C:\OSGeo4W\bin\python3.exe convertDATA_cogtiff_4band_to_3band.py
```

Konfiguration direkt im Script-Kopf anpassen (`INPUT_PATH`, `OUTPUT_PATH`, `OUTPUT_BANDS`).

---

## Architektur

```
GUI_cogtiff_4band_to_3band.py   (Standard-Python, tkinter)
        │
        │  JSON-Config (tempfile)
        ▼
_osgeo_runner.py                (OSGeo4W Python, GDAL)
        │
        │  stdout → live ins GUI-Log + Logdatei
        ▼
    logs/*.log
```

Die Trennung ermöglicht es, das GUI mit jeder Standard-Python-Installation zu starten, ohne OSGeo4W-Abhängigkeiten im GUI-Prozess.
