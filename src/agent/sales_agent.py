"""
Core Sales Agent orchestrator.
Uses Claude's tool-use loop to coordinate the full discovery → score → save pipeline.

The agent is given four tools:
  1. discover_leads    — scrape job boards for a sector + country
  2. score_company     — ask Claude to score a specific company
  3. save_results      — persist companies, postings, and scores to SQLite
  4. get_top_leads     — retrieve the current top leads from the database

The agent decides which tools to call and in what order based on its instructions.
"""

import json
from typing import Any

import anthropic

from config import ANTHROPIC_API_KEY, CLAUDE_MODEL, SECTORS, TARGET_COUNTRIES
from src.database import db
from src.database.models import Company, JobPosting, LeadScore
from src.discovery.job_board_scraper import discover_leads as _discover_leads
from src.scoring.lead_scorer import score_lead, score_batch

# ── Tool definitions ───────────────────────────────────────────────────────────
TOOLS: list[dict] = [
    {
        "name": "discover_leads",
        "description": (
            "Scrape job boards (StepStone, Indeed) to find companies actively hiring "
            "in a specific sector and country. Returns a summary of companies and "
            "job postings found."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sector": {
                    "type": "string",
                    "description": "Sector to search. One of: construction, logistics, agriculture, manufacturing, hospitality",
                    "enum": list(SECTORS.keys()),
                },
                "country": {
                    "type": "string",
                    "description": "ISO-2 country code to search in. One of: DE, NL, AT, BE, IT, RO",
                    "enum": TARGET_COUNTRIES,
                },
            },
            "required": ["sector", "country"],
        },
    },
    {
        "name": "score_company",
        "description": (
            "Use AI to score the urgency and value of a specific company as a sales lead. "
            "Call this after discovering companies to understand which ones to prioritise."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "company_name":   {"type": "string"},
                "country":        {"type": "string"},
                "sector":         {"type": "string"},
                "posting_count":  {"type": "integer", "description": "Number of job postings found for this company"},
                "max_days_open":  {"type": "integer", "description": "Oldest posting age in days"},
                "total_openings": {"type": "integer", "description": "Total number of open roles"},
                "repeated_count": {"type": "integer", "description": "Number of repeated/duplicate postings"},
                "job_titles":     {"type": "string", "description": "Pipe-separated list of job titles advertised"},
                "size_estimate":  {"type": "string", "description": "small, medium, or large"},
            },
            "required": ["company_name", "country", "sector", "posting_count",
                         "max_days_open", "total_openings", "repeated_count", "job_titles"],
        },
    },
    {
        "name": "save_results",
        "description": "Save discovered companies, job postings, and lead scores to the database.",
        "input_schema": {
            "type": "object",
            "properties": {
                "companies": {
                    "type": "array",
                    "description": "List of company objects to save",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "country": {"type": "string"},
                            "sector": {"type": "string"},
                            "website": {"type": "string"},
                            "city": {"type": "string"},
                            "size_estimate": {"type": "string"},
                            "source_url": {"type": "string"},
                        },
                        "required": ["name", "country", "sector"],
                    },
                },
            },
            "required": ["companies"],
        },
    },
    {
        "name": "get_top_leads",
        "description": "Retrieve the current top-scoring leads from the database.",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit":     {"type": "integer", "default": 10},
                "min_score": {"type": "number",  "default": 6.0},
                "country":   {"type": "string"},
                "sector":    {"type": "string"},
            },
        },
    },
]

# ── In-memory storage for current session's scraped data ─────────────────────
_session_companies: list[Company] = []
_session_postings:  list[JobPosting] = []
_session_scores:    list[LeadScore] = []


def _handle_tool(tool_name: str, tool_input: dict) -> Any:
    """Execute a tool call and return a JSON-serialisable result."""
    global _session_companies, _session_postings, _session_scores

    if tool_name == "discover_leads":
        sector  = tool_input["sector"]
        country = tool_input["country"]
        companies, postings = _discover_leads(sector, country)
        _session_companies.extend(companies)
        _session_postings.extend(postings)

        # Summarise for the agent
        company_summary = {}
        for p in postings:
            key = p.company_name
            if key not in company_summary:
                company_summary[key] = {
                    "company_name": key,
                    "country": p.country,
                    "sector": p.sector,
                    "posting_count": 0,
                    "max_days_open": 0,
                    "total_openings": 0,
                    "repeated_count": 0,
                    "titles": [],
                    "size_estimate": "unknown",
                }
            s = company_summary[key]
            s["posting_count"] += 1
            s["max_days_open"] = max(s["max_days_open"], p.days_open)
            s["total_openings"] += p.num_openings
            if p.is_repeated:
                s["repeated_count"] += 1
            if p.title not in s["titles"]:
                s["titles"].append(p.title)

        # Attach size estimate from company objects
        company_sizes = {c.name: c.size_estimate or "unknown" for c in companies}
        for key, s in company_summary.items():
            s["size_estimate"] = company_sizes.get(key, "unknown")
            s["titles"] = " | ".join(s["titles"][:5])

        return {
            "sector": sector,
            "country": country,
            "companies_found": len(companies),
            "postings_found": len(postings),
            "companies": list(company_summary.values())[:20],
        }

    elif tool_name == "score_company":
        score = score_lead(
            company_name=tool_input["company_name"],
            country=tool_input["country"],
            sector=tool_input["sector"],
            posting_count=tool_input.get("posting_count", 1),
            max_days_open=tool_input.get("max_days_open", 0),
            total_openings=tool_input.get("total_openings", 1),
            repeated_count=tool_input.get("repeated_count", 0),
            job_titles=tool_input.get("job_titles", ""),
            size_estimate=tool_input.get("size_estimate", "unknown"),
        )
        _session_scores.append(score)
        db.upsert_lead_score(score)
        return {
            "company_name":        score.company_name,
            "urgency_score":       score.urgency_score,
            "value_score":         score.value_score,
            "total_score":         score.total_score,
            "pitch_angle":         score.pitch_angle,
            "recommended_contact": score.recommended_contact,
        }

    elif tool_name == "save_results":
        saved = 0
        for c_data in tool_input.get("companies", []):
            company = Company(
                name=c_data["name"],
                country=c_data["country"],
                sector=c_data["sector"],
                website=c_data.get("website"),
                city=c_data.get("city"),
                size_estimate=c_data.get("size_estimate"),
                source_url=c_data.get("source_url"),
            )
            db.upsert_company(company)
            saved += 1
        for p in _session_postings:
            db.save_job_posting(p)
        return {"saved_companies": saved, "saved_postings": len(_session_postings)}

    elif tool_name == "get_top_leads":
        leads = db.get_top_leads(
            limit=tool_input.get("limit", 10),
            min_score=tool_input.get("min_score", 6.0),
            country=tool_input.get("country"),
            sector=tool_input.get("sector"),
        )
        return {"leads": leads, "count": len(leads)}

    return {"error": f"Unknown tool: {tool_name}"}


def run_agent(sector: str, country: str, verbose: bool = True) -> list[LeadScore]:
    """
    Run the full sales agent pipeline for a sector + country.
    Returns the list of LeadScore objects produced in this session.
    """
    global _session_companies, _session_postings, _session_scores
    _session_companies = []
    _session_postings  = []
    _session_scores    = []

    db.init_db()

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    system_prompt = (
        "You are a sales intelligence agent for a Romanian recruiting company. "
        "Your task is to find and score the best companies to approach as clients. "
        f"Focus on sector: {sector}, country: {country}. "
        "Steps: (1) discover leads, (2) score the top 5 most promising companies, "
        "(3) save all results to the database, (4) retrieve and summarise the top leads. "
        "Be efficient — do not score companies with fewer than 2 job postings unless "
        "they show other urgency signals."
    )

    messages = [
        {
            "role": "user",
            "content": (
                f"Run a full lead generation cycle for the '{sector}' sector in {country}. "
                "Discover companies that are hiring, identify the most desperate ones, "
                "score them, save everything, then give me a summary of the best leads to call."
            ),
        }
    ]

    if verbose:
        print(f"\n[agent] Starting pipeline: sector={sector}, country={country}")

    # Agentic loop
    while True:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=4096,
            system=system_prompt,
            tools=TOOLS,
            messages=messages,
        )

        # Collect assistant's response into messages
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            # Agent finished — print its final message
            for block in response.content:
                if hasattr(block, "text") and verbose:
                    print(f"\n[agent] {block.text}")
            break

        if response.stop_reason != "tool_use":
            break

        # Process tool calls
        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            if verbose:
                print(f"[agent] Calling tool: {block.name}({json.dumps(block.input, ensure_ascii=False)[:120]}...)")

            result = _handle_tool(block.name, block.input)

            if verbose:
                summary = json.dumps(result, ensure_ascii=False)[:200]
                print(f"[agent]   → {summary}")

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": json.dumps(result, ensure_ascii=False),
            })

        messages.append({"role": "user", "content": tool_results})

    return _session_scores
