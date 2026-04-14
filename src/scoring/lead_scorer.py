"""
AI-powered lead scoring engine.
Uses Claude (claude-sonnet-4-6) with tool use and prompt caching to evaluate
each company and produce a structured urgency + value score.

Prompt caching is used for the static system context (sector knowledge,
scoring rubric) to reduce token costs on repeated scoring runs.
"""

import json
from datetime import datetime
from typing import Optional

import anthropic

from config import (
    ANTHROPIC_API_KEY, CLAUDE_MODEL, SECTORS, COUNTRY_NAMES,
    URGENCY_WEIGHT, VALUE_WEIGHT, COUNTRY_VALUE_WEIGHT,
)
from src.database.models import LeadScore

# ── Static system prompt (cached) ─────────────────────────────────────────────
_SYSTEM_PROMPT = """You are a senior sales intelligence analyst for a Romanian recruiting agency
that supplies non-EU workers (both qualified and unqualified) to European employers.

Your job is to evaluate a prospective client company and output a precise lead score.

## Scoring Rubric

### Urgency Score (1–10) — How desperate is this company for workers?
- 9–10: Multiple roles open >30 days, repeated postings, known sector shortage, expansion news
- 7–8:  Several roles open >21 days, sector is known to struggle, moderate signals
- 5–6:  A few openings, standard posting age, no special urgency signals
- 3–4:  Single opening, recently posted, no distress signals
- 1–2:  Unclear need, very recent posting, or signals suggest they're not struggling

### Value Score (1–10) — How much revenue can we generate from this client?
- 9–10: Large company (200+ employees), premium sector (construction/manufacturing), high-paying country (DE/NL/AT)
- 7–8:  Medium company (50–200), good sector, good country
- 5–6:  SME, average sector, average country
- 3–4:  Very small company or low-margin sector or low-paying market
- 1–2:  Tiny company unlikely to pay agency fees

### Target Sectors & Revenue Potential
- Construction (DE/AT/NL): HIGHEST fees — qualified workers command €800–1500/placement, unqualified €400–800
- Manufacturing (DE/AT): HIGH fees — welders, CNC operators €600–1200/placement
- Logistics/Warehousing (DE/NL/BE): MEDIUM-HIGH — volume play, €300–600/placement
- Agriculture/Food Processing (NL/BE/DE): MEDIUM — seasonal volume, €200–500/placement
- Hospitality/Cleaning (IT/BE): MEDIUM — high turnover = repeat business, €200–400/placement

### Countries by Fee Potential
Germany: 1.0x | Netherlands: 0.95x | Austria: 0.90x | Belgium: 0.85x | Italy: 0.75x | Romania: 0.50x

## Output Format
Always respond with ONLY a valid JSON object matching this schema:
{
  "urgency_score": <float 1.0–10.0>,
  "value_score": <float 1.0–10.0>,
  "open_roles_count": <integer>,
  "pitch_angle": "<one compelling sentence explaining why we should call this company NOW>",
  "recommended_contact": "<job title of the best person to call, e.g. 'HR Manager', 'Operations Director', 'CEO'>",
  "reasoning": "<2–3 sentences explaining the scores>"
}"""


def score_lead(
    company_name: str,
    country: str,
    sector: str,
    posting_count: int,
    max_days_open: int,
    total_openings: int,
    repeated_count: int,
    job_titles: str,
    news_signals: Optional[dict] = None,
    size_estimate: str = "unknown",
) -> LeadScore:
    """
    Ask Claude to score a lead and return a LeadScore object.
    Uses prompt caching on the static system context.
    """
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    country_name = COUNTRY_NAMES.get(country, country)
    sector_label = SECTORS.get(sector, {}).get("label", sector)

    news_text = ""
    if news_signals and news_signals.get("snippets"):
        positive = ", ".join(news_signals.get("positive_signals", []))
        negative = ", ".join(news_signals.get("negative_signals", []))
        snippets = " | ".join(news_signals.get("snippets", [])[:2])
        news_text = f"""
News signals:
  - Positive indicators: {positive or 'none found'}
  - Negative indicators: {negative or 'none found'}
  - News snippets: {snippets or 'no snippets'}
  - Signal score: {news_signals.get('signal_score', 0):.2f} (-1 = bad, +1 = good)"""

    user_message = f"""Please score this prospective client company:

Company: {company_name}
Country: {country_name} ({country})
Sector: {sector_label}
Company size estimate: {size_estimate}

Job posting data:
  - Total job postings found: {posting_count}
  - Total openings across all postings: {total_openings}
  - Maximum days any posting has been open: {max_days_open}
  - Number of repeated/duplicated postings: {repeated_count}
  - Job titles being advertised: {job_titles}
{news_text}

Based on all of the above, provide your lead score as a JSON object."""

    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=512,
        system=[
            {
                "type": "text",
                "text": _SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},  # cache the static system prompt
            }
        ],
        messages=[
            {"role": "user", "content": user_message}
        ],
    )

    raw = response.content[0].text.strip()

    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    data = json.loads(raw)

    urgency = float(data.get("urgency_score", 5.0))
    value   = float(data.get("value_score", 5.0))

    # Apply country value weight adjustment
    country_weight = COUNTRY_VALUE_WEIGHT.get(country.upper(), 0.70)
    adjusted_value = min(10.0, value * country_weight + value * (1 - country_weight) * 0.5)

    total = round(urgency * URGENCY_WEIGHT + adjusted_value * VALUE_WEIGHT, 2)

    return LeadScore(
        company_name=company_name,
        country=country,
        sector=sector,
        urgency_score=round(urgency, 1),
        value_score=round(adjusted_value, 1),
        total_score=total,
        open_roles_count=int(data.get("open_roles_count", total_openings)),
        pitch_angle=data.get("pitch_angle", ""),
        recommended_contact=data.get("recommended_contact", "HR Manager"),
        scored_at=datetime.utcnow().isoformat(),
    )


def score_batch(unscored_companies: list[dict]) -> list[LeadScore]:
    """
    Score a list of unscored company dicts (as returned by db.get_unscored_companies).
    Returns a list of LeadScore objects.
    """
    scores: list[LeadScore] = []
    for rec in unscored_companies:
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
            scores.append(score)
        except Exception as exc:
            # Log and continue — don't let one bad record break the batch
            print(f"[scorer] Failed to score {rec.get('company_name')}: {exc}")
            continue
    return scores
