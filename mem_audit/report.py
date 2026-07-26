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

# Explicit display order for the report — HIGH first, because the whole point
# of an audit is to surface the findings most likely to cause bad behavior at
# the top. Kept as an explicit map (not the enum declaration order) so that
# reordering the Severity members can never silently flip the report.
_SEVERITY_ORDER = {
    Severity.HIGH: 0,
    Severity.MEDIUM: 1,
    Severity.LOW: 2,
}


def print_report(
    findings: list[Finding], total_memories: int, user_id: str, run_line: str | None = None
) -> None:
    console = Console()
    console.print(f"\n[bold]mem-audit[/bold] — {user_id} — {total_memories} memories scanned\n")

    if not findings:
        console.print("[green]No duplicates, contradictions, or stale facts found.[/green]")
        if run_line:
            console.print(f"[dim]{run_line}[/dim]")
        return

    by_severity = sorted(findings, key=lambda f: _SEVERITY_ORDER.get(f.severity, len(_SEVERITY_ORDER)))

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
    if run_line:
        # One line identifying how this run was produced — models + top-k — so
        # the console output isn't anonymous either. Kept to a single dim line.
        console.print(f"[dim]{run_line}[/dim]")


def export_json(findings: list[Finding], path: str, metadata: dict | None = None) -> None:
    """
    Write findings to `path` as JSON.

    With `metadata`, the file is an object {"metadata": ..., "findings": [...]}
    so a report records how it was produced (see cli.py). Without it, the file
    is a bare findings list (used by library callers that don't track a run).
    """
    findings_data = [finding_to_dict(f) for f in findings]
    payload = {"metadata": metadata, "findings": findings_data} if metadata is not None else findings_data
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
