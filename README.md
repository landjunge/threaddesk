**English** · [Deutsch](README.de.md)

<p align="center">
  <img src="assets/design/icons/dark/ThreadDesk-dark-256.png" alt="ThreadDesk" width="256" height="256">
</p>

<p align="center">
  <a href="https://github.com/landjunge/KiraBridge/blob/docs/product-family-readme-20261031/README.md" title="KiraBridge"><img src="assets/readme/KiraBridge-dark.svg" alt="KiraBridge" width="48" height="48"></a>
  &nbsp;
  <a href="https://github.com/landjunge/4AllPass/blob/docs/product-family-readme-20261031/README.md" title="4AllPass"><img src="assets/readme/4AllPass-dark-128.png" alt="4AllPass" width="48" height="48"></a>
  &nbsp;
  <a href="https://github.com/landjunge/tollgate/blob/docs/product-family-readme-20261031/README.md" title="TollGate"><img src="assets/readme/TollGate-dark-128.png" alt="TollGate" width="48" height="48"></a>
  &nbsp;
  <a href="https://github.com/landjunge/agent-authority-lab/blob/docs/product-family-readme-20261031/README.md" title="Agent Authority"><img src="assets/readme/Agent-Authority-dark.svg" alt="Agent Authority" width="48" height="48"></a>
</p>

<h1 align="center">ThreadDesk</h1>

<p align="center"><strong>A workspace that remembers where your AI projects stand.</strong></p>

ThreadDesk keeps ideas, decisions, notes and files with their project. Switch between tasks and pick up where you left off.

**Published: [0.1.1rc1](https://github.com/landjunge/threaddesk/releases/tag/v0.1.1rc1) · October 2, 2026 · Preview**

[Download for macOS Intel](https://github.com/landjunge/threaddesk/releases/download/v0.1.1rc1/ThreadDesk-macOS.dmg) · [macOS Apple Silicon](https://github.com/landjunge/threaddesk/releases/download/v0.1.1rc1/ThreadDesk-macOS-AppleSilicon.dmg) · [Windows](https://github.com/landjunge/threaddesk/releases/download/v0.1.1rc1/ThreadDesk-Windows.exe)

Checksums and source records are on the [download page](https://github.com/landjunge/threaddesk/releases/tag/v0.1.1rc1). Windows development is temporarily paused; the existing download remains available.

## What ThreadDesk helps you do

- **Project context:** manage threads, notes, snapshots, a knowledge map and whiteboards locally.
- **Local AI:** optionally use Ollama with a model you choose.
- **Collaboration:** exchange explicitly shared whiteboard entries between local installations.
- **Backups:** export a workspace and open a backup as a separate workspace.

**Also in current source:** library import, local search, revision-checked changes, and linked handoffs, questions and results through MCP. These additions are not automatically included in the desktop download. Preparing work does not start an external agent; a delivery still needs your acceptance. [Details and limits](docs/DEVELOPERS.md).

## Get started

1. **Install.** Download the matching file. On macOS, open the DMG and drag ThreadDesk to Applications; on Windows, open the EXE. Python is included.
2. **Create a thread.** Name your project and add a note or file.
3. **Save your progress.** Save a snapshot and try the backup option under Data.

The interface supports English and German. The macOS app is not Apple-notarized. Backups contain private content and room credentials; externally linked files are not included. Room sharing is local, with no finished Internet service.

Without explicit permission, the optional local AI may not delete your originals, use external services or access secrets. You control the model choice and use of computer resources. [Usage, backups and AI boundaries](docs/DEVELOPERS.md).

## Planned collaboration

The five products remain independent. The goal is a shared workflow with **KiraBridge as the communication hub**:

| Product | Role in the shared workflow |
| --- | --- |
| [ThreadDesk](https://github.com/landjunge/threaddesk/blob/docs/product-family-readme-20261031/README.md) | Keeps project context, knowledge and results. |
| [KiraBridge](https://github.com/landjunge/KiraBridge/blob/docs/product-family-readme-20261031/README.md) | Relays tasks, questions and replies between chat, local agents and tools. |
| [4AllPass](https://github.com/landjunge/4AllPass/blob/docs/product-family-readme-20261031/README.md) | Manages credentials; is intended to enable specifically approved access. |
| [TollGate](https://github.com/landjunge/tollgate/blob/docs/product-family-readme-20261031/README.md) | Checks connected calls and enforces usage limits and stops. |
| [Agent Authority](https://github.com/landjunge/agent-authority-lab/blob/docs/product-family-readme-20261031/README.md) | Shows observations, contradictions and missing evidence; does not approve actions. |

Some interfaces already exist. A fully configured and verified workflow across all five products is still planned. Approvals stay with the responsible tool and the human. KiraBridge and Agent Authority require access to their private repositories.

## License

Private, non-business use is free under the [Netzwerkpunkt Personal Use License 1.0](LICENSE). Business use requires separate written permission. The German text governs; historical license rights remain intact.

Product concept and architecture: **Daniel Filipek (landjunge)**. AI assists with implementation and documentation. Feedback and verifiable reviews are welcome.

[User interface](docs/UI.md) · [Local content search](docs/LOCAL-SEARCH.md) · [MCP and developer documentation](docs/DEVELOPERS.md) · [Product website](https://threaddesk.netzwerkpunkt.de/)
