from __future__ import annotations

import json

from rich.console import Console
from rich.table import Table

from mem_audit.detectors.base import Finding, Severity, finding_to_dict

_SEVERITY_STYLE = {
    Severity.HIGH: "bold red",
    Severity.MEDIUM: "yellow",
    Severity.LOW: "dim",
}


def print_report(findings: list[Finding], total_memories: int, user_id: str) -> None:
    console = Console()
    console.print(f"\n[bold]mem-audit[/bold] — {user_id} — {total_memories} memories scanned\n")

    if not findings:
        console.print("[green]No duplicates, contradictions, or stale facts found.[/green]")
        return

    by_severity = sorted(findings, key=lambda f: list(Severity).index(f.severity))

    table = Table(show_lines=True)
    table.add_column("Severity")
    table.add_column("Type")
    table.add_column("Summary", overflow="fold")
    table.add_column("Suggested action", overflow="fold")

    for f in by_severity:
        style = _SEVERITY_STYLE.get(f.severity, "")
        table.add_row(
            f"[{style}]{f.severity.value}[/{style}]",
            f.type.value,
            f.summary,
            f.suggested_action or "-",
        )

    console.print(table)
    high = sum(1 for f in findings if f.severity == Severity.HIGH)
    console.print(f"\n[bold]{len(findings)}[/bold] findings ([bold red]{high} high severity[/bold red]).")
    console.print("mem-audit never modifies your memory store. Nothing was changed.")


def export_json(findings: list[Finding], path: str) -> None:
    data = [finding_to_dict(f) for f in findings]
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
