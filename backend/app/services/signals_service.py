"""
Motor de señales — The Odds API + Value Betting + Arbitraje + IA
"""
import httpx
import asyncio
from typing import List, Dict, Optional
from datetime import datetime
from app.core.config import settings

# ── The Odds API ──────────────────────────────────────────────────────────────

SPORTS_MAP = {
    "futbol":  ["soccer_spain_la_liga", "soccer_england_premier_league", 
                "soccer_argentina_primera_division", "soccer_germany_bundesliga",
                "soccer_italy_serie_a", "soccer_france_ligue_one", 
                "soccer_uefa_champs_league"],
    "basket":  ["basketball_nba", "basketball_euroleague"],
    "tenis":   ["tennis_atp_french_open", "tennis_wta"],
    "mma":     ["mma_mixed_martial_arts"],
    "rugby":   ["rugbyleague_nrl"],
}

BOOKMAKERS_AR = [
    "betfair_ex_eu", "pinnacle", "bet365", "betway", 
    "unibet", "williamhill", "bwin", "1xbet"
]


async def fetch_odds(sport_key: str) -> List[Dict]:
    """Obtiene odds reales de The Odds API para un deporte"""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{settings.ODDS_API_URL}/sports/{sport_key}/odds",
            params={
                "apiKey": settings.ODDS_API_KEY,
                "regions": "eu,uk",
                "markets": "h2h,spreads,totals",
                "oddsFormat": "decimal",
                "bookmakers": ",".join(BOOKMAKERS_AR)
            },
            timeout=10.0
        )
        resp.raise_for_status()
        return resp.json()


async def fetch_all_odds() -> List[Dict]:
    """Obtiene odds de todos los deportes en paralelo"""
    all_events = []
    tasks = []
    for sport_category, sport_keys in SPORTS_MAP.items():
        for sport_key in sport_keys:
            tasks.append(fetch_odds(sport_key))
    
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for result in results:
        if isinstance(result, list):
            all_events.extend(result)
    
    return all_events


# ── Value Betting Engine ──────────────────────────────────────────────────────

def implied_probability(odd: float) -> float:
    """Convierte cuota decimal a probabilidad implícita"""
    return 1 / odd if odd > 0 else 0


def calculate_model_probability(odds_list: List[float]) -> float:
    """
    Modelo de probabilidad: promedio ponderado de las mejores cuotas
    de mercado, ajustado por margen del bookmaker.
    En producción reemplazar por modelo ML entrenado.
    """
    if not odds_list:
        return 0
    # Quitar el margen promedio del book (~5%)
    raw_probs = [implied_probability(o) for o in odds_list]
    avg_margin = sum(raw_probs) / len(raw_probs)
    return min(0.98, max(0.02, avg_margin * 0.95))


def calculate_ev(model_prob: float, odd: float) -> float:
    """Expected Value = (prob_modelo * cuota) - 1"""
    return (model_prob * odd) - 1


def kelly_criterion(model_prob: float, odd: float) -> float:
    """Kelly Criterion para sizing de apuesta"""
    b = odd - 1  # ganancia neta por unidad
    p = model_prob
    q = 1 - p
    kelly = (b * p - q) / b
    # Fracción de Kelly (25%) para ser conservadores
    return max(0, min(0.15, kelly * 0.25))


def detect_value_bets(events: List[Dict], min_ev: float = 0.03) -> List[Dict]:
    """
    Detecta value bets en los eventos.
    min_ev: EV mínimo para considerar valor (3% por defecto)
    """
    value_bets = []
    
    for event in events:
        home = event.get("home_team", "")
        away = event.get("away_team", "")
        sport_key = event.get("sport_key", "")
        commence_time = event.get("commence_time")
        
        # Recolectar todas las cuotas por outcome
        outcomes_odds: Dict[str, List[float]] = {}
        
        for bookmaker in event.get("bookmakers", []):
            for market in bookmaker.get("markets", []):
                if market.get("key") != "h2h":
                    continue
                for outcome in market.get("outcomes", []):
                    name = outcome.get("name")
                    price = outcome.get("price", 0)
                    if name and price > 1:
                        outcomes_odds.setdefault(name, []).append(price)
        
        # Analizar cada outcome
        for outcome_name, odds_list in outcomes_odds.items():
            best_odd = max(odds_list)
            model_prob = calculate_model_probability(odds_list)
            ev = calculate_ev(model_prob, best_odd)
            
            if ev >= min_ev:
                book_prob = implied_probability(best_odd)
                kelly = kelly_criterion(model_prob, best_odd)
                
                # Encontrar en qué bookmaker está la mejor cuota
                best_book = ""
                for bookmaker in event.get("bookmakers", []):
                    for market in bookmaker.get("markets", []):
                        if market.get("key") != "h2h":
                            continue
                        for outcome in market.get("outcomes", []):
                            if outcome.get("name") == outcome_name and outcome.get("price") == best_odd:
                                best_book = bookmaker.get("title", "")
                
                value_bets.append({
                    "type": "value_bet",
                    "sport": sport_key,
                    "match": f"{home} vs {away}",
                    "pick": outcome_name,
                    "odd": best_odd,
                    "platform": best_book,
                    "model_prob": round(model_prob * 100, 2),
                    "book_prob": round(book_prob * 100, 2),
                    "ev_pct": round(ev * 100, 2),
                    "kelly_pct": round(kelly * 100, 2),
                    "confidence": round(min(95, max(50, model_prob * 100 + ev * 50)), 2),
                    "event_time": commence_time,
                    "detected_at": datetime.utcnow().isoformat(),
                })
    
    return sorted(value_bets, key=lambda x: x["ev_pct"], reverse=True)


# ── Arbitrage Engine ──────────────────────────────────────────────────────────

def detect_arbitrages(events: List[Dict], min_profit: float = 0.01) -> List[Dict]:
    """
    Detecta arbitrajes entre bookmakers.
    Un arbitraje existe cuando la suma de probabilidades implícitas < 1
    """
    arbitrages = []
    
    for event in events:
        home = event.get("home_team", "")
        away = event.get("away_team", "")
        
        # Buscar la mejor cuota por outcome en DIFERENTES bookmakers
        best_by_outcome: Dict[str, Dict] = {}
        
        for bookmaker in event.get("bookmakers", []):
            for market in bookmaker.get("markets", []):
                if market.get("key") != "h2h":
                    continue
                for outcome in market.get("outcomes", []):
                    name = outcome.get("name")
                    price = outcome.get("price", 0)
                    book_name = bookmaker.get("title", "")
                    
                    if name and price > 1:
                        current_best = best_by_outcome.get(name)
                        if not current_best or price > current_best["odd"]:
                            best_by_outcome[name] = {
                                "odd": price,
                                "book": book_name,
                                "pick": name
                            }
        
        # Para partidos de 2 outcomes (sin empate posible)
        outcomes = list(best_by_outcome.values())
        if len(outcomes) >= 2:
            for i in range(len(outcomes)):
                for j in range(i + 1, len(outcomes)):
                    o1, o2 = outcomes[i], outcomes[j]
                    # Solo si son bookmakers DIFERENTES
                    if o1["book"] != o2["book"]:
                        margin = (1 / o1["odd"]) + (1 / o2["odd"])
                        if margin < (1 - min_profit):
                            profit = (1 / margin - 1) * 100
                            total_stake = 1000  # Ejemplo $1000 total
                            stake1 = total_stake / (margin * o1["odd"])
                            stake2 = total_stake / (margin * o2["odd"])
                            
                            arbitrages.append({
                                "type": "arbitrage",
                                "sport": event.get("sport_key"),
                                "match": f"{home} vs {away}",
                                "platform_1": o1["book"],
                                "pick_1": o1["pick"],
                                "odd_1": o1["odd"],
                                "stake_1": round(stake1, 2),
                                "platform_2": o2["book"],
                                "pick_2": o2["pick"],
                                "odd_2": o2["odd"],
                                "stake_2": round(stake2, 2),
                                "margin": round(margin, 4),
                                "profit_pct": round(profit, 2),
                                "guaranteed_profit": round(total_stake / margin - total_stake, 2),
                                "detected_at": datetime.utcnow().isoformat(),
                            })
    
    return sorted(arbitrages, key=lambda x: x["profit_pct"], reverse=True)


# ── AI Analysis ───────────────────────────────────────────────────────────────

async def analyze_signal_with_ai(signal: Dict) -> str:
    """Genera análisis IA para una señal usando Claude"""
    import anthropic
    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    
    prompt = f"""Analiza esta señal de apuesta deportiva:
Partido: {signal.get('match')}
Tipo: {signal.get('type')}
Pick: {signal.get('pick')}
Cuota: {signal.get('odd')}
EV: +{signal.get('ev_pct')}%
Confianza del modelo: {signal.get('confidence')}%

Dame en máximo 60 palabras: 1) Si apostuarías 2) Factores clave 3) Riesgo principal. Sin markdown."""
    
    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=200,
        messages=[{"role": "user", "content": prompt}]
    )
    return message.content[0].text


# ── Main scanner ──────────────────────────────────────────────────────────────

async def run_full_scan() -> Dict:
    """
    Escaneo completo: obtiene odds reales y detecta value bets + arbitrajes.
    Se ejecuta cada X minutos via scheduler.
    """
    events = await fetch_all_odds()
    value_bets = detect_value_bets(events, min_ev=0.03)
    arbitrages = detect_arbitrages(events, min_profit=0.01)
    
    return {
        "scanned_events": len(events),
        "value_bets_found": len(value_bets),
        "arbitrages_found": len(arbitrages),
        "value_bets": value_bets[:20],   # Top 20
        "arbitrages": arbitrages[:10],   # Top 10
        "scanned_at": datetime.utcnow().isoformat()
    }
