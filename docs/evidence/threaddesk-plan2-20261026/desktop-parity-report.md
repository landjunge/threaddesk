# Installierte ThreadDesk-Version und Gitstand

Read-only-Prüfung vom 26. Oktober 2026, Session /root/trash_contract. Keine App gestartet, gestoppt, neu gebaut oder ersetzt; keine Nutzerdaten geändert. Maschinenlesbarer Beleg: `/tmp/threaddesk-plan2-team/desktop-parity.json`.

## Tatsächliches Ergebnis

Die installierte `/Applications/ThreadDesk.app` ist weiterhin Version/Bundlebuild `0.1.2`. Aktuelle SHA-256-Werte der beiden ausführbaren Dateien stimmen exakt mit der früher unabhängig geprüften finalen Installation überein:

| Datei | SHA-256 |
| --- | --- |
| `Contents/MacOS/threaddesk-tauri` | `7caf8530f2d33052d13e4ebbce2031222c284d4f37db017ccef1f0aa6a273317` |
| `Contents/Resources/bin/ThreadDeskServer` | `341b51d3ba57d30eb30180e7ad85eb11423742038ddd9e202278f21647aebf60` |

Der damit byteidentische Sidecar wurde im vorhandenen unabhängigen Archivbeleg mit eingebetteter Identität `source_commit=07e10bf10ad24084becb8ae24e869a624f0b16d1`, `dirty=false`, `build_id=20261026T152152Z` geprüft. Statt die App auszuführen wurde die Identität über die exakte Binarygleichheit nachvollzogen.

Zusätzlich wurden jetzt alle im damaligen Archivbeleg erfassten **70 Modulquellhashes und 46 UI-Assethashes** direkt gegen die Gitobjekte von `07e10bf` geprüft: alle identisch. Der frühere Beleg bestätigt dazu den Bytecodevergleich dieser Module und die Übereinstimmung der Assets im gebauten Sidecar. Die Hashprüfung des heute installierten Sidecars verbindet diese Nachweise mit der tatsächlich vorhandenen Datei. Eine erneute Archivextraktion war wegen vollständiger Binarygleichheit nicht nötig.

Aktuell gelesenes `origin/main` ist ebenfalls `07e10bf10ad24084becb8ae24e869a624f0b16d1`. `git diff 07e10bf -- src packaging pyproject.toml` war beim Check leer. Die laufende Dokumentationsarbeit verändert damit den geprüften Laufzeitcode nicht. `codesign --verify --deep --strict --verbose=2 /Applications/ThreadDesk.app` wurde lesend ausgeführt und bestand mit Exit0.

## Einordnung für den nächsten Dokumentationscommit

Ein neuer Plan-/AGENTS-/Prüfbelegcommit hat einen neuen Git-SHA, während die installierte App ihren tatsächlichen Build-SHA07e10bf behält. Das ist bei unverändertem Runtimebaum nachvollziehbare Laufzeitparität, **keine SHA-identische Neubau-/Installationsbehauptung**. Nach Commit/Merge noch einmal prüfen, dass `src`, `packaging` und `pyproject.toml` gegenüber07e10bf unverändert bleiben; dann dokumentieren: Dokumentationsstand neuer SHA, installierter Runtimepin07e10bf, Runtimequellen identisch. Keine reine Dokuänderung als neue installierte App ausgeben.

Sobald Produktcode, UI-Assets, Paketierung oder Runtimeabhängigkeiten geändert werden, muss ein finaler Commit gepinnt, daraus das echte Paket gebaut, geprüft und installiert sowie die tatsächliche eingebettete Identität und der Erhalt des Nutzerprofils nachgewiesen werden. Der jetzige Plan baut keine neue Grafik und keinen Papierkorb.

## Grenzen und Originalquellen

Keine neue UI-/Browser-/Restartabnahme in dieser Aufgabe. Das frühere `window_onscreen=false` wird nicht nachträglich als bestanden umgedeutet; Hash- und Codesignprüfung belegen Dateiparität und Integrität, keine aktuelle Bildschirmbedienung. Der Archivbeleg erfasst die70 geladenen Produktmodule, keine pauschale Aussage über jeden beliebigen Repositorypfad.

Originale: `/Users/landjunge/ThreadDesk-Backups/latest-20261026T145414Z/evidence/independent-final-install-verification.json`, `independent-final-sidecar-archive-audit.json` und `build-identity-independent-review.json`. Deren konkrete Zeit-/Quellstände bleiben erhalten.
