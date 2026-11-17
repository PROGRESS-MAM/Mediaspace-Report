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
- Teil 1: Datenquelle FlowAPI.Admin.get_mediaspaces(as_admin=True) (editshare-flow-api), cred.env mit FLOW_HOST, FLOW_USER, FLOW_PASSWORD; Felder uuid, name, created, removed, mount_used_bytes. Storage-API liefert 401.
- Teil 1: Snapshot jede Nacht um 00:01; Bericht direkt danach aktualisiert; der Lauf am 01. um 00:01 schließt den Vormonat ab und legt den neuen Monatsbericht an.
- Teil 1: Bericht als Excel; Blatt Rohdaten mit jedem eingeflossenen Space und der ermittelten Projektzuordnung; Blatt LTO-Bestand.
- Teil 1: Zustandsdatei neben dem Skript; Berichtsordner fest im CONFIG-Bereich.
- storage_probe: app_name = "storage_probe", app_version = "0.1.0"; mediaspace_report: app_name = "mediaspace_report", app_version = "0.1.0".

- Automation-Paket (2026-11-17): Vorlage ES-All-Meta; Launcher mediaspace_report_launcher.py im Repo-Root, auf dem Worker unter /var/flow/automation/scripts/, Fachmodule im Unterordner mediaspace_report/.
- Automation-Paket: State-JSON, Log und reports/ im Unterordner mediaspace_report/ (script_dir).
- Automation-Paket: nur Linux; alle Windows-Bezüge und Windows-Funktionsteile entfernen.
- Automation-Paket: Toolbox-Mini unverändert, nicht verwendet; ms_source behält die eigene Admin-Verbindung.
- Automation-Paket: mediaspace_report app_version = "0.4.0"; Launcher app_name = "mediaspace_report_launcher", app_version = "1.0.0".

## Pakete
| ID | Paket | Dateien | Abhängig von | Modus | Review | Status |
| --- | --- | --- | --- | --- | --- | --- |
| T1 | Ark-Testskript Größe archivierter Spaces | ark_probe.py, tests/test_ark_probe.py | – | direct | B | fertig |
| T2 | Konsolenmeldungen, laufend gespeicherte Kurzfassung, Fehlerprotokoll | ark_probe.py, tests/test_ark_probe.py | T1 | direct | B | fertig |
| T3 | Testskript weitere Ark-Quellen mit Zeitlimit je Aufruf | ark_sources_probe.py, tests/test_ark_sources_probe.py | T2 | direct | B | fertig |
| T4 | Testskript Rohantworten Storage-Spaces | storage_probe.py, tests/test_storage_probe.py | – | direct | B | fertig |
| T5 | Projektzuordnung, Zusammenfassung, Sortierung, CSV | mediaspace_report.py, tests/test_mediaspace_report.py | – | direct | B | fertig |
| T6 | Datenquelle: Admin-Abfrage mit Zeitlimit, Umwandlung in SpaceInfo | ms_source.py, tests/test_ms_source.py | T4 | plan-first | B | fertig |
| T7 | Zustandsdatei, Snapshots, Interpolation, Monatssummen | ms_state.py, tests/test_ms_state.py | – | direct | B | fertig |
| T8 | Excel-Arbeitsmappe (Bericht, Rohdaten, LTO-Bestand), 24 Berichte | ms_excel.py, tests/test_ms_excel.py | – | direct | B | fertig |
| T9 | Phasen/Reaktivierung, Bericht- und Rohdatenzeilen, Statuszeile; CSV entfällt | mediaspace_report.py, tests/test_mediaspace_report.py | T5–T8 | direct | B | fertig |
| T10 | Ablauf: Lauf, Monatsabschluss, LTO, Log, Aufbewahrung, README | mediaspace_report.py, tests/test_mediaspace_report.py, README.md | T9 | plan-first | B | fertig |
| T11 | Einstieg update_mediaspace_report/main(argv), Flow-Meldungen, Windows-Teile entfernen | mediaspace_report.py, tests/test_mediaspace_run.py | T10 | direct | B | fertig |
| T12 | Launcher Flow Automation/Standalone | mediaspace_report_launcher.py, tests/test_launcher.py | T11 (Schnittstelle) | direct | A | fertig |
| T13 | README Worker-Deploy, requirements.txt | README.md, requirements.txt | – | CodeZilla | – | fertig |
| T14 | Berichtsordner aus Destination Media Space (output_dir/output_subdir) | mediaspace_report.py, tests/test_mediaspace_run.py | T11 | direct | B | fertig |
| T15 | Launcher übergibt output_dir/output_subdir | mediaspace_report_launcher.py, tests/test_launcher.py | T12, T14 (Schnittstelle) | direct | A | fertig |
| T16 | README Destination Media Space | README.md | – | CodeZilla | – | fertig |

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
- Teil 1 (Martin, 2026-11-16): Keine Tagesberichte; der Monatsbericht wird jede Nacht fortgeschrieben, höchstens 24 Berichte.
- Teil 1 (Martin, 2026-11-16): Teiler = alle Kalendertage des Monats; Spaces, die nur einen Teil des Monats existieren, zählen anteilig.
- T4: Feldnamen für Belegung, Erstellungsdatum und Kennung der Spaces unbekannt – zuerst Rohantworten der Storage-API holen, Martin startet den Lauf.
- T5: Namensendung ohne Beachtung der Groß-/Kleinschreibung, Trenner Leerzeichen, _ oder -; Projekte gleichen Namens unabhängig von der Schreibweise zusammengefasst.
- T5: Reihenfolge: zuerst alle Looks-Projekte nach Name, dann Spaces ohne Zuordnung nach Größe.
- T5: Spalten Name;TB;Anfangsdatum;Enddatum;Zuordnung; Datum TT.MM.JJJJ; Anfangs-/Enddatum auch für Spaces ohne Zuordnung.
- T5: Enddatum eines Projekts leer, solange einer seiner Spaces existiert.
- T7: Ein Messwert gilt für den Vortag (Lauf nach Mitternacht); der Lauf am 01. schließt den Vormonat ab.
- T4/T5: Gesamte Testsuite scheitert an alten Tests für die nicht mehr vorhandenen ark_probe.py und ark_sources_probe.py – nicht Teil der Abnahme, Martin entscheidet über die alten Tests.
- Teil 1 (Martin, 2026-11-17): Durchschnitt = Summe der Snapshot-Werte / Anzahl der Snapshots im Monat; eine fehlende Nacht zählt nicht mit; fehlen mehrere Nächte, wird linear vom letzten Snapshot aus interpoliert und im Bericht als interpoliert gekennzeichnet. Ersetzt T6 „Wert der vorherigen Nacht“.
- Teil 1 (Martin, 2026-11-17): Ein im Monat gelöschtes Projekt bleibt bis zum Monatsabschluss im Bericht, im Folgebericht nicht mehr.
- Teil 1 (Martin, 2026-11-17): Excel statt CSV – ersetzt das CSV-Ausgabeformat aus T5; parse_project und build_rows bleiben.
- T7: Der Snapshot vom 01. um 00:01 gilt für den letzten Tag des Vormonats; der neue Monat beginnt mit dem Snapshot vom 02.
- T7: Interpolation je Space zwischen letztem und aktuellem Snapshot; Existenz an den fehlenden Tagen aus created/removed; Tage werden ihrem Kalendermonat zugeordnet, ein verpasster Monatsabschluss wird beim nächsten Lauf nachgeholt.
- T7: Kennung eines Space = uuid – Namen werden nach dem Löschen erneut vergeben.
- T6: Zeitstempel der API (UTC) werden in Europe/Berlin umgerechnet.
- T9: Ist die Excel-Datei gesperrt, bleibt der Zustand erhalten und der nächste Lauf schreibt den Bericht neu; ein noch nicht geschriebener Abschluss wird nachgeholt.
- T6: Zugangsdaten (credentials) der API-Antwort werden nie in Bericht, Rohdaten oder Zustandsdatei übernommen.
- T9: Projektzuordnung nur über gleichen Projektnamen (ohne Groß-/Kleinschreibung), keine unscharfe Suche nach Endungen wie _2 – sonst falsche Gruppen, z. B. „ddr 72“, „1989“.
- T9: Reaktivierung = mindestens ein ganzer Tag, an dem kein Space des Projekts existierte (aus created/removed).
- T9: LTO-Bestand nur für Looks-Projekte, deren letzter Space gelöscht ist; laufend fortgeführt; bei Reaktivierung bleibt der Eintrag bestehen.
- Teil 1 (Martin, 2026-11-17): LTO-Wert = Durchschnitt über die Snapshots des Projekts im letzten Monat mit Werten, gekennzeichnet mit „~“; kein Höchstwert, nicht der letzte Snapshot.
- Teil 1 (Martin, 2026-11-17): Anfangsdatum reaktivierter Projekte = Beginn der aktuellen Phase; frühere Phasen in Rohdaten/LTO-Bestand.
- Teil 1 (Martin, 2026-11-17): Snapshots nur für den laufenden Monat; nach Abschluss werden sie gelöscht, soweit technisch nicht mehr nötig. Gelöschte Spaces werden nicht mit 0 geführt.
- Teil 1 (Martin, 2026-11-17): LTO-Blatt mit Spalte „Looks“ und Hinweistext, dass es nur Looks-Projekte enthält, nicht den gesamten LTO-Bestand.
- Teil 1 (Martin, 2026-11-17): Manuelle Zuordnungsliste ggf. nach dem ersten Lauf.
- T6: mount_used_bytes ist aktuell – Admin-Panel 8,2 / 5,5 TiB gegen API 8,249 / 5,546 TiB; 1989 Onlining 15,05 gegen 15,48 TiB vermutlich Änderung zwischen den Zeitpunkten.
- T6: Einheit TiB (2**40 Byte) – deckungsgleich mit EditShare-Panel und Quotas (quota_in_gb binär); ersetzt TB = 10**12 für Teil 1.
- T7: Abrechnung je Space = Summe seiner Snapshot-Werte / Anzahl aller Snapshots des Monats; gelöschte Spaces haben keine weiteren Einträge (keine 0 gespeichert) – sonst zählt ein 1-Tages-Space als ganzer Monat.
- T7: Ein zweiter Lauf am selben Tag ersetzt den Snapshot dieses Tages.
- T8: Excel über openpyxl; TiB numerisch mit Format 0.00, im LTO-Blatt "~"0.00; Datum TT.MM.JJJJ; Dateiname Mediaspace-Report_YYYY-MM.xlsx.
- T8: Bericht beginnt mit Statuszeile (Monat, Stand, Snapshots, vorläufig/abgeschlossen) – verhindert Abrechnung eines vorläufigen Berichts.
- T9: Fehler nachts in begrenzter Logdatei (RotatingFileHandler) neben dem Skript.
- T9: Unter Windows braucht zoneinfo das Paket tzdata – in README-Installation.
- T8: Reviewer: Fehlermeldungen der API ohne Zugangsdaten (ersetzt durch [REDACTED]).
- T9: Phase = zusammenhängende Lebenszeit der Spaces eines Projekts; neue Phase ab mindestens einem ganzen Tag ohne Space; Bericht nutzt die letzte Phase, die bis Monatsende begonnen hat.
- T9: Rohdaten-Reihenfolge: Looks-Spaces nach Projekt und Name, danach Spaces ohne Zuordnung nach Name.
- T10: LTO-Eintrag nur beim Monatsabschluss, mit dem Monatsmittel des letzten abgeschlossenen Monats mit Werten der aktuellen Phase; doppelt verhindert über Projekt + Phasenbeginn.
- T10: Standard-Berichtsordner reports/ neben dem Skript, Martin trägt den festen Pfad in CONFIG ein – erster Lauf funktioniert ohne Anpassung.
- T10: Gesperrter Bericht (PermissionError) = Warnung, Exit 0, Monat bleibt im Zustand; andere Schreibfehler = Exit 1; Zustand wird nach jedem erfolgreichen Snapshot gespeichert.
- T10: Fehler beim Laden des Zustands, bei der API oder beim Snapshot: Exit 1, nichts geschrieben außer dem Log.
- T10: README neu: nur storage_probe.py und mediaspace_report.py (ark_probe/ark_sources_probe nicht mehr im Repo); Zeitplan über Windows-Aufgabenplanung 00:01.
- T10: Reviewer: gesperrter Berichtsordner (PermissionError beim Anlegen) wie gesperrter Bericht – Warnung, Zustand gespeichert, Berichte beim nächsten Lauf.
- T11: Sonderbehandlung PermissionError (gesperrte Excel-Datei unter Windows) entfällt – unter Linux ein echter Rechtefehler: Exit 1, Monat bleibt im Zustand, nächster Lauf schreibt neu.
- T11: _configure_console (UTF-8 für Windows-Konsolen) entfällt; tzdata entfällt in requirements.
- T11: Flow-Meldungen: ERROR und höher → "error", sonst "info".
- T12: Launcher folgt metadata_file_launcher.py aus ES-All-Meta; Exit-Code ≠ 0 → error_and_exit.
- T13: README ohne storage_probe-Abschnitt – storage_probe.py ist nicht mehr im Repo; tests/test_storage_probe.py ist verwaist und nicht Teil der Abnahme.
- T13: Repo bleibt flach wie die Vorlage; die Unterordner-Struktur entsteht beim Kopieren auf den Worker.
- T14 (Martin, 2026-11-17): Berichte über Flow Automation „Destination Media Space“ (Transfer, Subdir „tmp Claudia\_Mediaspace Reports“); Flow hängt den Space ein, das Skript mountet nicht selbst.
- T14: Subdir: „\“ wird zu „/“, leere und „.“-Teile entfallen, „..“ ist ungültig – Eingabe im Panel im Windows-Stil.
- T14: Ziel-Space-Wurzel (output_dir) fehlt oder Subdir ungültig: Snapshot speichern, keine Berichte, Exit 1; die Wurzel wird nie angelegt – sonst landen Berichte bei fehlendem Mount auf der lokalen Platte.
- T14: Ohne output_dir (Standalone) gilt report_dir aus CONFIG.
- T15: Launcher meldet am Ende „mediaspace_report abgeschlossen“; der Berichtsordner steht als Logzeile „Berichtsordner: …“ im Job-Log.
