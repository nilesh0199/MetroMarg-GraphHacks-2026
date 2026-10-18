import sys
from textwrap import dedent

try:
    sys.stdout.reconfigure(encoding="utf-8")  # so boxes and symbols print on Windows
except Exception:
    pass

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from agent import ask, TRACE, RESULTS, QUERIES

import logging
logging.getLogger("google_genai").setLevel(logging.ERROR)  # hide the AFC notice

console = Console()


def route_panel(r):
    t = Table(header_style="bold")
    t.add_column("Option")
    t.add_column("Route")
    t.add_column("Minutes", justify="right")
    t.add_row("Normal", " → ".join(r["normal"]["via"]), str(r["normal"]["minutes"]))
    if "detour" in r:
        t.add_row("While closed", " → ".join(r["detour"]["via"]),
                  f"{r['detour']['minutes']} [yellow](+{r['extra_minutes']})[/]")
    return Panel(t, title=f"🚇 {r['from']} to {r['to']}", border_style="green")


def impact_panel(r):
    t = Table(header_style="bold")
    t.add_column("Station")
    t.add_column("Hops", justify="right")
    t.add_column("Route")
    for a in sorted(r["affected"], key=lambda a: (a["hops"], a["station"])):
        t.add_row(a["station"], str(a["hops"]), " → ".join(a["via"]))
    return Panel(t, title=f"⚠️ Within {r['depth']} hop(s) of {r['station']}",
                 border_style="yellow")


def place_panel(r):
    t = Table(header_style="bold")
    t.add_column("Station")
    t.add_column("Walk", justify="right")
    t.add_column("Status")
    for s in r["stations"]:
        status = "[red]✘ closed[/]" if s["closed"] else "[green]✔ open[/]"
        t.add_row(s["station"], f"{s['walk_min']} min", status)
    return Panel(t, title=f"📍 Stations near {r['place']}", border_style="green")


def trip_panel(r):
    def row(label, o):
        route = " → ".join(o["via"]) + f" → walk to {r['place']}"
        return (label, route, f"{o['minutes']} ({o['ride']} ride + {o['walk']} walk)")

    t = Table(header_style="bold")
    t.add_column("Option")
    t.add_column("Route")
    t.add_column("Minutes", justify="right")
    t.add_row(*row("Normal", r["normal"]))
    if "detour" in r:
        label, route, mins = row("While closed", r["detour"])
        t.add_row(label, route, f"{mins} [yellow](+{r['extra_minutes']})[/]")
    else:
        t.add_row("While closed", "[red]no route found[/]", "")
    return Panel(t, title=f"📍 {r['from']} to {r['place']}", border_style="green")


def other_panel(r):
    detail = r.get("note") or r.get("asked") or r.get("closed") or ""
    text = f"{r.get('outcome')}: {detail}" if detail else str(r.get("outcome"))
    return Panel(Text(text), title="Result", border_style="red")


def result_panels():
    for r in RESULTS:
        if "normal" in r and "place" in r:
            yield trip_panel(r)
        elif "normal" in r:
            yield route_panel(r)
        elif "affected" in r:
            yield impact_panel(r)
        elif "stations" in r:
            yield place_panel(r)
        else:
            yield other_panel(r)


def queries_panel():
    seen, blocks = set(), []
    for q, params in QUERIES:
        text = dedent(q).strip()
        if text in seen:
            continue
        seen.add(text)
        blocks.append(text + (f"\n// params: {params}" if params else ""))
    if not blocks:
        return None
    return Panel(Syntax("\n\n".join(blocks), "cypher", theme="monokai", word_wrap=True),
                 title="🔎 The graph queries behind this answer", border_style="grey62")


if __name__ == "__main__":
    console.print("[bold]Metro disruption agent[/] (empty line to quit)")
    while True:
        q = console.input("\n[bold cyan]you ›[/] ").strip()
        if not q:
            break
        with console.status("Walking the graph..."):
            answer = ask(q)

        for p in result_panels():
            console.print(p)
        # Text() keeps square brackets in the answer from being read as styling
        console.print(Panel(Text(answer), title="👑 MetroMarg", border_style="yellow"))
        for t in TRACE:
            console.print(f"[dim]{t['tool']}{t['args']} · {t['ms']} ms → {t['outcome']}[/]")
        qp = queries_panel()
        if qp:
            console.print(qp)
