# Optionale lokale Inhaltssuche / optional local content search

Die Suche ist standardmäßig ausgeschaltet. Sie erfasst ausschließlich den
aktuellen Titel, die Beschreibung und `context.notes` eines Threads im bereits
ausgewählten lokalen Workspace. Dateien, Prompts, Agentenzustand, Snapshots und
historische Notizen werden nicht durchsucht. Keine zusätzliche Abhängigkeit.

```sh
td search --status
td search --enable
td search --rebuild --batches 1000 --status
td search 'nächste Schritte' --limit 20
td search 'nächste Schritte' --project project-id --all --pages 3
td search --disable
```

Ausgabe ist JSON, bei mehreren Seiten JSONL. Ein Treffer nennt Thread-ID,
Threadrevision, Originalfeld, Zeichenposition und höchstens 240 Zeichen Plaintext
als Ausschnitt. Plaintext muss bei späterer HTML-Darstellung escaped werden.
`SearchService.resolve(hit)` liest das Originalfeld erneut, prüft aktuelle
Berechtigung, Revision und Projektionsdigest und lehnt veraltete Ziele ab. Der
Digest ist ein Änderungsindikator, kein Identitäts- oder Herkunftsnachweis.

Die kleine Python-API liegt in `threaddesk.services.search`: `SearchService`
mit `status`, `set_enabled`, `rebuild_batch`, `search`, `resolve`, `close`.
`SearchService(store)` ohne passende Authority lehnt ab. Der lokale CLI-Einstieg
übergibt ausdrücklich `LocalFileOwnerPolicy` für den ausgewählten Workspace.
Sie vertraut dem lokalen Bediener und dessen Dateizugriff; auf POSIX muss die
Workspace-Wurzel zusätzlich dem aktuellen UID gehören. Das ist keine Anmeldung,
keine SID-Prüfung auf Windows und keine Team-, Room-, LAN- oder Modulberechtigung.
Die Suche wird keinem HTTP-/MCP-/Room-Weg hinzugefügt. Ein Projektfilter erteilt
keine Rechte. Ein künftiger Authority-Adapter muss `authorize(workspace)`, eine
bei Rechteänderung wechselnde `generation()` und `can_read_current(document)`
bereitstellen. Jeder Treffer und der Seitenabschluss prüfen die Policy frisch;
fehlende/fehlerhafte Authority verwirft die Antwort. Teamrechte bleiben E06.

SQLite verwendet die vorhandene FTS5-Tabelle mit einer wegwerfbaren Projektion
und optionaler Metadatentabelle; Schema-Version und kanonische Threadform bleiben
gleich. Expliziter Aufbau bereinigt und befüllt höchstens 500 Datensätze und
8 MiB Quelltext pro Batch. Kanonische Store-Saves, Rename, Archive/Unarchive,
Snapshot-Restore und Delete aktualisieren die Projektion im bestehenden Commit.
Ein Veröffentlichungsmarker und Quellgeneration verhindern `ready` bei
fehlendem Index, fehlgeschlagener Aktualisierung oder zwischenzeitlichem Save
während des Aufbaus. `ready` bezieht sich auf diesen verwalteten Store-Vertrag;
direkte SQL-Manipulation ist kein unterstützter Schreibervertrag. Indexfehler
führen zur begrenzten kanonischen Ersatzsuche. Ein isolierter Indexfehler darf
einen gültigen Save nicht scheitern lassen; ein echter Engine-Rollback der
gesamten Transaktion muss weiterhin als fehlgeschlagener Save gemeldet werden.
Ein neuer expliziter Rebuild reconciliert den vollständigen verwalteten Bestand.
Zusätzlich beobachtet die dauerhaft getrennte read-only-Verbindung mittels
[SQLite `data_version`](https://www.sqlite.org/pragma.html#pragma_data_version)
fremde Commits während einer Seite/Fortsetzung, auch wenn ein optionaler
Epoch-Write fehlschlägt. Der Vergleich gilt nur auf derselben Verbindung im
laufenden Prozess; er ist keine persistente/global vergleichbare Generation
oder Snapshotgarantie. Jeder Workspace-DB-Commit darf konservativ invalidieren.
Der Seitenabschluss bindet zusätzlich aktuellen Quellmodus und Enabled-Stand.

JSON besitzt ausdrücklich **keinen** persistenten Inhaltsindex. Der Modus
`bounded_scan` liest aktuelle Quellen über die vorhandenen gebundenen
No-follow-Leser, ohne `get_thread`/`list_threads` und ohne Legacy-Anker zu
schreiben. `--rebuild` beginnt hier nur eine neue Beobachtungs-/Cursorgeneration.
Atomare Store-Schreibvorgänge ändern den Verzeichnisstand; fremde Inplace- und
Mehrprozessschreiber ermöglichen keine vollständige Snapshotgarantie.
JSON-Antworten tragen deshalb immer `json_external_writers_unverified`,
`complete=false` und `truncated=true`, auch nach Ende der beobachteten Aufzählung.
Der Ausschnitt stammt immer aus dem gerade gelesenen Originalfeld.

Pro Aufruf gelten: 1–100 Treffer, höchstens 500 Kandidaten und 8 MiB Quellen
einschließlich konservativer Reservierung fehlgeschlagener Reads, höchstens
1 MiB je Thread plus 16 KiB Revisionsanker. Das zusätzliche Zeitbudget von
100 ms wird zwischen Reads und per SQLite-Progresshandler geprüft; ein einzelner
Datei-/Betriebssystemaufruf ist dadurch nicht hart zeitlich präemptierbar.
Queries enthalten 1–16 wörtliche Begriffe, höchstens 512 UTF-8-Bytes, keine
Steuerzeichen. FTS erhält gebundene, quotierte Literale; Operatoren werden nicht
übernommen. FTS-Token-AND plus Prüfung des aktuellen Feldes und der Ersatzmodus
mit case-insensitivem Substring-AND sind ausdrücklich verschiedene Semantiken.
FTS kann mehrere Felder desselben Threads liefern; der Ersatzmodus liefert das
erste passende Feld pro Thread. Reihenfolge ist technisch, keine Relevanzzusage.

Fortsetzungen sind einmalig, pro Serviceprozess, höchstens fünf Minuten gültig
und auf 128 aktive Iteratoren begrenzt. Query, Limit, Projekt-/Archivfilter,
Quell-/Indexgeneration, Policy und Serviceinstanz binden den Cursor. Neustart,
Rechtewechsel, Deaktivierung und Rebuild invalidieren ihn. Der CLI-Prozess
verwendet `--pages` für echte Fortsetzungen im selben Aufruf; ein ausgegebener
Cursor kann nach Prozessende nicht wiederbelebt werden. `next_cursor=null`
bedeutet beobachtetes Aufzählungsende, keine globale JSON-Vollständigkeit.
Budget-/Quellfehler erscheinen in `reasons`; Teilantworten sind kein Ready-Beleg.

Quellprüfung: [E08.1-Evidenz](evidence/e08-local-search-20261020/STATUS.md).
Der getrennte optionale Bridge-Dateiindex, echte Projekt-/Teamrechte und eine
Produkt- oder Paketfreigabe bleiben außerhalb dieses lokalen Schnitts.

English: disabled by default, trusted local file-access scope only. Explicitly
enable/rebuild; bounded current-content search and honest scan-only fallback.
No transport authorization or complete JSON snapshot is claimed. Cursors expire
with the live process; use `--pages` within one CLI invocation.
