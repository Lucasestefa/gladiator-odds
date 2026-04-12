"""
Servicio de notificaciones WhatsApp — Integración con GL2 (Gladiator Bot Solutions)
"""
from twilio.rest import Client
from app.core.config import settings
from app.models.models import User, Signal, PlanType
from sqlalchemy.orm import Session
from typing import List

client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)


def format_value_bet_message(signal: dict) -> str:
    """Formatea una señal de value bet para WhatsApp"""
    return f"""⚔️ *GLADIATOR ODDS — VALUE BET*

🎯 *{signal['match']}*
📌 Pick: {signal['pick']}
📊 Cuota: `{signal['odd']}`
🏪 Plataforma: {signal['platform']}

📈 EV: +{signal['ev_pct']}%
🎲 Prob. modelo: {signal['model_prob']}%
💰 Kelly recomendado: {signal['kelly_pct']}% del bankroll
⭐ Confianza: {signal['confidence']}%

_Gladiator Odds · gladiatorodds.com_"""


def format_arbitrage_message(signal: dict) -> str:
    """Formatea un arbitraje para WhatsApp"""
    return f"""⚔️ *GLADIATOR ODDS — ARBITRAJE*

⚡ *{signal['match']}*
💰 Ganancia garantizada: +{signal['profit_pct']}%

🟢 Apuesta 1 → {signal['platform_1']}
   {signal['pick_1']} @ `{signal['odd_1']}`
   Stake: ${signal['stake_1']}

🔵 Apuesta 2 → {signal['platform_2']}
   {signal['pick_2']} @ `{signal['odd_2']}`
   Stake: ${signal['stake_2']}

✅ Con $1,000 total → ganás ${signal['guaranteed_profit']} sin importar el resultado

_Gladiator Odds · gladiatorodds.com_"""


def format_daily_report(user: User, stats: dict) -> str:
    """Reporte diario de P&L para el usuario"""
    pnl = stats.get('pnl', 0)
    emoji = "📈" if pnl >= 0 else "📉"
    return f"""⚔️ *GLADIATOR ODDS — REPORTE DIARIO*

Hola {user.full_name or 'apostador'} 👋

{emoji} *P&L hoy: {'+'if pnl>=0 else ''}{pnl:.2f} USD*

📊 Señales recibidas: {stats.get('signals_sent', 0)}
✅ Apostadas: {stats.get('bets_placed', 0)}
🏆 Ganadas: {stats.get('wins', 0)}
❌ Perdidas: {stats.get('losses', 0)}
💼 Bankroll actual: ${stats.get('bankroll', 0):.2f}

_Seguí en gladiatorodds.com_"""


async def send_whatsapp(to_number: str, message: str) -> bool:
    """Envía mensaje de WhatsApp via Twilio"""
    try:
        msg = client.messages.create(
            from_=settings.TWILIO_WHATSAPP_FROM,
            body=message,
            to=f"whatsapp:{to_number}"
        )
        return msg.status in ["queued", "sent", "delivered"]
    except Exception as e:
        print(f"Error enviando WhatsApp a {to_number}: {e}")
        return False


async def broadcast_signal(signal: dict, db: Session, signal_type: str = "value_bet"):
    """
    Distribuye una señal a todos los usuarios según su plan.
    - WA_SIGNALS, STARTER, PRO, ELITE → reciben señales por WA
    """
    users = db.query(User).filter(
        User.subscription_active == True,
        User.whatsapp != None,
        User.is_active == True
    ).all()

    if signal_type == "value_bet":
        message = format_value_bet_message(signal)
    elif signal_type == "arbitrage":
        message = format_arbitrage_message(signal)
    else:
        return

    sent_count = 0
    for user in users:
        # Planes que reciben señales WA
        if user.plan in [PlanType.WA_SIGNALS, PlanType.STARTER, PlanType.PRO, PlanType.ELITE]:
            success = await send_whatsapp(user.whatsapp, message)
            if success:
                sent_count += 1

    return sent_count


async def send_daily_reports(db: Session):
    """
    Modo Hood: envía reporte diario automático a todos los usuarios.
    Se ejecuta todos los días a las 23:00 via scheduler.
    """
    users = db.query(User).filter(
        User.subscription_active == True,
        User.whatsapp != None
    ).all()

    for user in users:
        # Calcular stats del día (simplificado)
        from app.models.models import Bet, BetResult
        from datetime import date
        today_bets = db.query(Bet).filter(
            Bet.user_id == user.id,
            Bet.placed_at >= datetime.combine(date.today(), datetime.min.time())
        ).all()

        stats = {
            "bets_placed": len(today_bets),
            "wins": len([b for b in today_bets if b.result == BetResult.WIN]),
            "losses": len([b for b in today_bets if b.result == BetResult.LOSS]),
            "pnl": sum(b.pnl for b in today_bets),
            "bankroll": user.bankroll,
            "signals_sent": 0  # Calcular desde Notification model
        }

        message = format_daily_report(user, stats)
        await send_whatsapp(user.whatsapp, message)
