"""
Modelos de base de datos — SQLAlchemy ORM
"""
from sqlalchemy import Column, String, Float, Integer, Boolean, DateTime, ForeignKey, Enum, Text, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
from app.core.database import Base
from datetime import datetime
import uuid
import enum

# ── Enums ────────────────────────────────────────────────────────────────────

class PlanType(str, enum.Enum):
    WA_SIGNALS = "wa_signals"    # $9/mes — solo WhatsApp
    STARTER    = "starter"       # $15/mes — básico
    PRO        = "pro"           # $39/mes — completo
    ELITE      = "elite"         # $89/mes — auto-ejecución

class UserMode(str, enum.Enum):
    MANUAL    = "manual"         # Usuario apuesta manualmente
    AUTO      = "auto"           # Bot ejecuta en Betfair
    HOOD      = "hood"           # Hood gestiona todo

class SignalType(str, enum.Enum):
    VALUE_BET  = "value_bet"
    ARBITRAGE  = "arbitrage"
    AI_PRED    = "ai_prediction"

class BetResult(str, enum.Enum):
    WIN     = "win"
    LOSS    = "loss"
    VOID    = "void"
    PENDING = "pending"

class PlatformType(str, enum.Enum):
    BOOKMAKER = "bookmaker"      # Solo análisis
    EXCHANGE  = "exchange"       # Ejecución automática

# ── Modelos ───────────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id            = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email         = Column(String, unique=True, nullable=False, index=True)
    hashed_password = Column(String, nullable=False)
    full_name     = Column(String)
    whatsapp      = Column(String)              # Para envío de señales
    plan          = Column(Enum(PlanType), default=PlanType.STARTER)
    mode          = Column(Enum(UserMode), default=UserMode.MANUAL)
    is_active     = Column(Boolean, default=True)
    is_hood_managed = Column(Boolean, default=False)  # Gestionado por Hood
    bankroll      = Column(Float, default=0.0)
    risk_pct      = Column(Float, default=2.0)        # % por apuesta
    tp_ratio      = Column(Float, default=2.0)
    
    # Suscripción
    stripe_customer_id     = Column(String)
    stripe_subscription_id = Column(String)
    mp_subscription_id     = Column(String)           # MercadoPago AR
    subscription_active    = Column(Boolean, default=False)
    subscription_end       = Column(DateTime)
    
    created_at    = Column(DateTime, default=datetime.utcnow)
    updated_at    = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relaciones
    bets          = relationship("Bet", back_populates="user")
    platforms     = relationship("UserPlatform", back_populates="user")
    notifications = relationship("Notification", back_populates="user")


class Platform(Base):
    """Plataformas disponibles en el sistema (Bet365, Betfair, etc.)"""
    __tablename__ = "platforms"

    id            = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name          = Column(String, nullable=False)           # "Bet365"
    slug          = Column(String, unique=True, nullable=False)  # "bet365"
    type          = Column(Enum(PlatformType))
    region        = Column(String, default="global")
    has_api       = Column(Boolean, default=False)
    api_url       = Column(String)
    logo_url      = Column(String)
    is_active     = Column(Boolean, default=True)
    odds_api_key  = Column(String)                           # Key para The Odds API
    config        = Column(JSON)                             # Config extra por plataforma


class UserPlatform(Base):
    """Qué plataformas tiene conectadas cada usuario"""
    __tablename__ = "user_platforms"

    id            = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id       = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    platform_id   = Column(UUID(as_uuid=True), ForeignKey("platforms.id"))
    api_key       = Column(String)                           # Key del usuario en esa plataforma
    api_secret    = Column(String)
    is_active     = Column(Boolean, default=True)
    auto_execute  = Column(Boolean, default=False)           # Ejecución automática activada

    user          = relationship("User", back_populates="platforms")
    platform      = relationship("Platform")


class Signal(Base):
    """Señales generadas por el bot"""
    __tablename__ = "signals"

    id            = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    type          = Column(Enum(SignalType))
    sport         = Column(String)                           # "futbol", "basket", etc.
    league        = Column(String)
    match         = Column(String)
    pick          = Column(String)                           # "River gana", "Empate", etc.
    platform_slug = Column(String)                           # Dónde está la cuota
    odd           = Column(Float)
    model_prob    = Column(Float)                            # Probabilidad del modelo
    book_prob     = Column(Float)                            # Probabilidad implícita del book
    ev_pct        = Column(Float)                            # Expected Value %
    kelly_pct     = Column(Float)                            # % de bankroll recomendado
    confidence    = Column(Float)
    
    # Para arbitrajes
    platform_2    = Column(String)
    odd_2         = Column(Float)
    pick_2        = Column(String)
    arb_profit    = Column(Float)
    
    # Para predicciones IA
    ai_analysis   = Column(Text)
    
    event_time    = Column(DateTime)
    expires_at    = Column(DateTime)
    created_at    = Column(DateTime, default=datetime.utcnow)

    bets          = relationship("Bet", back_populates="signal")


class Bet(Base):
    """Historial de apuestas por usuario"""
    __tablename__ = "bets"

    id            = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id       = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    signal_id     = Column(UUID(as_uuid=True), ForeignKey("signals.id"), nullable=True)
    platform_slug = Column(String)
    match         = Column(String)
    pick          = Column(String)
    stake         = Column(Float)
    odd           = Column(Float)
    potential_win = Column(Float)
    result        = Column(Enum(BetResult), default=BetResult.PENDING)
    pnl           = Column(Float, default=0.0)
    is_auto       = Column(Boolean, default=False)           # Ejecutada por el bot
    betfair_bet_id = Column(String)                          # ID en Betfair
    placed_at     = Column(DateTime, default=datetime.utcnow)
    settled_at    = Column(DateTime)

    user          = relationship("User", back_populates="bets")
    signal        = relationship("Signal", back_populates="bets")


class Notification(Base):
    """Historial de notificaciones enviadas"""
    __tablename__ = "notifications"

    id            = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id       = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    channel       = Column(String)                           # "whatsapp", "email", "push"
    message       = Column(Text)
    sent          = Column(Boolean, default=False)
    sent_at       = Column(DateTime)
    created_at    = Column(DateTime, default=datetime.utcnow)

    user          = relationship("User", back_populates="notifications")


class Subscription(Base):
    """Log de eventos de suscripción"""
    __tablename__ = "subscriptions"

    id            = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id       = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    plan          = Column(Enum(PlanType))
    amount_usd    = Column(Float)
    payment_method = Column(String)                          # "stripe", "mercadopago", "crypto"
    status        = Column(String)                           # "active", "cancelled", "failed"
    period_start  = Column(DateTime)
    period_end    = Column(DateTime)
    created_at    = Column(DateTime, default=datetime.utcnow)
