# Mediaspace-Report

## mediaspace_report.py

Das Skript erstellt aus nächtlichen Snapshots monatliche Excel-Berichte zur Speicherbelegung der Media Spaces je Projekt. Es schließt den Vormonat ab, führt den LTO-Bestand für Looks-Projekte und bereinigt ältere Berichte.

### Installation

Python 3.11 oder neuer.

```console
pip config set global.extra-index-url https://artifacts.editshare.com/artifactory/api/pypi/editshare-pypi-public/simple
pip install editshare-flow-api python-dotenv openpyxl tzdata
```

`cred.env` neben dem Skript anlegen und nicht committen:

```dotenv
FLOW_HOST=<host>
FLOW_USER=<user>
FLOW_PASSWORD=<password>
```

### Verwendung

```console
python mediaspace_report.py
```

Für den nächtlichen Lauf unter Windows in der Aufgabenplanung täglich um 00:01 Uhr einen Task anlegen, zum Beispiel:

```console
schtasks /Create /SC DAILY /ST 00:01 /TN "Mediaspace-Report" /TR "\"C:\Pfad\zu\python.exe\" \"C:\Pfad\zu\mediaspace_report.py\""
```

### Config (Kopf von `mediaspace_report.py`)

| Eintrag | Standard | Bedeutung |
| --- | --- | --- |
| `app_name` | `mediaspace_report` | Anwendungsname |
| `app_version` | `0.3.0` | Skriptversion |
| `unit_bytes` | `2**40` | Byte je TiB |
| `script_dir` | Ordner des Skripts | Basisordner |
| `cred_path` | `script_dir / "cred.env"` | Zugangsdaten |
| `state_path` | `script_dir / "mediaspace_state.json"` | Snapshot-Zustand |
| `log_path` | `script_dir / "mediaspace_report.log"` | Laufprotokoll |
| `report_dir` | `script_dir / "reports"` | Hier den festen Berichtsordner eintragen (Standard: reports neben dem Skript) |
| `api_timeout` | `120` | Zeitlimit für den Abruf in Sekunden |
| `keep_reports` | `24` | Zahl der zu behaltenden Monatsberichte |

### Dateien und Hinweise

- `reports/Mediaspace-Report_YYYY-MM.xlsx`: Monatsbericht mit den Blättern `Bericht`, `Rohdaten` und `LTO-Bestand`.
- `mediaspace_state.json`: gespeicherte Snapshots und LTO-Daten.
- `mediaspace_report.log`: Laufmeldungen.
- Alle Größenwerte sind in TiB.
- Der Bericht bleibt vorläufig bis zum Lauf am 01. des Folgemonats um 00:01 Uhr.
- Ein Snapshot um 00:01 Uhr gilt für den Vortag.
- Fehlt eine Nacht, zählt sie nicht; fehlen mehrere Nächte, wird interpoliert und der Wert markiert.
- Der LTO-Bestand umfasst nur Looks-Projekte und beginnt erst ab dem Start der Erfassung.
- Der erste Monat enthält nur Snapshots ab dem ersten Lauf.

## storage_probe.py

Das Skript ist ein nur lesendes Testskript für Storage-Abfragen. Aufruf: `python storage_probe.py`; die Ausgaben liegen in einem zeitgestempelten Unterordner von `probe_output/` neben dem Skript.

**Achtung:** `04_admin_get_mediaspaces.json` enthält Zugangsdaten der Spaces. Nach Gebrauch löschen und nicht weitergeben.
