"""
BETSCAN — Odds Snapshot Collector
Corre cada hora via Railway Cron Job
Guarda odds en Supabase PostgreSQL
"""

import os
import time
import hashlib
import requests
import psycopg2
from datetime import datetime, timezone
from psycopg2.extras import execute_values

# ─── CONFIG ────────────────────────────────────────────────
ODDS_API_KEY   = os.environ.get("ODDS_API_KEY", "d6f8fe933e1192484e9fa3e47aee845b")
DATABASE_URL   = os.environ.get("DATABASE_URL")  # Supabase connection string
ODDS_API_BASE  = "https://api.the-odds-api.com/v4"

# Deportes a monitorear (empezamos con fútbol — más alto ROI de datos)
SPORTS = [
    "soccer_epl",           # Premier League
    "soccer_spain_la_liga", # La Liga
    "soccer_uefa_champs_league",  # Champions
    "soccer_germany_bundesliga",
    "soccer_italy_serie_a",
    "soccer_france_ligue_one",
    "soccer_argentina_primera_division",
]

# Mercados a capturar
MARKETS = "h2h,spreads,totals"

# Bookmakers que nos interesan
BOOKMAKERS = "bet365,betfair,pinnacle,williamhill,unibet,bwin,draftkings,fanduel"

# ─── HELPERS ───────────────────────────────────────────────

def make_match_id(home: str, away: str, commence: str) -> str:
    """Hash único por partido"""
    raw = f"{home}|{away}|{commence}"
    return hashlib.md5(raw.encode()).hexdigest()

def get_db_connection():
    return psycopg2.connect(DATABASE_URL, sslmode="require")

# ─── FETCHER ───────────────────────────────────────────────

def fetch_odds(sport: str) -> list:
    url = f"{ODDS_API_BASE}/sports/{sport}/odds"
    params = {
        "apiKey":     ODDS_API_KEY,
        "regions":    "eu",
        "markets":    MARKETS,
        "oddsFormat": "decimal",
        "bookmakers": BOOKMAKERS,
    }
    resp = requests.get(url, params=params, timeout=15)
    
    # Headers de quota
    quota_used      = resp.headers.get("x-requests-used", "?")
    quota_remaining = resp.headers.get("x-requests-remaining", "?")
    print(f"  [{sport}] Status: {resp.status_code} | Quota used: {quota_used} | Remaining: {quota_remaining}")
    
    if resp.status_code == 200:
        return resp.json(), int(quota_remaining) if quota_remaining != "?" else None
    elif resp.status_code == 401:
        print("  ⚠️  API key inválida o expirada")
        return [], None
    elif resp.status_code == 429:
        print("  ⚠️  Quota agotada")
        return [], 0
    else:
        print(f"  ⚠️  Error: {resp.text}")
        return [], None

# ─── PARSER ────────────────────────────────────────────────

def parse_events(events: list, sport_key: str) -> list:
    """Convierte respuesta de API en filas planas para la DB"""
    rows = []
    captured_at = datetime.now(timezone.utc)
    
    for event in events:
        match_id     = make_match_id(
            event["home_team"],
            event["away_team"],
            event["commence_time"]
        )
        home_team    = event["home_team"]
        away_team    = event["away_team"]
        sport_title  = event.get("sport_title", sport_key)
        commence_time = event["commence_time"]
        
        for bookmaker in event.get("bookmakers", []):
            bk_key = bookmaker["key"]
            
            for market in bookmaker.get("markets", []):
                market_key = market["key"]
                
                for outcome in market.get("outcomes", []):
                    rows.append((
                        captured_at,
                        sport_key,
                        sport_title,
                        commence_time,
                        home_team,
                        away_team,
                        bk_key,
                        market_key,
                        outcome["name"],
                        float(outcome["price"]),
                        float(outcome.get("point", 0)) or None,
                        match_id
                    ))
    
    return rows

# ─── SAVER ─────────────────────────────────────────────────

def save_snapshots(conn, rows: list) -> int:
    if not rows:
        return 0
    
    with conn.cursor() as cur:
        sql = """
            INSERT INTO odds_snapshots (
                captured_at, sport_key, sport_title, commence_time,
                home_team, away_team, bookmaker, market,
                outcome_name, price, point, match_id
            ) VALUES %s
        """
        execute_values(cur, sql, rows, page_size=500)
    
    conn.commit()
    return len(rows)

def log_run(conn, sports_fetched, snapshots_saved, api_calls, quota_remaining, error_msg, duration_ms):
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO collector_log 
            (sports_fetched, snapshots_saved, api_calls_used, quota_remaining, error_msg, duration_ms)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (sports_fetched, snapshots_saved, api_calls, quota_remaining, error_msg, duration_ms))
    conn.commit()

# ─── MAIN ──────────────────────────────────────────────────

def main():
    start_time = time.time()
    print(f"\n{'='*50}")
    print(f"🧠 BetScan Collector — {datetime.now(timezone.utc).isoformat()}")
    print(f"{'='*50}")
    
    total_snapshots = 0
    total_api_calls = 0
    quota_remaining = None
    error_msg       = None
    
    try:
        conn = get_db_connection()
        print("✅ Conectado a Supabase")
        
        for sport in SPORTS:
            print(f"\n📡 Fetching: {sport}")
            
            events, quota = fetch_odds(sport)
            total_api_calls += 1
            
            if quota is not None:
                quota_remaining = quota
            
            if quota == 0:
                print("  🛑 Quota agotada — deteniendo colector")
                break
            
            if events:
                rows = parse_events(events, sport)
                saved = save_snapshots(conn, rows)
                total_snapshots += saved
                print(f"  ✅ {len(events)} partidos → {saved} odds guardadas")
            else:
                print(f"  ⚠️  Sin datos para {sport}")
            
            # Pausa entre requests para no saturar la API
            time.sleep(1)
        
        duration_ms = int((time.time() - start_time) * 1000)
        log_run(conn, len(SPORTS), total_snapshots, total_api_calls, quota_remaining, None, duration_ms)
        conn.close()
        
        print(f"\n{'='*50}")
        print(f"✅ Completado en {duration_ms}ms")
        print(f"📊 Snapshots guardados: {total_snapshots}")
        print(f"🔑 Quota restante: {quota_remaining}")
        print(f"{'='*50}\n")
        
    except Exception as e:
        error_msg   = str(e)
        duration_ms = int((time.time() - start_time) * 1000)
        print(f"\n❌ Error: {error_msg}")
        
        try:
            log_run(conn, 0, 0, total_api_calls, quota_remaining, error_msg, duration_ms)
            conn.close()
        except:
            pass
        
        raise e

if __name__ == "__main__":
    main()
