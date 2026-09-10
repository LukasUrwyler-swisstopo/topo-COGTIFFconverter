# COGTIFF Werkzeuge

Drei GDAL-Werkzeuge rund um Cloud-Optimized GeoTIFFs (COG), als Tabs im selben GUI:

- **COGTIFF erstellen** — mosaikiert gekachelte `.tif`/`.tfw`-Dateien (z.B. 1km²-Kacheln) per VRT zu einem einzigen COGTIFF, optional mit Band-Mapping und Bit-Tiefe-Konvertierung.
- **COGTIFF to TIFF** — konvertiert ein COGTIFF zu klassischem (Big)TIFF + `.tfw`-Weltdatei: entweder als einzelne Datei, oder als Kachel-Set gemaess Grid-Shape (Dateiname je Kachel aus Attributfeld `NAME`).
- **change BANDS** — konvertiert ein COG/GeoTIFF mit beliebiger Bandanzahl in ein neues COG mit frei konfigurierbarem Band-Mapping.

## GUI

Eingabe im cmd-Terminal:
```bash
python pfad/GUI_cogtiffConverter.py
```
<img width="635" height="691" alt="image" src="https://github.com/user-attachments/assets/eb0ba387-4f68-4db9-9311-63d8c42892bc" />


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
| `GUI_cogtiffConverter.py` | Tkinter-GUI — startet mit Standard-Python |
| `process_scripts/_osgeo_runner.py` | GDAL-Worker — wird intern via OSGeo4W Python als Subprocess gestartet |
| `process_scripts/02_convertDATA_cogtiff_4band_to_3band.py` | Standalone-Script für die Kommandozeile (erfordert OSGeo4W Python direkt) |
| `process_scripts/_cogtiff_config.json` | GUI-Konfiguration (OSGeo4W-Python-Pfad), wird automatisch angelegt |
| `test/test_functions.py` | Import-/Sanity-Checks (siehe [Tests](#tests)) |

---

## Voraussetzungen

- **GUI:** Python >= 3.6 (Standard-Installation, nur `tkinter` benötigt). Bewusst kompatibel mit 3.6 gehalten (z.B. `tk.Spinbox` statt `ttk.Spinbox`, das erst ab 3.7 existiert) — Firmen-Standard-Python ist 3.6.
- **GDAL-Verarbeitung:** [OSGeo4W](https://trac.osgeo.org/osgeo4w/) oder QGIS-Installation mit `python3.exe` und `osgeo`-Paket
  - Standardpfad: `C:\OSGeo4W\bin\python3.exe`
  - GDAL >= 3.1 (COG-Driver erforderlich)

---

## GUI starten

```bash
python GUI_cogtiffConverter.py
```

Beim ersten Start erkennt das GUI automatisch die OSGeo4W-Installation. Der Pfad kann über die Schaltfläche **Ändern…** manuell gesetzt und wird in `process_scripts/_cogtiff_config.json` gespeichert.


---

## Bedienung — Tab "Baender aendern"

1. **Input-Datei** auswählen (4-Band COG-TIFF oder GeoTIFF — dieser Tab erwartet immer 4 Bänder)
2. **Output-Datei** festlegen (wird automatisch vorgeschlagen)
3. **Datei-Info** liest Bandanzahl, ColorInterp, Auflösung, CRS und NoData automatisch aus; erkennt
   das Tool einen echten Alpha-Kanal (ColorInterp=Alpha), wird **"4. Kanal ist"** automatisch auf
   `Alpha` vorgewählt
4. **Band-Konfiguration** über Schnellauswahl-Preset oder manuelle Eingabe
5. **4. Kanal ist** — steuert, wie aus dem 4. Band eine Transparenz-Maske wird (siehe
   [Masken-Logik](#masken-logik-4-kanal-nir-oder-alpha) unten):
   - `NIR` (Standard) — Bänder frei wähl-/umsortierbar, Maske aus NoData-Dropdown berechnet
   - `Alpha` — Ausgabe automatisch auf die 3 Nicht-Alpha-Bänder fixiert, Maske direkt aus dem
     Alpha-Band übernommen
6. **COG-Optionen** anpassen (Kompression, Kachelgrösse, Overviews, Resampling, ggf. NoData-Wert der Maske)
7. **KONVERTIEREN** starten

---

## Masken-Logik (4. Kanal: NIR oder Alpha)

Der Tab "Baender aendern" erwartet immer einen 4-Band-Input. Was mit dem 4. Band passiert, hängt
vom Dropdown **"4. Kanal ist"** ab — in beiden Fällen entsteht eine **echte interne COG-Maske**
(GDAL `GMF_PER_DATASET`, kein separates `.msk`-File, keine reine NoData-Metadaten-Angabe):

| Modus | Ausgabebänder | Maskenquelle |
|-------|---------------|--------------|
| `Alpha` | automatisch auf die 3 Nicht-Alpha-Bänder fixiert (Eingabefeld gesperrt) | 1:1 aus dem Alpha-Band übernommen (`gdal_translate -mask <Band>`-Äquivalent) |
| `NIR` (Standard) | frei wähl-/umsortierbar wie gehabt (Presets, manuelle Eingabe) | berechnet aus dem NoData-Dropdown (`0`/`255`): ein Pixel gilt nur dann als **ungültig**, wenn **alle** gewählten Ausgabebänder diesem Wert entsprechen (AND-Logik) |

**Warum AND-Logik im NIR-Fall:** Verhindert, dass z.B. ein einzelner rein schwarzer Farbkanal
(ohne dass es sich um echten Bildrand handelt) fälschlich als NoData maskiert wird — typische
Bildränder bei swisstopo-Orthofotos sind in **allen** Kanälen gleichzeitig `0` bzw. `255`.

**Technisch:** Im `NIR`-Modus wird der NoData-Wert **nicht** als Datei-Metadatum geschrieben,
sondern ausschliesslich zur Maskenberechnung verwendet — GDAL verwirft sonst bei gleichzeitig
gesetztem `noData` und einer eigenen Maske eine der beiden ("conflicting mask sources"). Die
COG-Overviews werden aus derselben Maske automatisch mit heruntergerechnet.

**Im Tab "COGTIFF erstellen" (Mosaik)** gilt dieselbe Logik, nur ueber das Dropdown
**"NoData-Wert (Input)"** gesteuert statt ueber "4. Kanal ist":

| Auswahl | Ausgabebänder | Maskenquelle |
|---------|---------------|--------------|
| `Alpha-Kanal (interne Maske)` — erscheint/wird automatisch vorgewaehlt, sobald ein Alpha-Band erkannt wurde | frei wähl-/umsortierbar (Presets, manuelle Eingabe); ohne explizite Auswahl automatisch alle Nicht-Alpha-Bänder | 1:1 aus dem Alpha-Band übernommen, unabhängig von der Zahl der gemosaikten Kacheln |
| Wertbasierte Presets (`0 0 0` usw.) | frei wähl-/umsortierbar | berechnet aus dem gewählten NoData-Wert (AND-Logik über alle Ausgabebänder), blockweise über das gesamte Mosaik |

Wird **`Alpha-Kanal`** gewählt und das Alpha-Band trotzdem explizit in "Ausgabebänder" mit
aufgeführt, bricht die Konvertierung mit einer Fehlermeldung ab (das Alpha-Band kann nicht
gleichzeitig Datenband und Maskenquelle sein). Auch hier wird — aus demselben Grund
("conflicting mask sources") — bewusst **kein** zusätzlicher NoData-Tag geschrieben.

---

## Bedienung — Tab "COGTIFF erstellen" (Mosaik aus Kacheln)

Mosaikiert gekachelte `.tif`/`.tfw`-Dateien (z.B. 1km²-Kacheln, keine eingebettete CRS-Info) per VRT
zu einem einzigen COGTIFF. Entspricht der Pipeline `gdalbuildvrt` → `gdal_translate -of COG`.

1. **Input-Ordner** waehlen (enthaelt die `.tif`/`.tfw`-Kacheln)
2. **Output-Ordner** waehlen — das COGTIFF wird direkt hier abgelegt, die VRT-Zwischendatei im
   automatisch angelegten Unterordner `vrt/`
3. **Ausgabedateiname** angeben (ohne Endung)
4. **Band-Konfiguration** (optional) — wie im Tab "Baender aendern": Schnellauswahl-Preset oder
   manuelle Eingabe von Input-Bandbezeichnungen und Ausgabebaendern (z.B. `RGBN → RGB`).
   Leer gelassen = alle Baender unveraendert.
5. **Bit-Tiefe (Output)** waehlen: `(unveraendert)`, `8bit` oder `16bit`. Die Quell-Bit-Tiefe wird
   automatisch erkannt; bei Konvertierung wird linear skaliert (8bit ↔ 16bit).
6. **NoData-Wert** waehlen — die Vorschlaege richten sich nach der gewaehlten Ziel-Bit-Tiefe:
   8bit → `0 0 0` / `255 255 255`; 16bit → `0 0 0 0` / `65535 65535 65535`;
   gilt gemeinsam fuer `-srcnodata`, `-vrtnodata` und `-a_nodata`.
   Erkennt die **Datei-Info** in der Muster-Kachel einen echten Alpha-Kanal (ColorInterp=Alpha,
   i.d.R. Band 4), erscheint zusaetzlich die Option **`Alpha-Kanal (interne Maske)`** und wird
   automatisch vorgewaehlt — siehe [Masken-Logik](#masken-logik-4-kanal-nir-oder-alpha) unten.
7. **COG-Optionen** anpassen (Kompression inkl. JPEG mit Qualitaets-Regler, Kachelgrösse, Overviews, Resampling)
8. **COGTIFF ERSTELLEN** starten

> **Koordinatensystem:** wird beim Mosaik-Tab fest auf **EPSG:2056** (LV95) gesetzt, da Kachel-TIFFs
> mit `.tfw`-Begleitdatei i.d.R. keine CRS-Information eingebettet haben.

---

## Bedienung — Tab "cogtiff to TIFF"

Konvertiert ein COGTIFF zu klassischem (Big)TIFF + `.tfw`-Weltdatei (kein Cloud-Optimized-Layout).
Zwei Modi zur Auswahl:

- **BigTIFF (einzelne Datei)** — das gesamte Raster als eine Ausgabedatei. `BIGTIFF=IF_SAFER`:
  GDAL wechselt nur bei Bedarf (Datei nahe der 4GB-Grenze) automatisch ins BigTIFF-Format.
- **Tiled-TIFF (Kacheln via Grid-Shape)** — schneidet das Raster anhand eines Grid-Shapes
  (Bounding-Box je Feature) in einzelne Kachel-Dateien:
  1. **Grid-Shape (.shp)** waehlen — Attributfeld **`NAME`** liefert den Dateinamen je Kachel
     (`<Praefix><NAME><Suffix>.tif`, Praefix/Suffix optional)
  2. Das Shape wird bei Bedarf automatisch nach **EPSG:2056** reprojiziert (CRS-Pruefung anhand
     des Shape-eigenen `.prj`)
  3. Ein raeumlicher Vorfilter (`SetSpatialFilterRect`) sorgt dafuer, dass bei grossen Grids
     (z.B. gesamte Schweiz in 1km²-Kacheln, zehntausende Features) nur die tatsaechlich mit dem
     Quellraster ueberlappenden Kacheln verarbeitet werden — die geografische Kachelgroesse kommt
     dabei vollstaendig aus der Geometrie des Grid-Shapes, nicht aus einer GUI-Einstellung
  4. Kacheln ohne Ueberlappung zum Quellraster werden uebersprungen, nicht als Fehler behandelt
  5. Kacheln, die nach dem Zuschnitt zu **100% aus einem konstanten Wert** bestehen (reine
     Hintergrund-/NoData-Flaeche ausserhalb der eigentlichen Bildkontur, z.B. bei unregelmaessig
     geformten Befliegungsgebieten innerhalb eines rechteckigen Grids), werden automatisch wieder
     geloescht (`.tif` + `.tfw` + ggf. `.aux.xml`) — die Anzahl erscheint am Ende im Log

**Fixparameter:** Output-Koordinatensystem stets **EPSG:2056** (CH1901+ LV95).

**TIFF-Optionen:**

| Option | Standard | Beschreibung |
|--------|----------|-------------|
| Kompression | `NONE` | `NONE`/`DEFLATE`/`LZW`/`ZSTD`/`JPEG` |
| JPEG-Qualitaet | `90` | Nur relevant bei Kompression=JPEG |
| TIFF-Blockgroesse (intern) | `256` | Interne Pixel-Bloecke fuer performantes Lesen (256/512/1024) — **nicht** die geografische Kachelgroesse der Ausgabedateien |

---

## COG-Optionen

| Option | Standard | Beschreibung |
|--------|----------|-------------|
| Kompression | `DEFLATE` (Baender-Tab) / `JPEG` (Mosaik-Tab) | `DEFLATE`/`LZW`/`ZSTD` = verlustfrei mit Predictor=2; `JPEG` = verlustbehaftet mit Qualitaets-Regler; `NONE` = unkomprimiert |
| JPEG-Qualitaet | `90` (Baender-Tab) / `95` (Mosaik-Tab) | Nur relevant bei Kompression=JPEG, Bereich 60–100 |
| Kachelgrösse | `256` | Interne Kachelgrösse in Pixel (256, 512 oder 1024) |
| Overviews | `AUTO` | Eingebettete Übersichtsebenen (COG-intern, keine .ovr-Datei) |
| OV-Resampling | `AVERAGE` (beide Tabs) | Interpolation für Overviews — im Dropdown umstellbar, u.a. auf `LANCZOS` (schärfer, für Einzel-Luftbilder) |
| NoData (Maske) | Baender-Tab: `0` (nur bei "4. Kanal ist"=`NIR`) — Mosaik-Tab: bitentiefenabhaengiges Preset bzw. `Alpha-Kanal` falls erkannt | Steuert ausschliesslich die Masken-Berechnung (siehe [Masken-Logik](#masken-logik-4-kanal-nir-oder-alpha)), wird nie als Datei-NoData-Tag geschrieben |
| BIGTIFF | `YES` | Erzwingt BigTIFF-Format, unabhaengig von der Dateigroesse — vermeidet die 4GB-Grenze klassischer TIFFs bei grossen Orthofotos/Mosaiken |
| NUM_THREADS | `ALL_CPUS` | Parallele Kompression ueber alle verfuegbaren CPU-Kerne |
| ADD_ALPHA | `NO` | GDAL-COG-Option, relevant nur bei Reprojektion (die dieses Tool nicht durchfuehrt) — aktuell ohne Wirkung, sicherheitshalber gesetzt |
| GDAL_TIFF_INTERNAL_MASK | `YES` (global, nicht pro Tab einstellbar) | Erzwingt interne Maskenspeicherung statt `.msk`-Begleitdatei; bei COG ohnehin Standardverhalten |

> **Hinweis Kachelgrösse:** 256 ist der Standard für DOP-Publikation (z.B. STAC, WMTS). 512/1024 bieten bessere Kompressionsrate bei weniger HTTP-Requests, sind aber weniger kompatibel mit Standard-Tile-Clients.

> **Hinweis Overviews:** Bei COG sind Overviews intern eingebettet — es entsteht keine separate `.ovr`-Datei. `LANCZOS`-Resampling liefert schärfere Ergebnisse für RGB-Einzel-Luftbilder, `AVERAGE` ist glaetter/robuster gegen Kachel-Naehte bei Mosaiken.

---

## Log-Ausgabe

Jede Konvertierung schreibt automatisch eine Logdatei in den Unterordner `logs/`:

```
logs/
└── dateiname_RGB_2025-06-22_143022.log
```

Der Ordner wird beim ersten Start automatisch erstellt.

Nach Abschluss eines Vorgangs (in allen drei Tabs) erscheint zusaetzlich ein Info-Fenster mit OK-Button,
das Erfolg oder Fehlschlag bestaetigt — Details dazu stehen im Log.

---

## Koordinatensystem

- **Baender aendern:** Das Koordinatensystem wird aus der Quelldatei übernommen und unverändert in die Ausgabedatei geschrieben.
- **COGTIFF erstellen (Mosaik):** Wird fest auf **EPSG:2056** (LV95) gesetzt, da Kachel-TIFFs mit `.tfw`-Begleitdatei i.d.R. keine CRS-Information eingebettet haben.
- **cogtiff to TIFF:** Wird fest auf **EPSG:2056** (LV95) gesetzt; ein optionales Grid-Shape (Tiled-TIFF-Modus) wird bei abweichendem CRS automatisch reprojiziert.

Für swisstopo-Daten massgebend: **EPSG:2056** (LV95 / LHN95).

---

## Standalone-Script (ohne GUI)

Für Batch-Verarbeitung kann `process_scripts/02_convertDATA_cogtiff_4band_to_3band.py` direkt mit OSGeo4W Python ausgeführt werden:

```bash
C:\OSGeo4W\bin\python3.exe process_scripts\02_convertDATA_cogtiff_4band_to_3band.py
```

Konfiguration direkt im Script-Kopf anpassen (`INPUT_PATH`, `OUTPUT_PATH`, `OUTPUT_BANDS`).

---

## Architektur

```
GUI_cogtiffConverter.py            (Standard-Python, tkinter)
        │
        │  JSON-Config (tempfile)
        ▼
process_scripts/_osgeo_runner.py   (OSGeo4W Python, GDAL)
    Aktionen: info / convert / mosaic / to_bigtiff
        │
        │  stdout → live ins GUI-Log + Logdatei
        ▼
    logs/*.log
```

Die Trennung ermöglicht es, das GUI mit jeder Standard-Python-Installation zu starten, ohne OSGeo4W-Abhängigkeiten im GUI-Prozess.

---

## Tests

Eine kleine, non-invasive Testdatei `test/test_functions.py` führt einfache Import-/Sanity-Checks durch (keine GDAL-Operationen).

Tests ausführen:

```bash
python -m pytest -q
```

Die Tests sind bewusst leichtgewichtig, damit sie auch in Umgebungen ohne OSGeo4W schnell laufen.
