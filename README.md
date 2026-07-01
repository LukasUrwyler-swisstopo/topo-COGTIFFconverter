# COGTIFF Werkzeuge

Zwei GDAL-Werkzeuge fuer Cloud-Optimized GeoTIFFs (COG), als Tabs im selben GUI:

- **COGTIFF erstellen** — mosaikiert gekachelte `.tif`/`.tfw`-Dateien (z.B. 1km²-Kacheln) per VRT zu einem einzigen COGTIFF.
- **Baender aendern** — konvertiert ein COG/GeoTIFF mit beliebiger Bandanzahl in ein neues COG mit frei konfigurierbarem Band-Mapping.

## GUI

```bash
python 01_GUI_cogtiff_4band_to_3band.py
```
<img width="1219" height="1363" alt="grafik" src="https://github.com/user-attachments/assets/a644bfba-4752-4737-9ced-3a938701f7c6" />


Typische Anwendungsfälle mit swisstopo-Luftbildern (DOP) fuer die Band-Konvertierung:

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
| `01_GUI_cogtiff_4band_to_3band.py` | Tkinter-GUI — startet mit Standard-Python |
| `_osgeo_runner.py` | GDAL-Worker — wird intern via OSGeo4W Python als Subprocess gestartet |
| `02_convertDATA_cogtiff_4band_to_3band.py` | Standalone-Script für die Kommandozeile (erfordert OSGeo4W Python direkt) |

---

## Voraussetzungen

- **GUI:** Python >= 3.6 (Standard-Installation, nur `tkinter` benötigt). Bewusst kompatibel mit 3.6 gehalten (z.B. `tk.Spinbox` statt `ttk.Spinbox`, das erst ab 3.7 existiert) — Firmen-Standard-Python ist 3.6.
- **GDAL-Verarbeitung:** [OSGeo4W](https://trac.osgeo.org/osgeo4w/) oder QGIS-Installation mit `python3.exe` und `osgeo`-Paket
  - Standardpfad: `C:\OSGeo4W\bin\python3.exe`
  - GDAL >= 3.1 (COG-Driver erforderlich)

---

## GUI starten

```bash
python 01_GUI_cogtiff_4band_to_3band.py
```

Beim ersten Start erkennt das GUI automatisch die OSGeo4W-Installation. Der Pfad kann über die Schaltfläche **Ändern…** manuell gesetzt und wird in `_cogtiff_config.json` gespeichert.


---

## Bedienung — Tab "Baender aendern"

1. **Input-Datei** auswählen (4-Band COG-TIFF oder GeoTIFF)
2. **Output-Datei** festlegen (wird automatisch vorgeschlagen)
3. **Datei-Info** liest Bandanzahl, ColorInterp, Auflösung, CRS und NoData automatisch aus
4. **Band-Konfiguration** über Schnellauswahl-Preset oder manuelle Eingabe
5. **COG-Optionen** anpassen (Kompression, Kachelgrösse, Overviews, Resampling, NoData)
6. **KONVERTIEREN** starten

---

## Bedienung — Tab "COGTIFF erstellen" (Mosaik aus Kacheln)

Mosaikiert gekachelte `.tif`/`.tfw`-Dateien (z.B. 1km²-Kacheln, keine eingebettete CRS-Info) per VRT
zu einem einzigen COGTIFF. Entspricht der Pipeline `gdalbuildvrt` → `gdal_translate -of COG`.

1. **Input-Ordner** waehlen (enthaelt die `.tif`/`.tfw`-Kacheln)
2. **Output-Ordner** waehlen — das COGTIFF wird direkt hier abgelegt, die VRT-Zwischendatei im
   automatisch angelegten Unterordner `vrt/`
3. **Ausgabedateiname** angeben (ohne Endung)
4. **Bit-Tiefe** des Inputs waehlen (8bit/16bit) — steuert die passenden NoData-Vorschlaege
5. **NoData-Wert** waehlen: 8bit → `0 0 0` / `255 255 255`; 16bit → `0 0 0 0` / `65535 65535 65535`;
   gilt gemeinsam fuer `-srcnodata`, `-vrtnodata` und `-a_nodata`
6. **COG-Optionen** anpassen (Kompression inkl. JPEG mit Qualitaets-Regler, Kachelgrösse, Overviews, Resampling)
7. **COGTIFF ERSTELLEN** starten

> **Koordinatensystem:** wird beim Mosaik-Tab fest auf **EPSG:2056** (LV95) gesetzt, da Kachel-TIFFs
> mit `.tfw`-Begleitdatei i.d.R. keine CRS-Information eingebettet haben.

---

## COG-Optionen

| Option | Standard | Beschreibung |
|--------|----------|-------------|
| Kompression | `DEFLATE` (Baender-Tab) / `JPEG` (Mosaik-Tab) | `DEFLATE`/`LZW`/`ZSTD` = verlustfrei mit Predictor=2; `JPEG` = verlustbehaftet mit Qualitaets-Regler; `NONE` = unkomprimiert |
| JPEG-Qualitaet | `90` (Baender-Tab) / `95` (Mosaik-Tab) | Nur relevant bei Kompression=JPEG, Bereich 60–100 |
| Kachelgrösse | `256` | Interne Kachelgrösse in Pixel (256, 512 oder 1024) |
| Overviews | `AUTO` | Eingebettete Übersichtsebenen (COG-intern, keine .ovr-Datei) |
| OV-Resampling | `LANCZOS` (Baender-Tab) / `AVERAGE` (Mosaik-Tab) | Interpolation für Overviews — LANCZOS empfohlen für Einzel-Luftbilder, AVERAGE fuer Mosaike |
| NoData | auto (Baender-Tab) / Dropdown nach Bit-Tiefe (Mosaik-Tab) | Baender-Tab: aus Quelldatei erkannt, bei Alpha-Band automatisch auf 0 gesetzt |

> **Hinweis Kachelgrösse:** 256 ist der Standard für DOP-Publikation (z.B. STAC, WMTS). 512/1024 bieten bessere Kompressionsrate bei weniger HTTP-Requests, sind aber weniger kompatibel mit Standard-Tile-Clients.

> **Hinweis Overviews:** Bei COG sind Overviews intern eingebettet — es entsteht keine separate `.ovr`-Datei. `LANCZOS`-Resampling liefert die schärfsten Ergebnisse für RGB-Luftbilder, `AVERAGE` ist fuer Mosaike glaetter/robuster gegen Kachel-Naehte.

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

- **Baender aendern:** Das Koordinatensystem wird aus der Quelldatei übernommen und unverändert in die Ausgabedatei geschrieben.
- **COGTIFF erstellen (Mosaik):** Wird fest auf **EPSG:2056** (LV95) gesetzt, da Kachel-TIFFs mit `.tfw`-Begleitdatei i.d.R. keine CRS-Information eingebettet haben.

Für swisstopo-Daten massgebend: **EPSG:2056** (LV95 / LHN95).

---

## Standalone-Script (ohne GUI)

Für Batch-Verarbeitung kann `02_convertDATA_cogtiff_4band_to_3band.py` direkt mit OSGeo4W Python ausgeführt werden:

```bash
C:\OSGeo4W\bin\python3.exe 02_convertDATA_cogtiff_4band_to_3band.py
```

Konfiguration direkt im Script-Kopf anpassen (`INPUT_PATH`, `OUTPUT_PATH`, `OUTPUT_BANDS`).

---

## Architektur

```
01_GUI_cogtiff_4band_to_3band.py   (Standard-Python, tkinter)
        │
        │  JSON-Config (tempfile)
        ▼
_osgeo_runner.py                (OSGeo4W Python, GDAL)
    Aktionen: info / convert / mosaic
        │
        │  stdout → live ins GUI-Log + Logdatei
        ▼
    logs/*.log
```

Die Trennung ermöglicht es, das GUI mit jeder Standard-Python-Installation zu starten, ohne OSGeo4W-Abhängigkeiten im GUI-Prozess.

---

## Tests

Eine kleine, non-invasive Testdatei `test_functions.py` liegt im Projekt-Root und führt einfache Import-/Sanity-Checks durch (keine GDAL-Operationen).

Tests ausführen:

```bash
python -m pytest -q
```

Die Tests sind bewusst leichtgewichtig, damit sie auch in Umgebungen ohne OSGeo4W schnell laufen.
