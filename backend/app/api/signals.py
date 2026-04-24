"""
BetScan — Signals API
Datos reales via The Odds API + fallback a mock rico si quota agotada.
"""
import time
import random
from typing import List, Optional
from fastapi import APIRouter
from pydantic import BaseModel

try:
    from app.core.cache import cache
    CACHE_AVAILABLE = True
except ImportError:
    CACHE_AVAILABLE = False
    cache = None

try:
    from app.services.signals_service import fetch_all_odds, detect_value_bets, detect_arbitrages
    REAL_SERVICE_AVAILABLE = True
except ImportError:
    REAL_SERVICE_AVAILABLE = False

router = APIRouter()

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

BOOKMAKERS = ["Pinnacle", "Bet365", "Betfair", "1xBet", "Winamax", "Unibet", "Betway", "Bwin"]

MATCH_POOL = [
    {"sport": "football", "comp": "Champions League", "stage": "Quarterfinal", "home": ("Real Madrid", "RMA", "27-7-4"), "away": ("Arsenal", "ARS", "24-8-6"), "base_odds": (1.92, 2.08), "edge": 8.4},
    {"sport": "football", "comp": "Champions League", "stage": "Semifinal", "home": ("PSG", "PSG", "22-9-7"), "away": ("Liverpool", "LIV", "26-6-6"), "base_odds": (2.45, 1.68), "edge": 5.1},
    {"sport": "football", "comp": "La Liga", "stage": "Jornada 32", "home": ("Barcelona", "BAR", "25-8-5"), "away": ("Atletico Madrid", "ATM", "22-10-6"), "base_odds": (1.75, 2.30), "edge": 7.2},
    {"sport": "football", "comp": "Serie A", "stage": "Giornata 33", "home": ("Inter", "INT", "26-7-5"), "away": ("Juventus", "JUV", "22-9-7"), "base_odds": (1.68, 2.45), "edge": 6.3},
    {"sport": "football", "comp": "Primera Argentina", "stage": "Fecha 12", "home": ("Boca Juniors", "BOC", "8-2-2"), "away": ("River Plate", "RIV", "7-3-2"), "base_odds": (2.35, 2.10), "edge": 4.9},
    {"sport": "basketball", "comp": "NBA Playoffs", "stage": "Conference Semis", "home": ("Celtics", "BOS", "64-18"), "away": ("Knicks", "NYK", "52-30"), "base_odds": (1.72, 2.05), "edge": 6.7},
    {"sport": "tennis", "comp": "Madrid Open", "stage": "Semifinal", "home": ("Carlos Alcaraz", "ALC", "42-10"), "away": ("Jannik Sinner", "SIN", "40-12"), "base_odds": (1.75, 2.15), "edge": 5.2},
    {"sport": "hockey", "comp": "NHL Playoffs", "stage": "Round 2", "home": ("Oilers", "EDM", "52-28-2"), "away": ("Avalanche", "COL", "50-30-2"), "base_odds": (1.95, 1.90), "edge": 5.9},
    {"sport": "baseball", "comp": "MLB", "stage": "Regular Season", "home": ("Dodgers", "LAD", "65-40"), "away": ("Yankees", "NYY", "62-43"), "base_odds": (1.88, 2.00), "edge": 4.5},
    {"sport": "nfl", "comp": "NFL", "stage": "Week 17", "home": ("Chiefs", "KC", "13-3"), "away": ("49ers", "SF", "11-5"), "base_odds": (1.80, 2.10), "edge": 5.6},
]

def _now_bucket():
    return int(time.time() // 30)

def _kickoff_str(minutes_ahead):
    if minutes_ahead < 0: return "LIVE · En juego"
    if minutes_ahead < 60: return f"En {minutes_ahead}m"
    if minutes_ahead < 180: return f"En {minutes_ahead//60}h {minutes_ahead%60}m"
    return f"Hoy {(20 + (minutes_ahead // 60) % 4):02d}:00"

def _build_match_variant(idx, bucket):
    base = MATCH_POOL[idx % len(MATCH_POOL)]
    rng = random.Random(bucket + idx)
    home_name, home_code, home_rec = base["home"]
    away_name, away_code, away_rec = base["away"]
    home_odds = round(base["base_odds"][0] * (1 + rng.uniform(-0.03, 0.03)), 2)
    away_odds = round(base["base_odds"][1] * (1 + rng.uniform(-0.03, 0.03)), 2)
    p_home_raw = 1 / home_odds
    p_away_raw = 1 / away_odds
    total = p_home_raw + p_away_raw
    p_home = round((p_home_raw / total) * 100, 1)
    p_away = round((p_away_raw / total) * 100, 1)
    edge = round(base["edge"] + rng.uniform(-0.8, 0.8), 1)
    return {
        "id": f"{base['sport']}-{home_code.lower()}-{away_code.lower()}-b{bucket}",
        "base": base,
        "home_name": home_name, "home_code": home_code, "home_rec": home_rec,
        "away_name": away_name, "away_code": away_code, "away_rec": away_rec,
        "home_odds": home_odds, "away_odds": away_odds,
        "p_home": p_home, "p_away": p_away, "edge": edge,
        "edge_side": "home" if p_home >= p_away else "away",
        "bookmaker": rng.choice(BOOKMAKERS),
        "kickoff": _kickoff_str(rng.choice([-30, -15, 15, 30, 59, 90, 150, 300])),
    }

def _build_mock_featured(bucket):
    candidates = [i for i, m in enumerate(MATCH_POOL) if m["edge"] >= 5]
    v = _build_match_variant(candidates[bucket % len(candidates)], bucket)
    return FeaturedMatch(
        id=v["id"], sport=v["base"]["sport"],
        competition=v["base"]["comp"], stage=v["base"]["stage"],
        kickoff=v["kickoff"],
        home=TeamInfo(code=v["home_code"], fullName=v["home_name"], record=v["home_rec"], probability=v["p_home"], odds=v["home_odds"]),
        away=TeamInfo(code=v["away_code"], fullName=v["away_name"], record=v["away_rec"], probability=v["p_away"], odds=v["away_odds"]),
        valueEdge=ValueEdge(side=v["edge_side"], percent=v["edge"], bookmaker=v["bookmaker"]),
    )

def _build_mock_live(bucket, n=12):
    offset = bucket % len(MATCH_POOL)
    out = []
    for i in range(n):
        v = _build_match_variant((offset + i + 1) % len(MATCH_POOL), bucket)
        out.append(SecondaryMatch(
            id=v["id"], sport=v["base"]["sport"],
            meta=f"{v['base']['comp']} · {v['base']['stage']}",
            label=f"{v['home_name']} vs {v['away_name']}",
            homeCode=v["home_code"], awayCode=v["away_code"],
            homeProb=v["p_home"], awayProb=v["p_away"],
            homeOdds=v["home_odds"], awayOdds=v["away_odds"],
            valueEdgePercent=v["edge"],
        ))
    return out

def _sport_label(sport_key):
    mapping = {
        "soccer": "football", "basketball": "basketball",
        "tennis": "tennis", "mma": "mma",
        "icehockey": "hockey", "hockey": "hockey",
        "baseball": "baseball", "americanfootball": "nfl",
        "boxing": "boxing", "cricket": "cricket",
        "rugbyleague": "rugby", "rugbyunion": "rugby",
        "aussierules": "aussie",
    }
    return mapping.get(sport_key.split("_")[0], sport_key)

def _team_code(name):
    words = [w for w in name.split() if w and w[0].isalpha()] if name else []
    if len(words) >= 2:
        return (words[0][0] + words[1][:2]).upper()
    return name[:3].upper() if name else "UNK"

def _extract_team_data(vb, team_name):
    for o in vb.get("all_outcomes", []):
        if o["name"] == team_name:
            return {"prob": o["fair_prob"], "odd": o["best_odd"] or 2.0}
    return {"prob": 50.0, "odd": 2.0}

def _vb_to_featured(vb, bucket):
    home_name = vb.get("home_team", "Home")
    away_name = vb.get("away_team", "Away")
    home_data = _extract_team_data(vb, home_name)
    away_data = _extract_team_data(vb, away_name)
    pick = vb.get("pick", home_name)
    edge_side = "home" if pick == home_name else "away"
    return FeaturedMatch(
        id=f"real-{vb.get('sport','unk')}-{_team_code(home_name).lower()}-{_team_code(away_name).lower()}-b{bucket}",
        sport=_sport_label(vb.get("sport", "football")),
        competition=vb.get("sport", "").replace("_", " ").title(),
        stage=f"{vb.get('books_sampled', 1)} books · consenso",
        kickoff="Proximo",
        home=TeamInfo(code=_team_code(home_name), fullName=home_name, probability=home_data["prob"], odds=home_data["odd"]),
        away=TeamInfo(code=_team_code(away_name), fullName=away_name, probability=away_data["prob"], odds=away_data["odd"]),
        valueEdge=ValueEdge(side=edge_side, percent=vb.get("ev_pct", 0.0), bookmaker=vb.get("platform", "Pinnacle")),
    )

def _vb_to_secondary(vb, bucket):
    home_name = vb.get("home_team", "Home")
    away_name = vb.get("away_team", "Away")
    home_data = _extract_team_data(vb, home_name)
    away_data = _extract_team_data(vb, away_name)
    return SecondaryMatch(
        id=f"real-{vb.get('sport','unk')}-{_team_code(home_name).lower()}-{_team_code(away_name).lower()}-b{bucket}",
        sport=_sport_label(vb.get("sport", "football")),
        meta=vb.get("sport", "").replace("_", " ").title(),
        label=vb.get("match", f"{home_name} vs {away_name}"),
        homeCode=_team_code(home_name), awayCode=_team_code(away_name),
        homeProb=home_data["prob"], awayProb=away_data["prob"],
        homeOdds=home_data["odd"], awayOdds=away_data["odd"],
        valueEdgePercent=vb.get("ev_pct", 0.0),
    )

@router.get("/")
def index():
    return {"status": "ok", "module": "signals", "source": "real+mock-fallback",
            "pool_size": len(MATCH_POOL), "bucket": _now_bucket(), "real_service": REAL_SERVICE_AVAILABLE}

@router.get("/featured", response_model=FeaturedMatch)
async def get_featured():
    bucket = _now_bucket()
    cache_key = "featured"
    # Intentar servir desde cache (TTL 10 min)
    if CACHE_AVAILABLE and cache:
        cached = cache.get(cache_key)
        if cached:
            return cached
    # Si no hay cache — fetchear datos reales
    if REAL_SERVICE_AVAILABLE:
        try:
            events = await fetch_all_odds()
            vbs = detect_value_bets(events, min_ev=0.03)
            if vbs:
                result = _vb_to_featured(vbs[0], bucket)
                if CACHE_AVAILABLE and cache:
                    cache.set(cache_key, result, ttl_seconds=600)
                return result
        except Exception:
            pass
    result = _build_mock_featured(bucket)
    if CACHE_AVAILABLE and cache:
        cache.set(cache_key, result, ttl_seconds=600)
    return result

@router.get("/live", response_model=List[SecondaryMatch])
async def get_live():
    bucket = _now_bucket()
    cache_key = "live_signals"
    # Intentar servir desde cache (TTL 10 min)
    if CACHE_AVAILABLE and cache:
        cached = cache.get(cache_key)
        if cached:
            return cached
    # Si no hay cache — fetchear datos reales
    if REAL_SERVICE_AVAILABLE:
        try:
            events = await fetch_all_odds()
            vbs = detect_value_bets(events, min_ev=0.02)
            if vbs:
                seen = {}
                for vb in vbs:
                    match = vb.get("match", "")
                    if match not in seen or vb["ev_pct"] > seen[match]["ev_pct"]:
                        seen[match] = vb
                unique = list(seen.values())[:12]
                result = [_vb_to_secondary(vb, bucket) for vb in unique]
                if CACHE_AVAILABLE and cache:
                    cache.set(cache_key, result, ttl_seconds=600)
                return result
        except Exception:
            pass
    result = _build_mock_live(bucket, n=12)
    if CACHE_AVAILABLE and cache:
        cache.set(cache_key, result, ttl_seconds=600)
    return result

@router.get("/cache/stats")
def cache_stats():
    if CACHE_AVAILABLE and cache:
        return cache.stats()
    return {"error": "cache not available"}
