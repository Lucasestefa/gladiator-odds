"""
BetScan — Signals API
Mock data rico para MVP y demos. Simula value bets reales con rotación.
"""
import time
import random
from typing import List, Optional
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


# ========== SCHEMAS ==========

class TeamInfo(BaseModel):
    code: str
    fullName: Optional[str] = None
    record: Optional[str] = None
    probability: float
    odds: float


class ValueEdge(BaseModel):
    side: str
    percent: float
    bookmaker: str


class FeaturedMatch(BaseModel):
    id: str
    sport: str
    competition: str
    stage: str
    kickoff: str
    home: TeamInfo
    away: TeamInfo
    valueEdge: ValueEdge


class SecondaryMatch(BaseModel):
    id: str
    sport: str
    meta: str
    label: str
    homeCode: str
    awayCode: str
    homeProb: float
    awayProb: float
    homeOdds: float
    awayOdds: float
    valueEdgePercent: float


# ========== MOCK POOL ==========

BOOKMAKERS = ["Pinnacle", "Bet365", "Betfair", "1xBet", "Winamax", "Unibet", "Betway", "Bwin"]

# Pool rico de partidos realistas
MATCH_POOL = [
    # Football — UCL
    {"sport": "football", "comp": "Champions League", "stage": "Quarterfinal", "home": ("Real Madrid", "RMA", "27-7-4"), "away": ("Arsenal", "ARS", "24-8-6"), "base_odds": (1.92, 2.08), "edge": 8.4},
    {"sport": "football", "comp": "Champions League", "stage": "Semifinal", "home": ("PSG", "PSG", "22-9-7"), "away": ("Liverpool", "LIV", "26-6-6"), "base_odds": (2.45, 1.68), "edge": 5.1},
    {"sport": "football", "comp": "Champions League", "stage": "Semifinal", "home": ("Bayern Munich", "BAY", "28-6-4"), "away": ("Man City", "MCI", "25-8-5"), "base_odds": (1.85, 2.15), "edge": 6.9},
    # Football — EPL
    {"sport": "football", "comp": "Premier League", "stage": "Matchday 34", "home": ("Manchester United", "MUN", "19-11-8"), "away": ("Chelsea", "CHE", "20-10-8"), "base_odds": (2.20, 1.80), "edge": 4.2},
    {"sport": "football", "comp": "Premier League", "stage": "Matchday 34", "home": ("Tottenham", "TOT", "21-9-8"), "away": ("Newcastle", "NEW", "18-12-8"), "base_odds": (1.95, 2.05), "edge": 3.8},
    # Football — La Liga
    {"sport": "football", "comp": "La Liga", "stage": "Jornada 32", "home": ("Barcelona", "BAR", "25-8-5"), "away": ("Atlético Madrid", "ATM", "22-10-6"), "base_odds": (1.75, 2.30), "edge": 7.2},
    {"sport": "football", "comp": "La Liga", "stage": "Jornada 32", "home": ("Sevilla", "SEV", "15-15-8"), "away": ("Valencia", "VAL", "16-14-8"), "base_odds": (2.10, 1.90), "edge": 2.9},
    # Football — Serie A
    {"sport": "football", "comp": "Serie A", "stage": "Giornata 33", "home": ("Inter", "INT", "26-7-5"), "away": ("Juventus", "JUV", "22-9-7"), "base_odds": (1.68, 2.45), "edge": 6.3},
    {"sport": "football", "comp": "Serie A", "stage": "Giornata 33", "home": ("AC Milan", "MIL", "23-8-7"), "away": ("Napoli", "NAP", "21-10-7"), "base_odds": (2.00, 2.00), "edge": 4.7},
    # Football — Primera Argentina
    {"sport": "football", "comp": "Primera Argentina", "stage": "Fecha 12", "home": ("Boca Juniors", "BOC", "8-2-2"), "away": ("River Plate", "RIV", "7-3-2"), "base_odds": (2.35, 2.10), "edge": 4.9},
    {"sport": "football", "comp": "Primera Argentina", "stage": "Fecha 12", "home": ("Racing", "RAC", "7-3-2"), "away": ("Independiente", "IND", "5-4-3"), "base_odds": (1.85, 2.15), "edge": 5.5},
    # Football — Libertadores
    {"sport": "football", "comp": "Copa Libertadores", "stage": "Octavos", "home": ("Palmeiras", "PAL", "6-2-0"), "away": ("Flamengo", "FLA", "5-2-1"), "base_odds": (2.05, 1.95), "edge": 3.4},
    # Basketball — NBA
    {"sport": "basketball", "comp": "NBA Playoffs", "stage": "Conference Semis", "home": ("Celtics", "BOS", "64-18"), "away": ("Knicks", "NYK", "52-30"), "base_odds": (1.72, 2.05), "edge": 6.7},
    {"sport": "basketball", "comp": "NBA Playoffs", "stage": "Conference Semis", "home": ("Nuggets", "DEN", "58-24"), "away": ("Lakers", "LAL", "50-32"), "base_odds": (1.55, 2.45), "edge": 5.8},
    {"sport": "basketball", "comp": "NBA Playoffs", "stage": "Conference Semis", "home": ("Warriors", "GSW", "54-28"), "away": ("Thunder", "OKC", "56-26"), "base_odds": (2.20, 1.75), "edge": 4.3},
    # Tennis — ATP
    {"sport": "tennis", "comp": "Madrid Open", "stage": "Semifinal", "home": ("Carlos Alcaraz", "ALC", "42-10"), "away": ("Jannik Sinner", "SIN", "40-12"), "base_odds": (1.75, 2.15), "edge": 5.2},
    {"sport": "tennis", "comp": "Madrid Open", "stage": "Quarterfinal", "home": ("Novak Djokovic", "DJO", "38-11"), "away": ("Daniil Medvedev", "MED", "35-14"), "base_odds": (1.60, 2.35), "edge": 4.8},
    # Hockey — NHL
    {"sport": "hockey", "comp": "NHL Playoffs", "stage": "Round 2", "home": ("Oilers", "EDM", "52-28-2"), "away": ("Avalanche", "COL", "50-30-2"), "base_odds": (1.95, 1.90), "edge": 5.9},
    {"sport": "hockey", "comp": "NHL Playoffs", "stage": "Round 2", "home": ("Maple Leafs", "TOR", "48-32-2"), "away": ("Bruins", "BOS", "51-29-2"), "base_odds": (2.10, 1.75), "edge": 4.1},
    # Baseball — MLB
    {"sport": "baseball", "comp": "MLB", "stage": "Regular Season", "home": ("Dodgers", "LAD", "65-40"), "away": ("Yankees", "NYY", "62-43"), "base_odds": (1.88, 2.00), "edge": 4.5},
    {"sport": "baseball", "comp": "MLB", "stage": "Regular Season", "home": ("Astros", "HOU", "58-47"), "away": ("Rangers", "TEX", "54-51"), "base_odds": (1.70, 2.25), "edge": 3.7},
    # MMA — UFC
    {"sport": "mma", "comp": "UFC 310", "stage": "Main Event", "home": ("Islam Makhachev", "MAK", "26-1"), "away": ("Charles Oliveira", "OLI", "34-10"), "base_odds": (1.45, 2.75), "edge": 3.1},
    # NFL
    {"sport": "nfl", "comp": "NFL", "stage": "Week 17", "home": ("Chiefs", "KC", "13-3"), "away": ("49ers", "SF", "11-5"), "base_odds": (1.80, 2.10), "edge": 5.6},
]


# ========== HELPERS ==========

def _now_bucket() -> int:
    """Bucket de 30 segundos para rotar data en forma determinística."""
    return int(time.time() // 30)


def _kickoff_str(minutes_ahead: int) -> str:
    """Genera kickoff realista."""
    if minutes_ahead < 0:
        return "LIVE · En juego"
    if minutes_ahead < 60:
        return f"En {minutes_ahead}m"
    if minutes_ahead < 180:
        h = minutes_ahead // 60
        m = minutes_ahead % 60
        return f"En {h}h {m}m"
    return f"Hoy {(20 + (minutes_ahead // 60) % 4):02d}:00"


def _build_match_variant(idx: int, bucket: int) -> dict:
    """Construye una variante dinámica de un partido del pool."""
    base = MATCH_POOL[idx % len(MATCH_POOL)]
    rng = random.Random(bucket + idx)

    home_name, home_code, home_rec = base["home"]
    away_name, away_code, away_rec = base["away"]
    home_odds_base, away_odds_base = base["base_odds"]

    # Pequeña variación en odds (±3%)
    home_odds = round(home_odds_base * (1 + rng.uniform(-0.03, 0.03)), 2)
    away_odds = round(away_odds_base * (1 + rng.uniform(-0.03, 0.03)), 2)

    # Probabilidades inversas al odds, normalizadas
    p_home_raw = 1 / home_odds
    p_away_raw = 1 / away_odds
    total = p_home_raw + p_away_raw
    p_home = round((p_home_raw / total) * 100, 1)
    p_away = round((p_away_raw / total) * 100, 1)

    # Edge con variación mínima
    edge = round(base["edge"] + rng.uniform(-0.8, 0.8), 1)
    edge_side = "home" if p_home >= p_away else "away"
    bookmaker = rng.choice(BOOKMAKERS)

    # Kickoff aleatorio
    minutes_ahead = rng.choice([-30, -15, 15, 30, 59, 90, 150, 300])

    return {
        "id": f"{base['sport']}-{home_code.lower()}-{away_code.lower()}-b{bucket}",
        "base": base,
        "home_name": home_name,
        "home_code": home_code,
        "home_rec": home_rec,
        "away_name": away_name,
        "away_code": away_code,
        "away_rec": away_rec,
        "home_odds": home_odds,
        "away_odds": away_odds,
        "p_home": p_home,
        "p_away": p_away,
        "edge": edge,
        "edge_side": edge_side,
        "bookmaker": bookmaker,
        "kickoff": _kickoff_str(minutes_ahead),
    }


def _build_featured(bucket: int) -> FeaturedMatch:
    # Featured rota cada 30s eligiendo uno con edge alto (> 5)
    candidates = [i for i, m in enumerate(MATCH_POOL) if m["edge"] >= 5]
    idx = candidates[bucket % len(candidates)]
    v = _build_match_variant(idx, bucket)

    return FeaturedMatch(
        id=v["id"],
        sport=v["base"]["sport"],
        competition=v["base"]["comp"],
        stage=v["base"]["stage"],
        kickoff=v["kickoff"],
        home=TeamInfo(
            code=v["home_code"],
            fullName=v["home_name"],
            record=v["home_rec"],
            probability=v["p_home"],
            odds=v["home_odds"],
        ),
        away=TeamInfo(
            code=v["away_code"],
            fullName=v["away_name"],
            record=v["away_rec"],
            probability=v["p_away"],
            odds=v["away_odds"],
        ),
        valueEdge=ValueEdge(
            side=v["edge_side"],
            percent=v["edge"],
            bookmaker=v["bookmaker"],
        ),
    )


def _build_live_list(bucket: int, n: int = 12) -> List[SecondaryMatch]:
    """Lista de N partidos con edge variado."""
    out = []
    # Empezamos desde un offset rotante
    offset = bucket % len(MATCH_POOL)
    for i in range(n):
        idx = (offset + i + 1) % len(MATCH_POOL)
        v = _build_match_variant(idx, bucket)
        out.append(SecondaryMatch(
            id=v["id"],
            sport=v["base"]["sport"],
            meta=f"{v['base']['comp']} · {v['base']['stage']}",
            label=f"{v['home_name']} vs {v['away_name']}",
            homeCode=v["home_code"],
            awayCode=v["away_code"],
            homeProb=v["p_home"],
            awayProb=v["p_away"],
            homeOdds=v["home_odds"],
            awayOdds=v["away_odds"],
            valueEdgePercent=v["edge"],
        ))
    return out


# ========== ENDPOINTS ==========

@router.get("/")
def index():
    return {
        "status": "ok",
        "module": "signals",
        "source": "mock-rich",
        "pool_size": len(MATCH_POOL),
        "bucket": _now_bucket(),
    }


@router.get("/featured", response_model=FeaturedMatch)
def get_featured():
    return _build_featured(_now_bucket())


@router.get("/live", response_model=List[SecondaryMatch])
def get_live():
    return _build_live_list(_now_bucket(), n=12)
