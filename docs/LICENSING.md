# ThreadDesk: Lizenzhistorie und Geltungsbereiche

Dokumentationsstand: 27.10.2026. Geprüfte Basis ist main
`1199c8ba581dbf4ecaf2c489171f085c958b7560` (Version 0.1.5).
Die frühere nichtmaßgebliche englische Übersetzung ist im Originalverlauf und
im externen Belegarchiv erhalten. Die aktuelle eigene Lizenzdatei ist Deutsch;
ihre bisherigen deutschen Bedingungen bleiben wortgleich.
Diese Bestandsbeschreibung ändert keine Lizenzbedingungen und keine bereits
erteilten Rechte. Maßgeblich bleiben die jeweiligen Originaltexte und der
tatsächlich unter ihnen erhaltene Code.

## Belegte Historie

| Punkt im geprüften Gitverlauf | Nachweis | Bedeutung |
| --- | --- | --- |
| Initialcommit 14.08.2026 | `3f9b5da78c7e308189e378eee58a36209bc38ad3:LICENSE` | MIT, Copyright (c) 2026 landjunge |
| Historischer Release v0.1.1rc1 | Tagcommit `08e10b37547a8e3eb3d9407efdfc06ad31f34255:LICENSE` | MIT-Fassung; ältere Downloads bleiben unter ihren jeweils mitgelieferten Bedingungen |
| Unmittelbarer Parent des ersten Rechtewechsels | `1de98700bbb6b14f32edde94a2fdabe7e3fa2338:LICENSE` | Letzte MIT-Basis unmittelbar vor dem Wechsel auf diesem Pfad |
| 07.10.2026, 14:52:46 UTC | `449fdd2b4ac98e1a613a617b1518232f5f2ab3f0:LICENSE` | All-rights-reserved-Hinweis mit ausdrücklichem Vorbehalt bereits eingeräumter MIT-Rechte |
| 18.10.2026, 12:25:37 UTC | `f2661a44c47c618aa827922cfa74db2e7aa83910:LICENSE` | Netzwerkpunkt Personal Use License 1.0; §5 erhält historische MIT-Rechte |

Die Gitgrenze ist kein Nachweis, wann jede Kopie an jeden Empfänger gelangte.
Das Datum allein entscheidet auch nicht über die Herkunft später weitergenutzter
Dateiteile. Die aktuellen Bedingungen machen früher wirksam eingeräumte MIT-Rechte
an erhaltenen Fassungen bzw. weiterverwendeten MIT-Anteilen nicht rückwirkend
unwirksam. Separate Erlaubnisse und gesetzliche Rechte bleiben maßgeblich.
Der historische MIT-Text ist unverändert in
[`licenses/ThreadDesk-MIT-historical.txt`](../licenses/ThreadDesk-MIT-historical.txt)
aus dem genannten Parent archiviert. Er lizenziert nicht pauschal sämtliche
späteren eigenen Ergänzungen unter MIT.

## Heutige Metadaten und Texte

- [Root-LICENSE](../LICENSE): Netzwerkpunkt Personal Use License 1.0 mit unverändertem deutschen Bedingungstext
  für die unter ihr angebotenen eigenen Beiträge; Deutsch ist maßgeblich.
- Python: `LicenseRef-Netzwerkpunkt-Personal-Use-1.0 AND MIT AND 0BSD` erfasst
  die aktuelle Eigenlizenz zusammen mit erhaltenen MIT-Anteilen und den
  mitgelieferten UI-Dateien. `AND` beschreibt die zusammen enthaltenen
  Lizenzbereiche, keine Wahl zwischen MIT und der Eigenlizenz für alle Dateien.
  `license-files` nimmt die Texte und diese Abgrenzung ins Paket auf.
- Das private npm-Buildpaket `packaging/tauri` verweist mit
  `SEE LICENSE IN LICENSE` auf eine bytegleiche Kopie der Root-LICENSE im
  Paketordner. Bei künftigen Änderungen müssen beide Kopien abgeglichen werden.
- Das eigene Rust-Shellpaket verweist über `license-file` auf die Root-LICENSE.
  Fremde Tauri-/Rust-/npm-Pakete behalten ihre eigenen Lizenzen.

Die Anpassung der setuptools-Untergrenze auf 77.0.3 unterstützt ausschließlich
die verwendeten PEP-639-Metadaten. Laufzeitabhängigkeiten, Versionsnummern,
Funktionen und historische Release-Artefakte wurden dabei nicht geändert.
Ein lokal geprüftes Wheel ist kein neu veröffentlichtes Release und keine
aktualisierte Desktop-Installation.

## Verkauf und Rechtevorbehalte

Die aktuelle Eigenlizenz gewährt private Nutzung und private Anpassungen im
beschriebenen Umfang. Geschäftlicher Einsatz, Verkauf und entgeltliche Dienste
benötigen die dort genannte gesonderte Erlaubnis. Allgemeine Weiterverteilung,
Unterlizenzierung und Markenrechte werden darin nicht pauschal eingeräumt.
Dies ersetzt keinen Nachweis, welche ausschließlichen, übertragbaren oder
unterlizenzierbaren Rechte der Verkäufer tatsächlich besitzt.

Ein Verkaufsanhang muss historische MIT-Bestandteile, vorhandene Einzel- und
Privatnutzungsrechte sowie Drittkomponenten ausdrücklich aus einer etwaigen
Exklusivitätszusage ausnehmen. Rechte an menschlichen Fremdbeiträgen,
Arbeitsverhältnissen, KI-unterstützter Herkunft, Logos und Domains sind anhand
separater Unterlagen zu prüfen. Ein Autorname im Gitverlauf allein genügt nicht.
