"""
Gladiator Odds — Backend Principal
FastAPI + PostgreSQL + Redis
"""
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
    allow_origins=["http://localhost:3000", "https://betscan-app.vercel.app", "https://betscan-api-production.up.railway.app"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers — solo signals por ahora (sin DB)
app.include_router(signals.router, prefix="/api/signals", tags=["Signals"])

@app.get("/")
def root():
    return {"status": "BetScan API online", "version": "1.0.0"}

@app.get("/health")
def health():
    return {"status": "ok"}

# ================================================================
# TRADING BOT — endpoints de control
# ================================================================
from app.trading_bot import bot
import asyncio

@app.on_event("startup")
async def start_bot():
    # Delay de 30 segundos para que Railway confirme el health check primero
    async def delayed_start():
        await asyncio.sleep(30)
        await bot.start(interval_minutes=60)
    asyncio.create_task(delayed_start())

@app.get("/api/bot/status")
async def bot_status():
    return {
        "running":    bot.running,
        "summary":    bot.portfolio.get_summary(),
        "fear_greed": bot.fear_greed,
        "cycle":      bot.cycle_count,
    }

@app.post("/api/bot/cycle")
async def run_cycle_manual():
    return bot.run_cycle()

@app.post("/api/bot/pause")
async def pause_bot(reason: str = "Pausa manual"):
    bot.portfolio.pause(reason)
    return {"status": "paused", "reason": reason}

@app.post("/api/bot/resume")
async def resume_bot():
    bot.portfolio.resume()
    return {"status": "running"}

@app.post("/api/bot/reset")
async def reset_portfolio():
    from app.trading_bot import Portfolio
    bot.portfolio   = Portfolio()
    bot.last_prices = {}
    return {"status": "reset", "capital": 50000}

@app.get("/api/bot/signals")
async def get_signals():
    return {"signals": bot.last_signals}

@app.get("/api/bot/trades")
async def get_trades():
    return {"trades": bot.portfolio.trades}

@app.get("/api/bot/equity")
async def get_equity():
    return {"equity": bot.portfolio.equity_curve}
