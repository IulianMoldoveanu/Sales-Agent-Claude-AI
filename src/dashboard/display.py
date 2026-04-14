"""
Rich terminal dashboard for the Sales Agent AI.
Renders lead tables, stats panels, and progress indicators.
"""

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.columns import Columns
from rich.text import Text
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
from rich import box

from config import HOT_LEAD_THRESHOLD, WARM_LEAD_THRESHOLD, SECTORS, COUNTRY_NAMES

console = Console()


def _score_color(score: float) -> str:
    if score >= HOT_LEAD_THRESHOLD:
        return "bold red"
    if score >= WARM_LEAD_THRESHOLD:
        return "bold yellow"
    return "white"


def _score_badge(score: float) -> str:
    if score >= HOT_LEAD_THRESHOLD:
        return "[bold red]HOT[/bold red]"
    if score >= WARM_LEAD_THRESHOLD:
        return "[bold yellow]WARM[/bold yellow]"
    return "[white]COLD[/white]"


def show_top_leads(leads: list[dict], title: str = "Top Sales Leads") -> None:
    """Render a formatted table of leads."""
    if not leads:
        console.print(Panel("[yellow]No leads found. Run 'discover' first.[/yellow]", title=title))
        return

    table = Table(
        title=title,
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan",
        border_style="blue",
        expand=True,
    )

    table.add_column("#",               style="dim",        width=3,  justify="right")
    table.add_column("Company",         style="bold white", min_width=20)
    table.add_column("Country",         style="cyan",       width=10)
    table.add_column("Sector",          style="magenta",    min_width=14)
    table.add_column("Roles",           style="white",      width=6,  justify="right")
    table.add_column("Urgency",         width=8,  justify="center")
    table.add_column("Value",           width=7,  justify="center")
    table.add_column("Score",           width=7,  justify="center")
    table.add_column("Status",          width=6,  justify="center")
    table.add_column("Best Contact",    style="dim",        min_width=18)
    table.add_column("Pitch",           style="italic",     min_width=30)

    for i, lead in enumerate(leads, start=1):
        score = float(lead.get("total_score", 0))
        urgency = float(lead.get("urgency_score", 0))
        value   = float(lead.get("value_score", 0))
        sector_label = SECTORS.get(lead.get("sector", ""), {}).get("label", lead.get("sector", ""))
        country_name = COUNTRY_NAMES.get(lead.get("country", ""), lead.get("country", ""))

        table.add_row(
            str(i),
            lead.get("company_name", "—"),
            f"{lead.get('country', '?')} {country_name}",
            sector_label,
            str(lead.get("open_roles_count", "?")),
            Text(f"{urgency:.1f}", style=_score_color(urgency)),
            Text(f"{value:.1f}",   style=_score_color(value)),
            Text(f"{score:.1f}",   style=_score_color(score)),
            Text(_score_badge(score)),
            lead.get("recommended_contact", "HR"),
            lead.get("pitch_angle", "")[:80],
        )

    console.print(table)


def show_stats(stats: dict) -> None:
    """Render a stats summary panel."""
    panels = []

    # Lead counts
    counts_text = (
        f"[bold]Total leads:[/bold]    [cyan]{stats.get('total_leads', 0)}[/cyan]\n"
        f"[bold]HOT leads:[/bold]      [red]{stats.get('hot_leads', 0)}[/red]\n"
        f"[bold]WARM leads:[/bold]     [yellow]{stats.get('warm_leads', 0)}[/yellow]\n"
        f"[bold]Companies:[/bold]      [white]{stats.get('total_companies', 0)}[/white]\n"
        f"[bold]Job postings:[/bold]   [white]{stats.get('total_postings', 0)}[/white]"
    )
    panels.append(Panel(counts_text, title="Overview", border_style="blue"))

    # By country
    country_lines = []
    for row in stats.get("by_country", [])[:5]:
        country = COUNTRY_NAMES.get(row.get("country", ""), row.get("country", ""))
        count   = row.get("COUNT(*)", row.get("count", "?"))
        avg     = row.get("AVG(total_score)", row.get("avg", 0))
        color   = _score_color(float(avg) if avg else 0)
        country_lines.append(f"[cyan]{country:<14}[/cyan] {count:>3} leads  [{color}]{float(avg) if avg else 0:.1f} avg[/{color}]")
    panels.append(Panel("\n".join(country_lines) or "No data", title="By Country", border_style="cyan"))

    # By sector
    sector_lines = []
    for row in stats.get("by_sector", [])[:5]:
        sector = SECTORS.get(row.get("sector", ""), {}).get("label", row.get("sector", ""))
        count  = row.get("COUNT(*)", row.get("count", "?"))
        avg    = row.get("AVG(total_score)", row.get("avg", 0))
        color  = _score_color(float(avg) if avg else 0)
        sector_lines.append(f"[magenta]{sector[:18]:<18}[/magenta] {count:>3}  [{color}]{float(avg) if avg else 0:.1f}[/{color}]")
    panels.append(Panel("\n".join(sector_lines) or "No data", title="By Sector", border_style="magenta"))

    console.print(Columns(panels, equal=True, expand=True))


def print_header() -> None:
    console.print(Panel.fit(
        "[bold cyan]Sales Agent Claude AI[/bold cyan]\n"
        "[dim]Romanian Recruiting — Non-EU Worker Placement[/dim]\n"
        "[dim]Target markets: DE · NL · AT · BE · IT · RO[/dim]",
        border_style="cyan",
    ))


def make_progress() -> Progress:
    """Return a Rich Progress bar for long-running operations."""
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        console=console,
    )
