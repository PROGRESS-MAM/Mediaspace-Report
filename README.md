# Mediaspace-Report

## ark_probe.py – Testskript für archivierte Spaces

Liest aus Ark, welche Media Spaces auf Tape bzw. Disk gesichert sind und wie groß sie sind. Ändert nichts in Ark.

### Installation

Python 3.11 oder neuer.

```console
pip config set global.extra-index-url https://artifacts.editshare.com/artifactory/api/pypi/editshare-pypi-public/simple
pip install "toolbox @ git+https://github.com/PROGRESS-MAM/TOOLBOX.git@main"
pip install "ArkAPI @ git+https://github.com/PROGRESS-MAM/ES-Ark-API.git@main"
```

`cred.env` neben dem Skript anlegen (nicht committen):

```dotenv
ARK_HOST=<host>
ARK_USER=<user>
ARK_PASSWORD=<password>
```

### Verwendung

```console
python ark_probe.py
```

Abbrechen mit `Strg+C`: Bereits gelesene Daten werden noch gespeichert.

### Config (Kopf von `ark_probe.py`)

| Eintrag | Standard | Bedeutung |
| --- | --- | --- |
| `cred_path` | `cred.env` neben dem Skript | Zugangsdaten für Ark |
| `out_root` | `probe_output` neben dem Skript | Ablage, je Lauf ein Unterordner `<YYYY-MM-DD_HHMM>` |
| `page_limit` | `10000` | Dateien je Suchanfrage, höchstens 10000 |
| `max_pages` | `1000` | Höchstzahl an Suchanfragen je Lauf |

### Ergebnisdateien

| Datei | Inhalt |
| --- | --- |
| `summary.txt` | Kurzfassung des Laufs |
| `backups.json`, `backups.csv` | Alle Backups aus Ark |
| `search_sample.json` | Erste Suchantwort mit einem Treffer |
| `files.csv` | Alle gefundenen Dateien |
| `sizes_by_backup.csv` | Dateien und Größe je Backup |
| `sizes_by_space.csv` | Größe je Space und Ablage (tape/disk), alle Treffer und jede Datei einmal |
| `backup_contents_sample.json` | Inhalt eines Tape-Backups als Rohantwort |

CSV: Trennzeichen `;`, TB = 10^12 Byte mit Dezimalkomma.
