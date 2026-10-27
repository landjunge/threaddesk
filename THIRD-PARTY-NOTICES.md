# ThreadDesk: Drittkomponenten und erforderliche Hinweise

Stand 27.10.2026, Basis main `1199c8ba581dbf4ecaf2c489171f085c958b7560`.
Die Root-LICENSE gilt für die unter ihr angebotenen eigenen Beiträge.
Drittkomponenten und historische MIT-Anteile behalten ihre jeweiligen Rechte.
Diese Übersicht ist kein vollständiger SBOM-/Compliance-Nachweis eines
ausgelieferten Desktop-, Server- oder Containerartefakts.

## Direkt im Quellbaum und Python-Paket enthaltene UI-Dateien

| Komponente | Version | Lizenz | Erhaltener Originaltext |
| --- | --- | --- | --- |
| htmx.org | 2.0.4 | 0BSD | `src/threaddesk/ui/static/UI-VENDOR-LICENSES.txt` |
| alpinejs | 3.14.8 | MIT; Copyright © 2019–2021 Caleb Porzio and contributors | dieselbe Datei |

Die vollständigen vorhandenen Texte bleiben unverändert. Das Python-Paket
enthält sie als UI-Paketdatei und als deklarierten `License-File`-Eintrag.
Versionen und Hashes stehen in `src/threaddesk/ui/static/ui-vendor.json`.
Der erhaltene MIT-Notice für historische eigene Beiträge steht gesondert in
`licenses/ThreadDesk-MIT-historical.txt`; Umfang siehe `docs/LICENSING.md`.

## Getrennte Abhängigkeiten und Plattformpakete

`pyproject.toml` deklariert Python-Pakete überwiegend als Versionsbereiche.
Daraus folgt kein feststehender Inhalt eines künftigen Releasepakets. Der
aktuelle Rust-Lockstand enthält 404 externe Pakete; npm-Lockdatei und Cargo.lock
sind zusätzlich zu den konkret aufgelösten Python-Versionen zu prüfen.
Tauri und viele weitere Komponenten erlauben MIT oder Apache-2.0; die zulässige
Lizenzwahl und die jeweiligen Copyright-/Lizenz-/NOTICE-Texte sind festzuhalten.
Eigene Produktbedingungen ersetzen diese Texte nicht.

Besondere Nachweise vor Weitergabe eines gebauten Artefakts:

- MPL-2.0: im geprüften Cargo.lock `cssparser 0.37.0`,
  `cssparser-macros 0.7.1`, `dtoa-short 0.3.5`, `option-ext 0.2.0` und
  `selectors 0.38.0`. Tatsächlichen Build-/Link-/Distributionsumfang bestimmen
  und anwendbare Hinweis- und Quellbereitstellungspflichten erfüllen.
- Python-/Kryptografie-/OS-Pakete: konkrete Wheels, native Bibliotheken,
  OpenSSL-/Python-Texte und Containerbestandteile gesondert inventarisieren.
  Ein Entwicklungspaket ist nicht automatisch im Kundenartefakt enthalten.
- PyInstaller hat eine offizielle Bundlingausnahme; daraus folgt keine
  Befreiung von den Lizenzen der damit gebündelten anderen Komponenten.
- Systemframeworks, WebKit-/GTK-/WebView2-Weitergabe und alternative Backends
  hängen vom tatsächlich ausgelieferten Ziel ab. Kein pauschaler Schluss
  allein aus dem Namen des Wrappers.
- Noch nicht in dieser Mainbasis enthaltene Graph-/Command-Erweiterungen sind
  kein Bestandteil dieses festgehaltenen Inventars. Ihr späterer Merge braucht
  einen neuen Abgleich der tatsächlich gebündelten Dateien und Notices.

Vor Verkauf und vor jedem Distributionsrelease fehlen weiterhin ein
artefaktgenaues vollständiges Notice-/Quellenpaket und ein geprüfter Abgleich
mit den tatsächlich enthaltenen Binaries, Plattformen und Versionen. Diese
Dokumentation behauptet weder vollständige Exklusivrechte noch abgeschlossene
Erfüllung sämtlicher Drittpflichten.

Primärreferenzen: [MIT](https://opensource.org/license/mit),
[Mozilla MPL 2.0](https://www.mozilla.org/en-US/MPL/2.0/),
[PyInstaller-Ausnahme](https://pyinstaller.org/en/stable/license.html).
