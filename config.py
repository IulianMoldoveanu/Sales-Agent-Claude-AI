"""
Central configuration for the Sales Agent AI.
Defines target markets, sectors, scoring weights, and search keywords.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ── Anthropic ─────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL: str = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")

# ── Database ──────────────────────────────────────────────────────────────────
DB_PATH: str = os.path.join(os.path.dirname(__file__), "data", "leads.db")

# ── Target countries (ISO-2 codes) ────────────────────────────────────────────
TARGET_COUNTRIES: list[str] = ["DE", "NL", "AT", "BE", "IT", "RO"]

COUNTRY_NAMES: dict[str, str] = {
    "DE": "Germany",
    "NL": "Netherlands",
    "AT": "Austria",
    "BE": "Belgium",
    "IT": "Italy",
    "RO": "Romania",
}

# Fee multiplier per country (relative — higher = better revenue potential)
COUNTRY_VALUE_WEIGHT: dict[str, float] = {
    "DE": 1.0,
    "NL": 0.95,
    "AT": 0.90,
    "BE": 0.85,
    "IT": 0.75,
    "RO": 0.50,
}

# ── Priority sectors ──────────────────────────────────────────────────────────
# Each sector has multilingual search keywords and a revenue-potential score
SECTORS: dict[str, dict] = {
    "construction": {
        "label": "Construction & Real Estate",
        "value_weight": 1.0,
        "keywords": {
            "DE": ["Bauarbeiter", "Maurer", "Gerüstbauer", "Dachdecker", "Fliesenleger", "Bauhilfsarbeiter"],
            "NL": ["bouwvakker", "metselaar", "steigerbouwer", "dakdekker", "tegelzetter"],
            "AT": ["Bauarbeiter", "Maurer", "Gerüstbauer", "Hilfsarbeiter Bau"],
            "BE": ["ouvrier construction", "maçon", "échafaudeur", "couvreur"],
            "IT": ["operaio edile", "muratore", "ponteggiatore", "carpentiere"],
            "RO": ["muncitor constructii", "zidar", "muncitor necalificat constructii"],
        },
    },
    "logistics": {
        "label": "Logistics & Warehousing",
        "value_weight": 0.85,
        "keywords": {
            "DE": ["Lagerarbeiter", "Kommissionierer", "Staplerfahrer", "Lagermitarbeiter", "Versandmitarbeiter"],
            "NL": ["magazijnmedewerker", "orderpicker", "heftruck", "logistiek medewerker"],
            "AT": ["Lagerarbeiter", "Staplerfahrer", "Kommissionierer"],
            "BE": ["magasinier", "cariste", "préparateur de commandes", "logistic operator"],
            "IT": ["magazziniere", "operatore logistica", "mulettista", "addetto magazzino"],
            "RO": ["lucrator depozit", "operator logistica", "stivuitorist"],
        },
    },
    "agriculture": {
        "label": "Agriculture & Food Processing",
        "value_weight": 0.80,
        "keywords": {
            "DE": ["Erntehelfer", "Saisonarbeiter", "Lebensmittelverarbeitung", "Fleischverarbeitung", "Verpackung"],
            "NL": ["plukker", "seizoenarbeider", "voedselverwerkingsindustrie", "inpakker"],
            "AT": ["Erntehelfer", "Saisonarbeiter", "Lebensmittelproduktion"],
            "BE": ["ouvrier agricole", "saisonnier", "travailleur alimentaire"],
            "IT": ["raccoglitore", "lavoratore stagionale", "operaio agroalimentare"],
            "RO": ["muncitor sezonier", "lucrator agricultura", "lucrator abator"],
        },
    },
    "manufacturing": {
        "label": "Manufacturing & Industry",
        "value_weight": 0.90,
        "keywords": {
            "DE": ["Produktionsmitarbeiter", "Schlosser", "Schweißer", "CNC-Bediener", "Maschinenführer"],
            "NL": ["productiemedewerker", "lasser", "CNC-operator", "bankwerker"],
            "AT": ["Produktionsmitarbeiter", "Schlosser", "Schweißer", "Maschinenbediener"],
            "BE": ["opérateur production", "soudeur", "opérateur CNC", "technicien"],
            "IT": ["operaio produzione", "saldatore", "operatore CNC", "tornitore"],
            "RO": ["operator productie", "sudor", "operator CNC", "lacatus mecanic"],
        },
    },
    "hospitality": {
        "label": "Hospitality, Cleaning & Services",
        "value_weight": 0.70,
        "keywords": {
            "DE": ["Reinigungskraft", "Zimmermädchen", "Küchenhilfe", "Servicekraft", "Hauswirtschaft"],
            "NL": ["schoonmaakmedewerker", "keukenmedewerker", "horecamedewerker", "roomservice"],
            "AT": ["Reinigungskraft", "Küchenhilfe", "Servicekraft"],
            "BE": ["agent d'entretien", "aide de cuisine", "serveur", "employé hôtel"],
            "IT": ["addetto pulizie", "aiuto cuoco", "cameriere", "addetto ristorazione"],
            "RO": ["lucrator curatenie", "ajutor bucatar", "ospatar", "camerista"],
        },
    },
}

# ── Scoring weights ───────────────────────────────────────────────────────────
URGENCY_WEIGHT: float = 0.60   # How desperate is the company?
VALUE_WEIGHT: float = 0.40     # How much revenue can we generate?

# Minimum total score (0–10) to consider a lead "warm"
WARM_LEAD_THRESHOLD: float = 6.0
HOT_LEAD_THRESHOLD: float = 8.0

# Number of days a job posting has been open to be considered "urgent"
URGENT_POSTING_DAYS: int = 21

# ── Scraping ──────────────────────────────────────────────────────────────────
REQUEST_TIMEOUT: int = 30       # seconds
REQUEST_DELAY: float = 1.5      # seconds between requests (polite crawling)
MAX_RESULTS_PER_QUERY: int = 50
