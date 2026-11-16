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
- Teil 1: Monatsbericht je Projekt, jede Nacht fortgeschrieben; Zeitraum 01. bis letzter Tag des Monats.
- Teil 1: Belegte TB = Summe der täglichen Belegung / alle Kalendertage des Monats.
- Teil 1: Höchstens 24 Monatsberichte, die ältesten werden zuerst gelöscht.
- Teil 1: Projektzuordnung über Namensendung: Archiv, Archive, Render, Onlining, Rushes, Project, Projekt.
- Teil 1: Zugeordnete Projekte: eine Zeile je Projekt, Spalte mit Wert "Looks", sortiert nach Name.
- Teil 1: Spaces ohne Zuordnung: eine Zeile je Space, ohne "Looks", absteigend nach Größe.
- Teil 1: Storage-Zugriff über FlowAPI.EditShare (editshare-flow-api), cred.env mit FLOW_HOST, FLOW_USER, FLOW_PASSWORD; TOOLBOX unterstützt "storage" nicht.
- storage_probe: app_name = "storage_probe", app_version = "0.1.0"; mediaspace_report: app_name = "mediaspace_report", app_version = "0.1.0".

## Pakete
| ID | Paket | Dateien | Abhängig von | Modus | Review | Status |
| --- | --- | --- | --- | --- | --- | --- |
| T1 | Ark-Testskript Größe archivierter Spaces | ark_probe.py, tests/test_ark_probe.py | – | direct | B | fertig |
| T2 | Konsolenmeldungen, laufend gespeicherte Kurzfassung, Fehlerprotokoll | ark_probe.py, tests/test_ark_probe.py | T1 | direct | B | fertig |
| T3 | Testskript weitere Ark-Quellen mit Zeitlimit je Aufruf | ark_sources_probe.py, tests/test_ark_sources_probe.py | T2 | direct | B | fertig |
| T4 | Testskript Rohantworten Storage-Spaces | storage_probe.py, tests/test_storage_probe.py | – | direct | B | fertig |
| T5 | Projektzuordnung, Zusammenfassung, Sortierung, CSV | mediaspace_report.py, tests/test_mediaspace_report.py | – | direct | B | fertig |
| T6 | Nächtliche Erfassung, Fortschreibung, Aufbewahrung, README | mediaspace_report.py, tests/test_mediaspace_report.py, README.md | T4 (Martins Lauf), T5 | plan-first | B | offen |

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
- Teil 2 verworfen (Martin, 2026-11-16): Größe archivierter Projekte wird nicht ermittelt – keiner der Ansätze (Ark-Suche, Ark-Pools, FLOW-Metadaten) ist praktikabel.
- Teil 1 (Martin, 2026-11-16): Jede Nacht ein kurzer Erfassungslauf, am 01. zusätzlich der Monatsbericht über den Vormonat (01. bis letzter Tag).
- Teil 1 (Martin, 2026-11-16): Belegte TB je Projekt und Monat = Durchschnitt der Tageswerte im Monat.
- Teil 1 (Martin, 2026-11-16): Je Projekt Anfangsdatum (Erstellung erster Space) und Enddatum (Löschung letzter Space); nur aktuell belegte TB; Verkleinerung zum Ende hin auch über die Monatsgrenze über Tageswerte abbilden.
- Teil 1: Ausgabe als CSV wie Teil 2 (`;`, `utf-8-sig`, TB = 10^12 Byte, Dezimalkomma) – einheitlich mit den Testskripten.
- Teil 1: Enddatum = letzter Tag, an dem der Space erfasst wurde; leer, solange ein Space des Projekts existiert – der Löschzeitpunkt ist nur über die nächtliche Erfassung erkennbar.
- Teil 1: Anfangsdatum aus dem Erstellungsdatum in EditShare, sofern geliefert – Spaces von vor dem ersten Erfassungslauf.
- Teil 1 (Martin, 2026-11-16): Keine Tagesberichte; der Monatsbericht wird jede Nacht fortgeschrieben, höchstens 24 Berichte.
- Teil 1 (Martin, 2026-11-16): Teiler = alle Kalendertage des Monats; Spaces, die nur einen Teil des Monats existieren, zählen anteilig.
- T4: Feldnamen für Belegung, Erstellungsdatum und Kennung der Spaces unbekannt – zuerst Rohantworten der Storage-API holen, Martin startet den Lauf.
- T5: Namensendung ohne Beachtung der Groß-/Kleinschreibung, Trenner Leerzeichen, _ oder -; Projekte gleichen Namens unabhängig von der Schreibweise zusammengefasst.
- T5: Reihenfolge: zuerst alle Looks-Projekte nach Name, dann Spaces ohne Zuordnung nach Größe.
- T5: Spalten Name;TB;Anfangsdatum;Enddatum;Zuordnung; Datum TT.MM.JJJJ; Anfangs-/Enddatum auch für Spaces ohne Zuordnung.
- T5: Enddatum eines Projekts leer, solange einer seiner Spaces existiert.
- T6: Ein Messwert gilt für den Vortag (Lauf nach Mitternacht); der Lauf am 01. schließt den Vormonat ab.
- T6: Fehlt eine Nacht, zählt für Spaces, die davor und danach erfasst wurden, der Wert der vorherigen Nacht – sonst fehlen abrechenbare Tage.
- T6: Zustand je Monat in eigener Datei neben dem CSV, wird mit dem Bericht gelöscht; Anfangsdatum der Projekte wird in den Folgemonat übernommen – Daten bleiben bei in Excel geöffneter CSV erhalten.
- T6: Umbenannter Space gilt als gelöscht und neu angelegt.
- T4/T5: Gesamte Testsuite scheitert an alten Tests für die nicht mehr vorhandenen ark_probe.py und ark_sources_probe.py – nicht Teil der Abnahme, Martin entscheidet über die alten Tests.
