"""
Gladiator Odds — Backend Principal
FastAPI + PostgreSQL + Redis
"""
import asyncio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api import signals

app = FastAPI(
    title="Gladiator Odds API",
    version="1.0.0",
    description="Multi-platform betting intelligence platform"
)

# CORS para el frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "https://betscan-app.vercel.app", "https://betscan-api-production.up.railway.app", "https://www.betscan.online"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(signals.router, prefix="/api/signals", tags=["Signals"])

@app.get("/")
def root():
    return {"status": "BetScan API online", "version": "1.0.0"}

@app.get("/health")
def health():
    return {"status": "ok"}

# ================================================================
# TRADING BOT — import protegido
# ================================================================
try:
    from app.trading_bot import bot
    BOT_AVAILABLE = True
    print("[BOT] Import exitoso ✅")
except Exception as e:
    print(f"[BOT] Import error: {e}")
    BOT_AVAILABLE = False
    bot = None

@app.on_event("startup")
async def start_bot():
    if not BOT_AVAILABLE or bot is None:
        print("[BOT] No disponible — saltando startup")
        return
    async def delayed_start():
        await asyncio.sleep(60)
        await bot.start(interval_minutes=60)
    asyncio.create_task(delayed_start())

@app.get("/api/bot/status")
async def bot_status():
    if not BOT_AVAILABLE or bot is None:
        return {"running": False, "bot_available": False, "error": "Bot no disponible"}
    try:
        summary = bot.portfolio.get_summary()
        # ---- Kill switch por drawdown máximo (FIX: protección para testing) ----
        equity = summary.get("equity_total", 50000)
        peak   = getattr(bot.portfolio, "peak_equity", 50000)
        if equity > peak:
            bot.portfolio.peak_equity = equity
        drawdown_pct = (peak - equity) / peak * 100 if peak > 0 else 0
        if drawdown_pct >= 10 and summary.get("status") == "RUNNING":
            bot.portfolio.pause(f"Kill switch: drawdown {drawdown_pct:.1f}% desde pico ${peak:,.0f}")
        return {
            "running":       bot.running,
            "bot_available": True,
            "summary":       summary,
            "fear_greed":    bot.macro.get("fear_greed", 0) if bot.macro else 0,
            "cycle":         bot.cycle_count,
            "drawdown_pct":  round(drawdown_pct, 2),
            "peak_equity":   round(peak, 2),
        }
    except Exception as e:
        return {
            "running":       bot.running,
            "bot_available": True,
            "cycle":         bot.cycle_count,
            "status":        "iniciando — primer ciclo en progreso",
            "error":         str(e),
        }

@app.post("/api/bot/cycle")
async def run_cycle_manual():
    if not BOT_AVAILABLE or bot is None:
        return {"error": "Bot no disponible"}
    result = bot.run_cycle()
    return result

@app.post("/api/bot/pause")
async def pause_bot(reason: str = "Pausa manual"):
    if not BOT_AVAILABLE or bot is None:
        return {"error": "Bot no disponible"}
    bot.portfolio.pause(reason)
    return {"status": "paused", "reason": reason}

@app.post("/api/bot/resume")
async def resume_bot():
    if not BOT_AVAILABLE or bot is None:
        return {"error": "Bot no disponible"}
    bot.portfolio.resume()
    return {"status": "running"}

@app.post("/api/bot/reset")
async def reset_portfolio():
    if not BOT_AVAILABLE or bot is None:
        return {"error": "Bot no disponible"}
    from app.trading_bot import Portfolio
    bot.portfolio   = Portfolio()
    bot.last_prices = {}
    return {"status": "reset", "capital": 50000}

@app.get("/api/bot/signals")
async def get_signals():
    if not BOT_AVAILABLE or bot is None:
        return {"signals": []}
    return {"signals": bot.last_signals}

@app.get("/api/bot/trades")
async def get_trades():
    if not BOT_AVAILABLE or bot is None:
        return {"trades": []}
    return {"trades": bot.portfolio.trades}

@app.get("/api/bot/equity")
async def get_equity():
    if not BOT_AVAILABLE or bot is None:
        return {"equity": [50000]}
    return {"equity": bot.portfolio.equity_curve}
