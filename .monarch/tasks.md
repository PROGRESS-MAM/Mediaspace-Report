# Tasks – Mediaspace-Report

## Globale Vorgaben
- Teil 2 zuerst: Testskript `ark_probe.py`, nur lesend gegen Ark, startet Martin selbst.
- Verbindung: TOOLBOX `tb_link_api(cred_path, "ark")`, `cred.env` neben dem Skript mit ARK_HOST, ARK_USER, ARK_PASSWORD.
- ArkAPI-Aufrufe: nur `get_backups()`, `search_backups(pattern, mode, *, limit, offset)`, `get_backup_contents(backup_id)`.
- Suche: Muster `"*"`, Modus `"wildcard"`, Seitengröße 10000.
- Ausgabe: `probe_output/<YYYY-MM-DD_HHMM>/` neben dem Skript.
- CSV: Trennzeichen `;`, Kodierung `utf-8-sig`, Byte als Ganzzahl, TB = Byte / 10**12 mit 4 Nachkommastellen und Dezimalkomma.
- Coding-Gliederung: IMPORTS, CONFIG (app_name, app_version), FUNC, MAIN, EXEC.
- app_name = "ark_probe", app_version = "0.2.0" (ab T2)

## Pakete
| ID | Paket | Dateien | Abhängig von | Modus | Review | Status |
| --- | --- | --- | --- | --- | --- | --- |
| T1 | Ark-Testskript Größe archivierter Spaces | ark_probe.py, tests/test_ark_probe.py | – | direct | B | fertig |
| T2 | Konsolenmeldungen, laufend gespeicherte Kurzfassung, Fehlerprotokoll | ark_probe.py, tests/test_ark_probe.py | T1 | direct | B | fertig |
| T3 | Testskript weitere Ark-Quellen mit Zeitlimit je Aufruf | ark_sources_probe.py, tests/test_ark_sources_probe.py | T2 | direct | B | fertig |

## Entscheidungen
- T1: Space-Name über backup_id aus get_backups(); ohne Treffer space_name der Suche – space_name der Suche ist ein interner Kurzname.
- T1: Je Space beide Summen: alle Treffer und jede Datei nur einmal (flow_hash, sonst path/filename/size) – Mehrfachkopien unklar.
- T1: Eigene Seitenschleife statt limit=0 – limit=0 verwirft bei Fehlern alle Treffer und zeigt keinen Fortschritt.
- T1: Inhalt eines Tape-Backups immer einmal abrufen – klärt den Ausweichweg unabhängig vom Sucherfolg.
- T1: toolbox erst in connect_ark() importieren – Tests ohne FlowAPI/ArkAPI lauffähig.
- T1: Fehlt media_space_name im Backup, gilt der space_name der Suche – ein KeyError würde einen langen Lauf ohne Summen beenden.
- T1: sizes_by_backup.csv und sizes_by_space.csv auch bei Ausnahmen im Scan schreiben (finally) – keine Datenverluste.
- T2: Ursache des Abbruchs ohne Fehlermeldung unbekannt – summary.txt wird nach jedem Schritt und jeder Seite geschrieben, Fehler mit traceback.txt, damit der nächste Lauf die Ursache zeigt, auch nach hartem Stopp in VS Code.
- T2: Konsole auf UTF-8, errors=replace, zeilenweise Ausgabe – VS-Code-Ausgabefenster nutzen Pipes mit cp1252 und Pufferung.
- T2: Ungültige oder fehlende Dateigröße zählt 0 und wird als „ungültige größen“ gezählt statt den Lauf zu beenden.
- T2: In summary.txt nur die Anzahl nicht zugeordneter Backup-IDs – eine Liste kann bei abweichendem ID-Format sehr lang werden; Details in sizes_by_backup.csv.
- T2: tests/ und .monarch stehen in Martins .gitignore und fehlen im Snapshot – Testdatei wird Workern und Reviewern ausdrücklich angehängt.
- T2: Laufendes Neuschreiben der Summen-CSVs überspringt gesperrte Dateien (PermissionError, z. B. in Excel geöffnet) mit einmaliger Warnung; nur das Schreiben am Ende zählt als Fehler – sonst bricht ein offenes Excel den Lauf ab.
- T3: Wildcard-Suche hängt bei Martin in Schritt 2 (vermutlich Zählung aller Treffer über 7557 Tape-Backups) – zuerst günstige Endpunkte mit Größenangaben prüfen.
- T3: Eigenes Skript ark_sources_probe.py, nutzt Helfer aus ark_probe.py – ark_probe.py bleibt unverändert.
- T3: Jeder Aufruf in eigenem Thread mit Zeitlimit und frischer Ark-Verbindung – ArkAPI hat kein Zeitlimit; eine hängende Verbindung darf nicht weiterbenutzt werden.
- T3: Beispiel-Backup = jüngstes __ms__-Tape-Backup; Pool = dessen destination_id.
- T3: Fehlt Beispiel-Backup oder Pool, entfallen beide Inhaltsaufrufe (8 und 9) – Reviewer-Korrektur, bei Martins Daten haben alle Backups einen Pool.
