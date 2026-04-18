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
    allow_origins=["http://localhost:3000", "https://betscan-app.vercel.app"],
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
