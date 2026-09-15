"""Static, dependency-free SVG and PDF views of verified knowledge exports."""

from __future__ import annotations

from html import escape
import math
from typing import Any, Mapping

from threaddesk.services.knowledge_export import KnowledgeExportService


WIDTH, HEIGHT = 1000, 700
STATUS_COLOURS = {
    "blocked": "#d66a6a", "rejected": "#d66a6a", "rework": "#d66a6a",
    "done": "#75b798", "accepted": "#75b798", "verified": "#75b798",
    "active": "#6fa8dc", "in_progress": "#6fa8dc", "ready": "#d6b86a",
}


def _positions(nodes: list[Mapping[str, Any]]) -> dict[str, tuple[float, float]]:
    count = max(len(nodes), 1)
    radius = min(245, 90 + count * 12)
    return {
        node["id"]: (
            WIDTH / 2 + math.cos(index * 2 * math.pi / count) * radius,
            HEIGHT / 2 + math.sin(index * 2 * math.pi / count) * radius * .72,
        )
        for index, node in enumerate(nodes)
    }


def _summary(payload: Mapping[str, Any], filters: Mapping[str, str | None], english: bool) -> str:
    selected = payload["selection"]["requested"]
    parts = [f"{len(payload['nodes'])} nodes" if english else f"{len(payload['nodes'])} Knoten"]
    if selected is not None:
        parts.append("selection" if english else "Auswahl")
    for name in ("kind", "status"):
        if filters.get(name):
            parts.append(f"{name}: {filters[name]}")
    return " · ".join(parts)


def encode_svg(
    payload: Mapping[str, Any], *, language: str = "de",
    filters: Mapping[str, str | None] | None = None,
) -> str:
    checked = KnowledgeExportService.verify(payload)
    filters = filters or {}
    english = language == "en"
    positions = _positions(checked["nodes"])
    private = any(node["visibility"] == "private" for node in checked["nodes"])
    title = "ThreadDesk knowledge map" if english else "ThreadDesk-Wissenskarte"
    legend = "Legend: colour = status · line = relation" if english else "Legende: Farbe = Status · Linie = Beziehung"
    privacy = "WARNING: private content included" if english else "WARNUNG: private Inhalte enthalten"
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}" role="img">',
        f"<title>{escape(title)}</title>",
        '<rect width="1000" height="700" fill="#121316"/>',
        f'<text x="40" y="48" fill="#f1f3f5" font-family="sans-serif" font-size="26">{escape(title)}</text>',
        f'<text x="40" y="74" fill="#b6bac3" font-family="sans-serif" font-size="13">{escape(_summary(checked, filters, english))}</text>',
    ]
    for relation in checked["relations"]:
        start, end = positions[relation["source_id"]], positions[relation["target_id"]]
        lines.append(f'<line x1="{start[0]:.1f}" y1="{start[1]:.1f}" x2="{end[0]:.1f}" y2="{end[1]:.1f}" stroke="#777d88" stroke-width="2"/>')
    for node in checked["nodes"]:
        x, y = positions[node["id"]]
        colour = STATUS_COLOURS.get(node["status"], "#9298a3")
        label = node["title"] if len(node["title"]) <= 34 else node["title"][:31] + "…"
        lines.extend([
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="31" fill="#1e1f24" stroke="{colour}" stroke-width="4"/>',
            f'<text x="{x:.1f}" y="{y + 50:.1f}" text-anchor="middle" fill="#f1f3f5" font-family="sans-serif" font-size="14">{escape(label)}</text>',
            f'<text x="{x:.1f}" y="{y + 67:.1f}" text-anchor="middle" fill="#b6bac3" font-family="monospace" font-size="10">{escape(node["id"])}</text>',
        ])
    lines.append(f'<text x="40" y="650" fill="#b6bac3" font-family="sans-serif" font-size="12">{escape(legend)}</text>')
    lines.append(f'<text x="40" y="674" fill="#b6bac3" font-family="sans-serif" font-size="12">{escape(checked["generated_at"])}</text>')
    if private:
        lines.append(f'<text x="960" y="674" text-anchor="end" fill="#d66a6a" font-family="sans-serif" font-size="12">{escape(privacy)}</text>')
    lines.append("</svg>")
    return "\n".join(lines) + "\n"


def _pdf_text(value: Any) -> str:
    raw = str(value).encode("cp1252", "replace").decode("latin-1")
    return raw.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def encode_pdf(
    payload: Mapping[str, Any], *, language: str = "de",
    filters: Mapping[str, str | None] | None = None,
) -> bytes:
    checked = KnowledgeExportService.verify(payload)
    filters = filters or {}
    english = language == "en"
    positions = _positions(checked["nodes"])
    commands = ["0.071 0.075 0.086 rg 0 0 1000 700 re f", "1 1 1 rg BT /F1 24 Tf 40 650 Td"]
    commands.append(f"({_pdf_text('ThreadDesk knowledge map' if english else 'ThreadDesk-Wissenskarte')}) Tj ET")
    commands.extend(["0.72 0.73 0.76 rg BT /F1 12 Tf 40 625 Td", f"({_pdf_text(_summary(checked, filters, english))}) Tj ET"])
    for relation in checked["relations"]:
        a, b = positions[relation["source_id"]], positions[relation["target_id"]]
        commands.append(f"0.47 0.49 0.53 RG 2 w {a[0]:.1f} {700-a[1]:.1f} m {b[0]:.1f} {700-b[1]:.1f} l S")
    for node in checked["nodes"]:
        x, y = positions[node["id"]]
        label = node["title"] if len(node["title"]) <= 34 else node["title"][:31] + "..."
        commands.extend([
            f"0.12 0.12 0.14 rg {x-28:.1f} {700-y-28:.1f} 56 56 re f",
            f"0.95 0.95 0.96 rg BT /F1 12 Tf {x-70:.1f} {700-y-48:.1f} Td ({_pdf_text(label)}) Tj ET",
            f"0.72 0.73 0.76 rg BT /F1 9 Tf {x-55:.1f} {700-y-63:.1f} Td ({_pdf_text(node['id'])}) Tj ET",
        ])
    footer = ("Legend: colour = status; line = relation" if english else "Legende: Farbe = Status; Linie = Beziehung") + " · " + checked["generated_at"]
    commands.append(f"0.72 0.73 0.76 rg BT /F1 10 Tf 40 25 Td ({_pdf_text(footer)}) Tj ET")
    if any(node["visibility"] == "private" for node in checked["nodes"]):
        warning = "WARNING: private content included" if english else "WARNUNG: private Inhalte enthalten"
        commands.append(f"0.84 0.42 0.42 rg BT /F1 10 Tf 760 25 Td ({_pdf_text(warning)}) Tj ET")
    stream = "\n".join(commands).encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 1000 700] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    ]
    result = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for number, obj in enumerate(objects, 1):
        offsets.append(len(result)); result.extend(f"{number} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = len(result)
    result.extend(f"xref\n0 {len(objects)+1}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]: result.extend(f"{offset:010d} 00000 n \n".encode())
    result.extend(f"trailer << /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return bytes(result)
