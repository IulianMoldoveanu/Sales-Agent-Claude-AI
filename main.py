#!/usr/bin/env python3
"""
Sales Agent Claude AI — Entry Point
Romanian Recruiting: Non-EU Worker Placement

Usage:
  python main.py run      --sector construction --country DE   # Full pipeline
  python main.py discover --sector logistics    --country NL   # Discovery only
  python main.py score                                          # Score unscored leads
  python main.py leads    [--country DE] [--sector construction] [--min-score 6]
  python main.py stats                                          # Dashboard summary
  python main.py export   [--output leads.csv]                  # Export to CSV
"""

import sys
import csv
import os
import argparse
from typing import Optional

from config import SECTORS, TARGET_COUNTRIES, WARM_LEAD_THRESHOLD
from src.database import db
from src.dashboard.display import console, print_header, show_top_leads, show_stats, make_progress


def cmd_run(sector: str, country: str) -> None:
    """Full pipeline: discover → score → display."""
    from src.agent.sales_agent import run_agent

    print_header()
    console.print(f"\n[cyan]Running full pipeline:[/cyan] sector=[bold]{sector}[/bold], country=[bold]{country}[/bold]\n")

    scores = run_agent(sector=sector, country=country, verbose=True)

    console.print(f"\n[green]Pipeline complete.[/green] Scored [bold]{len(scores)}[/bold] companies.\n")

    leads = db.get_top_leads(limit=20, min_score=0.0, country=country, sector=sector)
    show_top_leads(leads, title=f"Results — {sector.title()} / {country}")


def cmd_discover(sector: str, country: str) -> None:
    """Discovery only — scrape job boards and save to database."""
    from src.discovery.job_board_scraper import discover_leads

    print_header()
    db.init_db()

    sector_label = SECTORS.get(sector, {}).get("label", sector)
    console.print(f"\n[cyan]Discovering leads:[/cyan] {sector_label} in {country}\n")

    with make_progress() as progress:
        task = progress.add_task(f"Scraping job boards for {sector} / {country}...", total=None)
        companies, postings = discover_leads(sector=sector, country=country)
        progress.update(task, completed=True)

    for company in companies:
        db.upsert_company(company)
    for posting in postings:
        db.save_job_posting(posting)

    console.print(f"[green]Found[/green] [bold]{len(companies)}[/bold] companies, "
                  f"[bold]{len(postings)}[/bold] job postings.")
    console.print("[dim]Run 'python main.py score' to score these leads.[/dim]\n")


def cmd_score() -> None:
    """Score all unscored companies in the database."""
    from src.scoring.lead_scorer import score_batch

    print_header()
    db.init_db()

    unscored = db.get_unscored_companies()
    if not unscored:
        console.print("[yellow]No unscored companies found. Run 'discover' first.[/yellow]")
        return

    console.print(f"\n[cyan]Scoring[/cyan] [bold]{len(unscored)}[/bold] companies with Claude AI...\n")

    with make_progress() as progress:
        task = progress.add_task("Scoring leads...", total=len(unscored))
        scored = 0
        for rec in unscored:
            from src.scoring.lead_scorer import score_lead
            try:
                score = score_lead(
                    company_name=rec["company_name"],
                    country=rec["country"],
                    sector=rec["sector"],
                    posting_count=int(rec.get("posting_count", 1)),
                    max_days_open=int(rec.get("max_days_open", 0)),
                    total_openings=int(rec.get("total_openings", 1)),
                    repeated_count=int(rec.get("repeated_count", 0)),
                    job_titles=rec.get("titles", ""),
                )
                db.upsert_lead_score(score)
                scored += 1
            except Exception as exc:
                console.print(f"[red]Error scoring {rec.get('company_name')}:[/red] {exc}")
            finally:
                progress.advance(task)

    console.print(f"\n[green]Scored[/green] [bold]{scored}[/bold] companies successfully.\n")

    hot = db.get_top_leads(limit=5, min_score=8.0)
    if hot:
        console.print(f"[bold red]TOP HOT LEADS ({len(hot)} companies with score ≥ 8.0):[/bold red]")
        show_top_leads(hot, title="Hot Leads")


def cmd_leads(country: Optional[str], sector: Optional[str], min_score: float) -> None:
    """Display top leads from the database."""
    print_header()
    db.init_db()

    leads = db.get_top_leads(limit=50, min_score=min_score, country=country, sector=sector)
    title = "Top Leads"
    if country:
        title += f" — {country}"
    if sector:
        title += f" / {sector.title()}"
    show_top_leads(leads, title=title)


def cmd_stats() -> None:
    """Show dashboard statistics."""
    print_header()
    db.init_db()

    stats = db.get_stats()
    show_stats(stats)


def cmd_export(output_path: str) -> None:
    """Export all leads to a CSV file."""
    db.init_db()

    leads = db.get_top_leads(limit=10000, min_score=0.0)
    if not leads:
        console.print("[yellow]No leads to export.[/yellow]")
        return

    fieldnames = [
        "company_name", "country", "sector", "urgency_score", "value_score",
        "total_score", "open_roles_count", "pitch_angle", "recommended_contact", "scored_at",
    ]

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(leads)

    console.print(f"[green]Exported[/green] [bold]{len(leads)}[/bold] leads to [cyan]{output_path}[/cyan]")


# ── CLI parser ─────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Sales Agent Claude AI — Recruiting Lead Generation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # run
    p_run = sub.add_parser("run", help="Full pipeline: discover, score, and display leads")
    p_run.add_argument("--sector",  required=True, choices=list(SECTORS.keys()), help="Industry sector")
    p_run.add_argument("--country", required=True, choices=TARGET_COUNTRIES,    help="ISO-2 country code")

    # discover
    p_disc = sub.add_parser("discover", help="Scrape job boards and save companies/postings")
    p_disc.add_argument("--sector",  required=True, choices=list(SECTORS.keys()))
    p_disc.add_argument("--country", required=True, choices=TARGET_COUNTRIES)

    # score
    sub.add_parser("score", help="Score all unscored companies in the database")

    # leads
    p_leads = sub.add_parser("leads", help="Display top leads")
    p_leads.add_argument("--country",   choices=TARGET_COUNTRIES, default=None)
    p_leads.add_argument("--sector",    choices=list(SECTORS.keys()), default=None)
    p_leads.add_argument("--min-score", type=float, default=WARM_LEAD_THRESHOLD)

    # stats
    sub.add_parser("stats", help="Show summary statistics")

    # export
    p_export = sub.add_parser("export", help="Export leads to CSV")
    p_export.add_argument("--output", default="leads.csv")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if not os.getenv("ANTHROPIC_API_KEY") and args.command in ("run", "score"):
        console.print(
            "[bold red]Error:[/bold red] ANTHROPIC_API_KEY is not set.\n"
            "Copy [cyan].env.example[/cyan] to [cyan].env[/cyan] and add your key."
        )
        sys.exit(1)

    if args.command == "run":
        cmd_run(args.sector, args.country)
    elif args.command == "discover":
        cmd_discover(args.sector, args.country)
    elif args.command == "score":
        cmd_score()
    elif args.command == "leads":
        cmd_leads(args.country, args.sector, args.min_score)
    elif args.command == "stats":
        cmd_stats()
    elif args.command == "export":
        cmd_export(args.output)


if __name__ == "__main__":
    main()
