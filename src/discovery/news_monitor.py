"""
News monitor module.
Searches for labour-shortage and expansion signals for a given company
using DuckDuckGo's public search (no API key required).

Signals we look for:
  - Company is expanding / opening new sites
  - Company is struggling to hire / "Fachkräftemangel"
  - Company recently won a large contract
  - Company is advertising en-masse across multiple platforms
"""

import time
import re
from urllib.parse import quote_plus

import httpx
from bs4 import BeautifulSoup

from config import REQUEST_TIMEOUT, REQUEST_DELAY

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# Keywords that indicate a company is desperate for workers (any language)
POSITIVE_SIGNALS = [
    "fachkräftemangel", "arbeitskräftemangel", "suchen dringend",
    "labour shortage", "worker shortage", "staff shortage", "hiring urgently",
    "tekort aan personeel", "personeelstekort", "carenza di personale",
    "expanding", "expansion", "new facility", "new plant", "new depot",
    "opening new", "große Auftrag", "major contract", "mass recruitment",
    "hundreds of jobs", "mass hiring",
]

NEGATIVE_SIGNALS = [
    "layoffs", "entlassungen", "redundancies", "closing", "insolvenz",
    "bankruptcy", "faillissement", "fallimento", "reduceri de personal",
]


def search_news_signals(company_name: str, country: str) -> dict:
    """
    Search DuckDuckGo for news about a company and return a signals dict:
    {
        "positive_signals": [...],
        "negative_signals": [...],
        "signal_score": float,   # -1.0 to +1.0
        "snippets": [...],       # raw text snippets found
    }
    A positive signal_score means the company looks like a good prospect.
    """
    query = f'"{company_name}" hiring OR jobs OR workers OR expansion {country}'
    url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"

    snippets: list[str] = []
    try:
        with httpx.Client(headers=HEADERS, timeout=REQUEST_TIMEOUT, follow_redirects=True) as client:
            resp = client.get(url)
            resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        for result in soup.select(".result__snippet")[:10]:
            snippets.append(result.get_text(strip=True))
    except Exception:
        pass

    time.sleep(REQUEST_DELAY)

    combined_text = " ".join(snippets).lower()

    found_positive = [s for s in POSITIVE_SIGNALS if s.lower() in combined_text]
    found_negative = [s for s in NEGATIVE_SIGNALS if s.lower() in combined_text]

    # Signal score: each positive = +0.15, each negative = -0.3, capped [-1, 1]
    raw_score = (len(found_positive) * 0.15) - (len(found_negative) * 0.30)
    signal_score = max(-1.0, min(1.0, raw_score))

    return {
        "positive_signals": found_positive,
        "negative_signals": found_negative,
        "signal_score": signal_score,
        "snippets": snippets[:5],
    }
