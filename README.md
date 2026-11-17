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
    └── reports/                       nur ohne Destination Media Space, legt das Skript an

<Destination Media Space>/<Subdir>/  Berichtsordner im Flow-Betrieb, von Flow eingehängt
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

Im ausgecheckten Repo ausführen, ohne `sudo`. Voraussetzung: Schreibrechte in `/var/flow/automation/scripts`.

```bash
base=/var/flow/automation/scripts
mkdir -p "$base/mediaspace_report"
cp mediaspace_report_launcher.py "$base/"
cp mediaspace_report.py ms_source.py ms_state.py ms_excel.py requirements.txt "$base/mediaspace_report/"

cat > "$base/mediaspace_report/cred.env" <<'ENV'
FLOW_HOST=<host>
FLOW_USER=<user>
FLOW_PASSWORD=<password>
ENV

sed -i 's/\r$//' "$base/mediaspace_report_launcher.py" "$base"/mediaspace_report/*.py "$base/mediaspace_report/cred.env" "$base/mediaspace_report/requirements.txt"
chmod +x "$base/mediaspace_report_launcher.py"

python3 -m pip install --user -r "$base/mediaspace_report/requirements.txt"
python3 -c "from zoneinfo import ZoneInfo; ZoneInfo('Europe/Berlin')"
```

Alle Dateien müssen UNIX-Zeilenenden (LF) haben; der `sed`-Befehl entfernt eventuelle CR-Zeichen.

### Rechte

Der Benutzer, unter dem Flow Automation die Skripte ausführt, muss alle Dateien lesen und im Ordner `mediaspace_report/` schreiben können (State-JSON, Log). Eigenen und Flow-Benutzer prüfen:

```bash
id -un
ps -eo user,args | grep -i "[f]low-automation"
ls -l "$base" "$base/mediaspace_report"
```

- Gleicher Benutzer: zusätzlich `chmod 600 "$base/mediaspace_report/cred.env"`. `pip install --user` gilt dann auch für Flow.
- Anderer Benutzer: Ein Administrator muss den Ordner `mediaspace_report/` diesem Benutzer zuweisen und die Pakete für dessen `python3` installieren. `chmod 600` auf `cred.env` dann nicht setzen, sonst kann Flow die Datei nicht lesen.

## Start

**Flow Automation:** Module **Time** und **Script Runner**, die `/var/flow/automation/scripts/mediaspace_report_launcher.py` aufrufen. Der Lauf muss täglich um **00:01 Uhr** starten.

Im Script Runner:

| Option | Wert | Wirkung |
| --- | --- | --- |
| Destination Media Space | z. B. `Transfer` | Flow hängt den Space ein und übergibt den Pfad als `output_dir` |
| Subdir | z. B. `tmp Claudia\_Mediaspace Reports` | Unterordner im Space (`output_subdir`); `\` und `/` sind erlaubt, `..` nicht; fehlende Ordner werden angelegt |

Ohne Destination Media Space schreibt das Skript nach `report_dir`. Ist der Ziel-Space nicht verfügbar oder der Subdir ungültig, wird der Snapshot trotzdem gespeichert, der Lauf endet mit Exit-Code `1` und der nächste Lauf schreibt die Berichte. State-JSON und Log bleiben immer lokal in `mediaspace_report/`.

**Manuell:**

```bash
/var/flow/automation/scripts/mediaspace_report_launcher.py --standalone
echo $?
```

Meldungen erscheinen auf der Konsole und im Log, im Flow-Betrieb im Job-Log. Der Standalone-Modus schreibt immer nach `report_dir`. Ohne `--standalone` läuft der Launcher als AutomationScript, wenn `editshare_helpers` verfügbar ist, sonst im Standalone-Modus.

Exit-Codes: `0` = ok, `1` = Fehler (Details im Log), `130` = abgebrochen. Im Flow-Betrieb schlägt der Job bei einem Fehler fehl.

Ein manueller Lauf ersetzt den Snapshot des Vortags durch den aktuellen Wert.

## Config (Kopf von `mediaspace_report.py`)

| Eintrag | Standard | Bedeutung |
| --- | --- | --- |
| `app_name` | `mediaspace_report` | Anwendungsname |
| `app_version` | `0.5.0` | Skriptversion |
| `unit_bytes` | `2**40` | Byte je TiB |
| `script_dir` | Ordner des Moduls | Basisordner (`mediaspace_report/`) |
| `cred_path` | `script_dir / "cred.env"` | Zugangsdaten |
| `state_path` | `script_dir / "mediaspace_state.json"` | Snapshot-Zustand |
| `log_path` | `script_dir / "mediaspace_report.log"` | Laufprotokoll, max. 1 MB, 2 Rotationen |
| `report_dir` | `script_dir / "reports"` | Berichtsordner ohne Destination Media Space (Standalone) |
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
