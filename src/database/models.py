"""
Data models for the Sales Agent AI.
Plain dataclasses — no ORM dependency.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Company:
    name: str
    country: str                   # ISO-2 code, e.g. "DE"
    sector: str                    # e.g. "construction"
    website: Optional[str] = None
    city: Optional[str] = None
    size_estimate: Optional[str] = None   # "small", "medium", "large"
    source_url: Optional[str] = None      # where we found this company
    id: Optional[int] = None
    created_at: Optional[str] = None


@dataclass
class JobPosting:
    company_name: str
    country: str
    title: str
    sector: str
    source_url: str
    days_open: int = 0             # estimated days since posted
    num_openings: int = 1          # number of identical roles posted
    is_repeated: bool = False      # same role posted multiple times
    raw_text: str = ""
    id: Optional[int] = None
    scraped_at: Optional[str] = None


@dataclass
class LeadScore:
    company_name: str
    country: str
    sector: str
    urgency_score: float           # 1–10
    value_score: float             # 1–10
    total_score: float             # weighted average
    open_roles_count: int = 0
    pitch_angle: str = ""          # one-line reason to contact them
    recommended_contact: str = ""  # "HR Manager", "Operations Director", etc.
    scored_at: Optional[str] = None
    id: Optional[int] = None

    @classmethod
    def compute_total(cls, urgency: float, value: float) -> float:
        from config import URGENCY_WEIGHT, VALUE_WEIGHT
        return round(urgency * URGENCY_WEIGHT + value * VALUE_WEIGHT, 2)
