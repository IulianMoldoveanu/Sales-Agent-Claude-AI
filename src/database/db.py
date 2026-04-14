"""
SQLite database layer.
Handles schema creation and all CRUD operations.
"""

import sqlite3
from datetime import datetime
from typing import Optional

from config import DB_PATH
from src.database.models import Company, JobPosting, LeadScore


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create all tables if they don't exist yet."""
    with _connect() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS companies (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT    NOT NULL,
                country     TEXT    NOT NULL,
                sector      TEXT    NOT NULL,
                website     TEXT,
                city        TEXT,
                size_estimate TEXT,
                source_url  TEXT,
                created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
                UNIQUE(name, country)
            );

            CREATE TABLE IF NOT EXISTS job_postings (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                company_name TEXT    NOT NULL,
                country      TEXT    NOT NULL,
                title        TEXT    NOT NULL,
                sector       TEXT    NOT NULL,
                source_url   TEXT    NOT NULL,
                days_open    INTEGER DEFAULT 0,
                num_openings INTEGER DEFAULT 1,
                is_repeated  INTEGER DEFAULT 0,
                raw_text     TEXT    DEFAULT '',
                scraped_at   TEXT    NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS lead_scores (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                company_name        TEXT    NOT NULL,
                country             TEXT    NOT NULL,
                sector              TEXT    NOT NULL,
                urgency_score       REAL    NOT NULL,
                value_score         REAL    NOT NULL,
                total_score         REAL    NOT NULL,
                open_roles_count    INTEGER DEFAULT 0,
                pitch_angle         TEXT    DEFAULT '',
                recommended_contact TEXT    DEFAULT '',
                scored_at           TEXT    NOT NULL DEFAULT (datetime('now')),
                UNIQUE(company_name, country)
            );
        """)


def upsert_company(company: Company) -> None:
    with _connect() as conn:
        conn.execute("""
            INSERT INTO companies (name, country, sector, website, city, size_estimate, source_url)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(name, country) DO UPDATE SET
                sector        = excluded.sector,
                website       = excluded.website,
                city          = excluded.city,
                size_estimate = excluded.size_estimate,
                source_url    = excluded.source_url
        """, (
            company.name, company.country, company.sector,
            company.website, company.city, company.size_estimate, company.source_url,
        ))


def save_job_posting(posting: JobPosting) -> None:
    with _connect() as conn:
        conn.execute("""
            INSERT INTO job_postings
                (company_name, country, title, sector, source_url,
                 days_open, num_openings, is_repeated, raw_text)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            posting.company_name, posting.country, posting.title,
            posting.sector, posting.source_url, posting.days_open,
            posting.num_openings, int(posting.is_repeated), posting.raw_text,
        ))


def upsert_lead_score(score: LeadScore) -> None:
    with _connect() as conn:
        conn.execute("""
            INSERT INTO lead_scores
                (company_name, country, sector, urgency_score, value_score,
                 total_score, open_roles_count, pitch_angle, recommended_contact,
                 scored_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(company_name, country) DO UPDATE SET
                urgency_score       = excluded.urgency_score,
                value_score         = excluded.value_score,
                total_score         = excluded.total_score,
                open_roles_count    = excluded.open_roles_count,
                pitch_angle         = excluded.pitch_angle,
                recommended_contact = excluded.recommended_contact,
                scored_at           = datetime('now')
        """, (
            score.company_name, score.country, score.sector,
            score.urgency_score, score.value_score, score.total_score,
            score.open_roles_count, score.pitch_angle, score.recommended_contact,
        ))


def get_top_leads(limit: int = 50, min_score: float = 0.0,
                  country: Optional[str] = None,
                  sector: Optional[str] = None) -> list[dict]:
    """Return top leads ordered by total_score descending."""
    query = "SELECT * FROM lead_scores WHERE total_score >= ?"
    params: list = [min_score]
    if country:
        query += " AND country = ?"
        params.append(country.upper())
    if sector:
        query += " AND sector = ?"
        params.append(sector.lower())
    query += " ORDER BY total_score DESC LIMIT ?"
    params.append(limit)

    with _connect() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def get_unscored_companies() -> list[dict]:
    """Return companies that have job postings but no score yet."""
    query = """
        SELECT DISTINCT jp.company_name, jp.country, jp.sector,
               COUNT(jp.id)            AS posting_count,
               MAX(jp.days_open)       AS max_days_open,
               SUM(jp.num_openings)    AS total_openings,
               SUM(jp.is_repeated)     AS repeated_count,
               GROUP_CONCAT(jp.title, ' | ') AS titles
        FROM   job_postings jp
        LEFT JOIN lead_scores ls
            ON jp.company_name = ls.company_name AND jp.country = ls.country
        WHERE  ls.id IS NULL
        GROUP BY jp.company_name, jp.country, jp.sector
    """
    with _connect() as conn:
        rows = conn.execute(query).fetchall()
    return [dict(r) for r in rows]


def get_stats() -> dict:
    """Return summary statistics for the dashboard."""
    with _connect() as conn:
        total_leads   = conn.execute("SELECT COUNT(*) FROM lead_scores").fetchone()[0]
        hot_leads     = conn.execute("SELECT COUNT(*) FROM lead_scores WHERE total_score >= 8").fetchone()[0]
        warm_leads    = conn.execute("SELECT COUNT(*) FROM lead_scores WHERE total_score >= 6 AND total_score < 8").fetchone()[0]
        total_companies = conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
        total_postings  = conn.execute("SELECT COUNT(*) FROM job_postings").fetchone()[0]
        by_country = conn.execute(
            "SELECT country, COUNT(*), AVG(total_score) FROM lead_scores GROUP BY country ORDER BY AVG(total_score) DESC"
        ).fetchall()
        by_sector = conn.execute(
            "SELECT sector, COUNT(*), AVG(total_score) FROM lead_scores GROUP BY sector ORDER BY AVG(total_score) DESC"
        ).fetchall()
    return {
        "total_leads": total_leads,
        "hot_leads": hot_leads,
        "warm_leads": warm_leads,
        "total_companies": total_companies,
        "total_postings": total_postings,
        "by_country": [dict(r) for r in by_country],
        "by_sector":  [dict(r) for r in by_sector],
    }
