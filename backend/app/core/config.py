"""
Configuración central — todas las variables de entorno
"""
from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    # App
    APP_NAME: str = "Gladiator Odds"
    ENVIRONMENT: str = "development"
    SECRET_KEY: str = "change-this-in-production"
    FRONTEND_URL: str = "http://localhost:3000"

    # Base de datos
    DATABASE_URL: str = "postgresql://postgres:password@localhost:5432/gladiator_odds"
    
    # Redis (cache + queues)
    REDIS_URL: str = "redis://localhost:6379"

    # JWT
    JWT_SECRET: str = "change-this-jwt-secret"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 días

    # The Odds API (datos de 40+ bookmakers)
    ODDS_API_KEY: str = ""
    ODDS_API_URL: str = "https://api.the-odds-api.com/v4"

    # Betfair API (ejecución automática)
    BETFAIR_APP_KEY: str = ""
    BETFAIR_USERNAME: str = ""
    BETFAIR_PASSWORD: str = ""
    BETFAIR_CERT_PATH: str = "./certs/betfair.crt"
    BETFAIR_KEY_PATH: str = "./certs/betfair.key"

    # WhatsApp / Twilio (GL2 — Gladiator Bot Solutions)
    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""
    TWILIO_WHATSAPP_FROM: str = "whatsapp:+14155238886"

    # Pagos — Stripe (global)
    STRIPE_SECRET_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""
    STRIPE_PRICE_STARTER: str = ""   # $15/mes
    STRIPE_PRICE_PRO: str = ""       # $39/mes
    STRIPE_PRICE_ELITE: str = ""     # $89/mes
    STRIPE_PRICE_WA: str = ""        # $9/mes

    # Pagos — MercadoPago (Argentina)
    MP_ACCESS_TOKEN: str = ""
    MP_WEBHOOK_SECRET: str = ""

    # Anthropic (análisis IA)
    ANTHROPIC_API_KEY: str = ""

    # n8n (GL3 — Gladiator Automate)
    N8N_WEBHOOK_URL: str = ""
    N8N_API_KEY: str = ""

    class Config:
        env_file = ".env"
        case_sensitive = True

settings = Settings()
