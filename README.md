# Mediaspace-Report

Erstellt aus nächtlichen Snapshots monatliche Excel-Berichte zur Speicherbelegung der Media Spaces je Projekt. Jeder Lauf schreibt den Bericht des laufenden Monats fort, schließt am 01. den Vormonat ab, führt den LTO-Bestand für Looks-Projekte und bereinigt ältere Berichte. Läuft als EditShare-Flow-Automation-Skript auf dem Linux-Worker.

## Dateien auf dem Worker

```text
/var/flow/automation/scripts/
├── mediaspace_report_launcher.py      Launcher (Flow Automation oder --standalone)
└── mediaspace_report/
    ├── mediaspace_report.py           Hauptmodul
    ├── ms_source.py                   Abruf der Media Spaces (Admin-API)
    ├── ms_state.py                    Zustandsdatei und Snapshots
    ├── ms_excel.py                    Excel-Arbeitsmappe
    ├── requirements.txt               pip-Abhängigkeiten (nur für die Installation)
    ├── cred.env                       Zugangsdaten, manuell anlegen
    ├── mediaspace_state.json          legt das Skript an
    ├── mediaspace_report.log          legt das Skript an (rotiert: .log.1, .log.2)
    └── reports/                       legt das Skript an
        └── Mediaspace-Report_YYYY-MM.xlsx
```

Die Toolbox-Mini wird von diesem Paket nicht verwendet und muss nicht kopiert werden.

## Pakete

Python 3.10 oder neuer. Installiert werden muss in das `python3`, das der Launcher über `#!/usr/bin/env python3` startet:

| Paket | Zweck |
| --- | --- |
| `editshare-flow-api~=2026.2.1.0` | FlowAPI (Admin-API), aus dem EditShare-Paketindex |
| `python-dotenv` | liest `cred.env` |
| `openpyxl` | schreibt die Excel-Berichte |

## Installation (Linux)

Im ausgecheckten Repo ausführen. `<flow-user>` ist der Linux-Benutzer, unter dem Flow Automation die Skripte ausführt; er braucht Schreibrechte im Ordner `mediaspace_report/`.

```bash
chmod +x /var/flow/automation/scripts/mediaspace_report_launcher.pyy

python3 -m pip install -r "$base/mediaspace_report/requirements.txt"
python3 -c "from zoneinfo import ZoneInfo; ZoneInfo('Europe/Berlin')"
```

Alle Dateien müssen UNIX-Zeilenenden (LF) haben; der `sed`-Befehl entfernt eventuelle CR-Zeichen.

## Start

**Flow Automation:** Module **Time** und **Script Runner**, die `/var/flow/automation/scripts/mediaspace_report_launcher.py` aufrufen. Der Lauf muss täglich um **00:01 Uhr** starten.

**Manuell:**

```bash
/var/flow/automation/scripts/mediaspace_report_launcher.py --standalone
echo $?
```

Meldungen erscheinen auf der Konsole und im Log, im Flow-Betrieb im Job-Log. Ohne `--standalone` läuft der Launcher als AutomationScript, wenn `editshare_helpers` verfügbar ist, sonst im Standalone-Modus.

Exit-Codes: `0` = ok, `1` = Fehler (Details im Log), `130` = abgebrochen. Im Flow-Betrieb schlägt der Job bei einem Fehler fehl.

Ein manueller Lauf ersetzt den Snapshot des Vortags durch den aktuellen Wert.

## Config (Kopf von `mediaspace_report.py`)

| Eintrag | Standard | Bedeutung |
| --- | --- | --- |
| `app_name` | `mediaspace_report` | Anwendungsname |
| `app_version` | `0.4.0` | Skriptversion |
| `unit_bytes` | `2**40` | Byte je TiB |
| `script_dir` | Ordner des Moduls | Basisordner (`mediaspace_report/`) |
| `cred_path` | `script_dir / "cred.env"` | Zugangsdaten |
| `state_path` | `script_dir / "mediaspace_state.json"` | Snapshot-Zustand |
| `log_path` | `script_dir / "mediaspace_report.log"` | Laufprotokoll, max. 1 MB, 2 Rotationen |
| `report_dir` | `script_dir / "reports"` | Berichtsordner |
| `api_timeout` | `120` | Zeitlimit für den Abruf in Sekunden |
| `keep_reports` | `24` | Zahl der zu behaltenden Monatsberichte |

## Hinweise

- `Mediaspace-Report_YYYY-MM.xlsx` enthält die Blätter `Bericht`, `Rohdaten` und `LTO-Bestand`. Alle Größenwerte sind in TiB.
- Der Bericht bleibt vorläufig bis zum Lauf am 01. des Folgemonats um 00:01 Uhr.
- Ein Snapshot um 00:01 Uhr gilt für den Vortag.
- Fehlt eine Nacht, zählt sie nicht; fehlen mehrere Nächte, wird interpoliert und der Wert markiert.
- Kann ein Bericht nicht geschrieben werden, bleibt der Monat im Zustand und der nächste Lauf schreibt ihn neu.
- Der LTO-Bestand umfasst nur Looks-Projekte und beginnt erst ab dem Start der Erfassung.
- Der erste Monat enthält nur Snapshots ab dem ersten Lauf.
