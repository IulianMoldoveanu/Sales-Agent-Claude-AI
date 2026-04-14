"""
Job board scraper module.
Fetches job listings from StepStone and Indeed to discover companies
that are actively hiring — the primary signal of labour shortage.

Designed to be polite: respects delays between requests and does not
hammer servers. Results are normalised into Company + JobPosting objects.
"""

import asyncio
import time
import re
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urlencode, quote_plus

import httpx
from bs4 import BeautifulSoup

from config import (
    REQUEST_TIMEOUT, REQUEST_DELAY, MAX_RESULTS_PER_QUERY,
    URGENT_POSTING_DAYS, SECTORS, COUNTRY_NAMES,
)
from src.database.models import Company, JobPosting

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# StepStone country domains
STEPSTONE_DOMAINS: dict[str, str] = {
    "DE": "www.stepstone.de",
    "AT": "www.stepstone.at",
    "BE": "www.stepstone.be",
    "NL": "www.stepstone.nl",
    "IT": "www.stepstone.it",
}

# Indeed country domains
INDEED_DOMAINS: dict[str, str] = {
    "DE": "de.indeed.com",
    "AT": "at.indeed.com",
    "BE": "be.indeed.com",
    "NL": "nl.indeed.com",
    "IT": "it.indeed.com",
    "RO": "ro.indeed.com",
}


def _parse_days_ago(text: str) -> int:
    """Convert a 'posted X days ago' string into an integer number of days."""
    text = text.lower().strip()
    if "heute" in text or "today" in text or "vandaag" in text or "oggi" in text:
        return 0
    if "gestern" in text or "yesterday" in text or "gisteren" in text or "ieri" in text:
        return 1
    match = re.search(r"(\d+)\s*(tag|day|dag|giorn)", text)
    if match:
        return int(match.group(1))
    # If we can't parse, assume moderate urgency (14 days)
    return 14


def _extract_company_size(description: str) -> str:
    """Heuristic: estimate company size from job description keywords."""
    text = description.lower()
    if any(w in text for w in ["konzern", "multinational", "international group", "listed", "börsennotiert"]):
        return "large"
    if any(w in text for w in ["mittelstand", "kmu", "sme", "medium", "regional"]):
        return "medium"
    return "small"


def scrape_stepstone(country: str, keywords: list[str],
                     sector: str, max_results: int = MAX_RESULTS_PER_QUERY
                     ) -> tuple[list[Company], list[JobPosting]]:
    """
    Scrape StepStone for job listings matching keywords in a given country.
    Returns (companies, job_postings).
    """
    domain = STEPSTONE_DOMAINS.get(country.upper())
    if not domain:
        return [], []

    companies: dict[str, Company] = {}
    postings: list[JobPosting] = []

    with httpx.Client(headers=HEADERS, timeout=REQUEST_TIMEOUT, follow_redirects=True) as client:
        for keyword in keywords[:3]:   # limit keywords per run to avoid bans
            params = {"q": keyword, "location": "", "p": 1}
            url = f"https://{domain}/jobs/{quote_plus(keyword)}"
            try:
                resp = client.get(url, params={"p": 1})
                resp.raise_for_status()
            except (httpx.HTTPError, httpx.TimeoutException):
                time.sleep(REQUEST_DELAY)
                continue

            soup = BeautifulSoup(resp.text, "lxml")

            # StepStone uses article[data-at="job-item"] or similar selectors
            job_cards = (
                soup.select("article[data-at='job-item']") or
                soup.select("article.sc-beySPh") or
                soup.select("[data-testid='job-item']") or
                soup.select("article")
            )

            for card in job_cards[:max_results]:
                try:
                    title_el = (
                        card.select_one("[data-at='job-item-title']") or
                        card.select_one("h2") or
                        card.select_one(".job-title")
                    )
                    company_el = (
                        card.select_one("[data-at='job-item-company-name']") or
                        card.select_one(".company-name") or
                        card.select_one("[class*='company']")
                    )
                    date_el = (
                        card.select_one("[data-at='job-item-date']") or
                        card.select_one("time") or
                        card.select_one("[class*='date']")
                    )
                    link_el = card.select_one("a[href]")

                    title = title_el.get_text(strip=True) if title_el else keyword
                    company_name = company_el.get_text(strip=True) if company_el else "Unknown"
                    if not company_name or company_name == "Unknown":
                        continue

                    days_open = _parse_days_ago(date_el.get_text(strip=True)) if date_el else 14
                    source_url = f"https://{domain}" + link_el["href"] if link_el else url

                    # Build / update company record
                    key = f"{company_name}_{country}"
                    if key not in companies:
                        companies[key] = Company(
                            name=company_name,
                            country=country.upper(),
                            sector=sector,
                            source_url=source_url,
                            size_estimate=_extract_company_size(card.get_text()),
                        )

                    # Build job posting
                    postings.append(JobPosting(
                        company_name=company_name,
                        country=country.upper(),
                        title=title,
                        sector=sector,
                        source_url=source_url,
                        days_open=days_open,
                        num_openings=1,
                        is_repeated=False,
                        raw_text=card.get_text(separator=" ", strip=True)[:500],
                    ))
                except Exception:
                    continue

            time.sleep(REQUEST_DELAY)

    # Detect repeated postings (same company, same sector, multiple listings)
    company_posting_counts: dict[str, int] = {}
    for p in postings:
        company_posting_counts[p.company_name] = company_posting_counts.get(p.company_name, 0) + 1
    for p in postings:
        if company_posting_counts[p.company_name] > 2:
            p.is_repeated = True
            p.num_openings = company_posting_counts[p.company_name]

    return list(companies.values()), postings


def scrape_indeed(country: str, keywords: list[str],
                  sector: str, max_results: int = MAX_RESULTS_PER_QUERY
                  ) -> tuple[list[Company], list[JobPosting]]:
    """
    Scrape Indeed for job listings matching keywords in a given country.
    Returns (companies, job_postings).
    """
    domain = INDEED_DOMAINS.get(country.upper())
    if not domain:
        return [], []

    companies: dict[str, Company] = {}
    postings: list[JobPosting] = []

    with httpx.Client(headers=HEADERS, timeout=REQUEST_TIMEOUT, follow_redirects=True) as client:
        for keyword in keywords[:3]:
            params = {"q": keyword, "l": "", "start": 0}
            url = f"https://{domain}/jobs?" + urlencode(params)
            try:
                resp = client.get(url)
                resp.raise_for_status()
            except (httpx.HTTPError, httpx.TimeoutException):
                time.sleep(REQUEST_DELAY)
                continue

            soup = BeautifulSoup(resp.text, "lxml")

            job_cards = (
                soup.select("div.job_seen_beacon") or
                soup.select("[data-jk]") or
                soup.select(".jobsearch-ResultsList > li")
            )

            for card in job_cards[:max_results]:
                try:
                    title_el = (
                        card.select_one("h2.jobTitle span") or
                        card.select_one(".jobTitle") or
                        card.select_one("h2")
                    )
                    company_el = (
                        card.select_one("[data-testid='company-name']") or
                        card.select_one(".companyName") or
                        card.select_one("[class*='company']")
                    )
                    date_el = (
                        card.select_one("[data-testid='myJobsStateDate']") or
                        card.select_one(".date") or
                        card.select_one("span[class*='date']")
                    )
                    link_el = card.select_one("a[id^='job_']") or card.select_one("a[href*='/rc/clk']")

                    title = title_el.get_text(strip=True) if title_el else keyword
                    company_name = company_el.get_text(strip=True) if company_el else "Unknown"
                    if not company_name or company_name == "Unknown":
                        continue

                    days_open = _parse_days_ago(date_el.get_text(strip=True)) if date_el else 14
                    href = link_el.get("href", "") if link_el else ""
                    source_url = f"https://{domain}{href}" if href.startswith("/") else href or url

                    key = f"{company_name}_{country}"
                    if key not in companies:
                        companies[key] = Company(
                            name=company_name,
                            country=country.upper(),
                            sector=sector,
                            source_url=source_url,
                            size_estimate=_extract_company_size(card.get_text()),
                        )

                    postings.append(JobPosting(
                        company_name=company_name,
                        country=country.upper(),
                        title=title,
                        sector=sector,
                        source_url=source_url,
                        days_open=days_open,
                        num_openings=1,
                        is_repeated=False,
                        raw_text=card.get_text(separator=" ", strip=True)[:500],
                    ))
                except Exception:
                    continue

            time.sleep(REQUEST_DELAY)

    # Mark repeated postings
    counts: dict[str, int] = {}
    for p in postings:
        counts[p.company_name] = counts.get(p.company_name, 0) + 1
    for p in postings:
        if counts[p.company_name] > 2:
            p.is_repeated = True
            p.num_openings = counts[p.company_name]

    return list(companies.values()), postings


def discover_leads(sector: str, country: str,
                   max_results: int = MAX_RESULTS_PER_QUERY
                   ) -> tuple[list[Company], list[JobPosting]]:
    """
    Unified entry point: run both StepStone and Indeed scrapers for a given
    sector + country combination, merge and deduplicate results.
    """
    sector_cfg = SECTORS.get(sector.lower())
    if not sector_cfg:
        return [], []

    keywords = sector_cfg["keywords"].get(country.upper(), [])
    if not keywords:
        return [], []

    all_companies: dict[str, Company] = {}
    all_postings: list[JobPosting] = []

    ss_companies, ss_postings = scrape_stepstone(country, keywords, sector, max_results)
    for c in ss_companies:
        all_companies[f"{c.name}_{c.country}"] = c
    all_postings.extend(ss_postings)

    time.sleep(REQUEST_DELAY)

    ind_companies, ind_postings = scrape_indeed(country, keywords, sector, max_results)
    for c in ind_companies:
        key = f"{c.name}_{c.country}"
        if key not in all_companies:
            all_companies[key] = c
    all_postings.extend(ind_postings)

    return list(all_companies.values()), all_postings
