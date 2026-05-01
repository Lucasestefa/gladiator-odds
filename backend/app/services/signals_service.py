"""
Motor de señales — The Odds API + Value Betting + Arbitraje + IA
Cache de 6 horas + 8 deportes optimizados para 20K credits/mes.
"""
import httpx
import asyncio
import time
from typing import List, Dict, Optional, Tuple
from datetime import datetime
from app.core.config import settings

# ── Deportes optimizados (8 total ~ 20K credits/mes con cache 6h) ─────────────

def get_active_sports() -> List[str]:
    """Rotacion por horario para distribuir quota."""
    hour = datetime.utcnow().hour
    # Madrugada/Manana: LATAM
    if 0 <= hour < 12:
        return [
            "soccer_argentina_primera_division",
            "soccer_brazil_campeonato",
            "soccer_mexico_ligamx",
            "soccer_uefa_champs_league",
            "basketball_nba",
        ]
    # Tarde: Europa
    elif 12 <= hour < 20:
        return [
            "soccer_england_premier_league",
            "soccer_spain_la_liga",
            "soccer_uefa_champs_league",
            "soccer_argentina_primera_division",
            "basketball_nba",
        ]
    # Noche: Mix completo
    else:
        return [
            "soccer_uefa_champs_league",
            "soccer_england_premier_league",
            "soccer_brazil_campeonato",
            "basketball_nba",
            "tennis_atp_french_open",
        ]

# ── Cache en memoria (6 horas) ────────────────────────────────────────────────

_cache: Dict[str, Dict] = {}
CACHE_TTL = 6 * 3600  # 6 horas en segundos

def _cache_get(key: str):
    entry = _cache.get(key)
    if entry and (time.time() - entry["ts"]) < CACHE_TTL:
        return entry["data"]
    return None

def _cache_set(key: str, data):
    _cache[key] = {"data": data, "ts": time.time()}

# ── The Odds API ──────────────────────────────────────────────────────────────

SHARP_BOOK_WEIGHTS = {
    "Pinnacle":       3.0,
    "Betfair":        2.5,
    "Matchbook":      2.0,
    "Unibet":         1.5,
    "Bet365":         1.2,
    "William Hill":   1.2,
    "Bwin":           1.0,
    "1xBet":          0.8,
}
DEFAULT_WEIGHT = 1.0


async def fetch_odds(sport_key: str) -> List[Dict]:
    """Obtiene odds reales con cache de 6h."""
    cached = _cache_get(f"odds_{sport_key}")
    if cached is not None:
        return cached

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{settings.ODDS_API_URL}/sports/{sport_key}/odds",
            params={
                "apiKey":     settings.ODDS_API_KEY,
                "regions":    "eu,uk",
                "markets":    "h2h",
                "oddsFormat": "decimal",
            },
            timeout=10.0,
        )
        if resp.status_code != 200:
            return []
        data = resp.json()
        _cache_set(f"odds_{sport_key}", data)
        remaining = resp.headers.get("x-requests-remaining", "?")
        used = resp.headers.get("x-requests-used", "?")
        print(f"Odds API [{sport_key}] — used: {used} | remaining: {remaining}")
        return data


async def fetch_all_odds() -> List[Dict]:
    """Fetch paralelo de los deportes activos segun horario."""
    cached = _cache_get("all_odds")
    if cached is not None:
        print("Cache hit — sin llamada a Odds API")
        return cached

    sports = get_active_sports()
    print(f"Fetching {len(sports)} deportes: {sports}")
    tasks = [fetch_odds(sport_key) for sport_key in sports]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    events = [event for result in results if isinstance(result, list) for event in result]
    _cache_set("all_odds", events)
    print(f"Total eventos obtenidos: {len(events)}")
    return events


# ── Devigging ─────────────────────────────────────────────────────────────────

def devig_market(outcomes: List[Dict]) -> Dict[str, float]:
    valid = [o for o in outcomes if o.get("price", 0) > 1]
    if not valid:
        return {}
    total_implied = sum(1 / o["price"] for o in valid)
    return {o["name"]: (1 / o["price"]) / total_implied for o in valid}


def consensus_fair_probs(h2h_markets: Dict[str, List[Dict]]) -> Dict[str, float]:
    accumulated: Dict[str, List[Tuple[float, float]]] = {}
    for book_title, outcomes in h2h_markets.items():
        weight = SHARP_BOOK_WEIGHTS.get(book_title, DEFAULT_WEIGHT)
        fair = devig_market(outcomes)
        for name, prob in fair.items():
            accumulated.setdefault(name, []).append((prob, weight))
    result = {}
    for name, entries in accumulated.items():
        total_w = sum(w for _, w in entries)
        result[name] = sum(p * w for p, w in entries) / total_w
    return result


# ── Value Betting Engine ──────────────────────────────────────────────────────

def calculate_ev(fair_prob: float, odd: float) -> float:
    return (fair_prob * odd) - 1


def kelly_criterion(fair_prob: float, odd: float) -> float:
    b = odd - 1
    q = 1 - fair_prob
    kelly = (b * fair_prob - q) / b if b > 0 else 0
    return max(0.0, min(0.15, kelly * 0.25))


def detect_value_bets(events: List[Dict], min_ev: float = 0.03) -> List[Dict]:
    value_bets = []
    for event in events:
        home      = event.get("home_team", "")
        away      = event.get("away_team", "")
        sport_key = event.get("sport_key", "")
        commence  = event.get("commence_time")

        h2h_markets: Dict[str, List[Dict]] = {}
        best_odds:   Dict[str, Dict]       = {}

        for bookmaker in event.get("bookmakers", []):
            book_title = bookmaker.get("title", "")
            for market in bookmaker.get("markets", []):
                if market.get("key") != "h2h":
                    continue
                outcomes = [
                    {"name": o["name"], "price": o["price"]}
                    for o in market.get("outcomes", [])
                    if o.get("price", 0) > 1
                ]
                if outcomes:
                    h2h_markets[book_title] = outcomes
                    for o in outcomes:
                        prev = best_odds.get(o["name"])
                        if not prev or o["price"] > prev["price"]:
                            best_odds[o["name"]] = {"price": o["price"], "book": book_title}

        if len(h2h_markets) < 2:
            continue

        fair_prob = consensus_fair_probs(h2h_markets)
        all_outcomes_summary = [
            {
                "name":      name,
                "fair_prob": round(fp * 100, 2),
                "best_odd":  best_odds.get(name, {}).get("price", 0),
                "best_book": best_odds.get(name, {}).get("book", ""),
            }
            for name, fp in fair_prob.items()
        ]

        for outcome_name, best in best_odds.items():
            fp = fair_prob.get(outcome_name, 0)
            if fp <= 0:
                continue
            ev = calculate_ev(fp, best["price"])
            if ev < min_ev or ev > 0.5:
                continue
            kelly = kelly_criterion(fp, best["price"])
            confidence = round(min(95, 50 + ev * 150 + len(h2h_markets) * 0.5), 1)
            value_bets.append({
                "type":          "value_bet",
                "sport":         sport_key,
                "match":         f"{home} vs {away}",
                "home_team":     home,
                "away_team":     away,
                "pick":          outcome_name,
                "odd":           best["price"],
                "platform":      best["book"],
                "fair_prob":     round(fp * 100, 2),
                "model_prob":    round(fp * 100, 2),
                "book_prob":     round((1 / best["price"]) * 100, 2),
                "ev_pct":        round(ev * 100, 2),
                "kelly_pct":     round(kelly * 100, 2),
                "confidence":    confidence,
                "books_sampled": len(h2h_markets),
                "event_time":    commence,
                "detected_at":   datetime.utcnow().isoformat(),
                "all_outcomes":  all_outcomes_summary,
            })

    return sorted(value_bets, key=lambda x: x["ev_pct"], reverse=True)


# ── Arbitrage Engine ──────────────────────────────────────────────────────────

def detect_arbitrages(events: List[Dict], min_profit: float = 0.005) -> List[Dict]:
    arbitrages = []
    for event in events:
        home = event.get("home_team", "")
        away = event.get("away_team", "")
        best_by_outcome: Dict[str, Dict] = {}
        for bookmaker in event.get("bookmakers", []):
            book_title = bookmaker.get("title", "")
            for market in bookmaker.get("markets", []):
                if market.get("key") != "h2h":
                    continue
                for outcome in market.get("outcomes", []):
                    name  = outcome.get("name")
                    price = outcome.get("price", 0)
                    if name and price > 1:
                        prev = best_by_outcome.get(name)
                        if not prev or price > prev["odd"]:
                            best_by_outcome[name] = {"odd": price, "book": book_title, "pick": name}
        outcomes = list(best_by_outcome.values())
        if len(outcomes) < 2:
            continue
        for i in range(len(outcomes)):
            for j in range(i + 1, len(outcomes)):
                o1, o2 = outcomes[i], outcomes[j]
                if o1["book"] == o2["book"]:
                    continue
                margin = (1 / o1["odd"]) + (1 / o2["odd"])
                if margin < (1 - min_profit):
                    profit_pct = (1 / margin - 1) * 100
                    total_stake = 1000
                    stake1 = total_stake / (margin * o1["odd"])
                    stake2 = total_stake / (margin * o2["odd"])
                    arbitrages.append({
                        "type":              "arbitrage",
                        "sport":             event.get("sport_key"),
                        "match":             f"{home} vs {away}",
                        "platform_1":        o1["book"],
                        "pick_1":            o1["pick"],
                        "odd_1":             o1["odd"],
                        "stake_1":           round(stake1, 2),
                        "platform_2":        o2["book"],
                        "pick_2":            o2["pick"],
                        "odd_2":             o2["odd"],
                        "stake_2":           round(stake2, 2),
                        "margin":            round(margin, 4),
                        "profit_pct":        round(profit_pct, 2),
                        "guaranteed_profit": round(total_stake / margin - total_stake, 2),
                        "detected_at":       datetime.utcnow().isoformat(),
                    })
    return sorted(arbitrages, key=lambda x: x["profit_pct"], reverse=True)


# ── AI Analysis ───────────────────────────────────────────────────────────────

async def analyze_signal_with_ai(signal: Dict) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    prompt = f"""Analiza esta senal de apuesta deportiva:
Partido: {signal.get('match')}
Pick: {signal.get('pick')}
Cuota: {signal.get('odd')}
Prob. fair: {signal.get('fair_prob')}%
EV: +{signal.get('ev_pct')}%
Books: {signal.get('books_sampled')}
En maximo 60 palabras: 1) apostarias? 2) factores clave 3) riesgo principal. Sin markdown."""
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=200,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


# ── Main scanner ──────────────────────────────────────────────────────────────

async def run_full_scan() -> Dict:
    events     = await fetch_all_odds()
    value_bets = detect_value_bets(events, min_ev=0.03)
    arbitrages = detect_arbitrages(events, min_profit=0.005)
    return {
        "scanned_events":   len(events),
        "value_bets_found": len(value_bets),
        "arbitrages_found": len(arbitrages),
        "value_bets":       value_bets[:20],
        "arbitrages":       arbitrages[:10],
        "scanned_at":       datetime.utcnow().isoformat(),
    }
