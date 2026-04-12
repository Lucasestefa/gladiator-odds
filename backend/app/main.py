"""
Gladiator Odds — Backend Principal
FastAPI + PostgreSQL + Redis
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api import auth, users, signals, platforms, betting, webhooks
from app.core.config import settings
from app.core.database import engine, Base

# Crear tablas al iniciar
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Gladiator Odds API",
    version="1.0.0",
    description="Multi-platform betting intelligence platform"
)

# CORS para el frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", settings.FRONTEND_URL],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(auth.router,      prefix="/api/auth",      tags=["Auth"])
app.include_router(users.router,     prefix="/api/users",     tags=["Users"])
app.include_router(signals.router,   prefix="/api/signals",   tags=["Signals"])
app.include_router(platforms.router, prefix="/api/platforms", tags=["Platforms"])
app.include_router(betting.router,   prefix="/api/betting",   tags=["Betting"])
app.include_router(webhooks.router,  prefix="/api/webhooks",  tags=["Webhooks"])

@app.get("/")
def root():
    return {"status": "Gladiator Odds API online", "version": "1.0.0"}

@app.get("/health")
def health():
    return {"status": "ok"}
