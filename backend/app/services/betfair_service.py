"""
Servicio de ejecución automática en Betfair Exchange
Solo disponible para usuarios Plan ELITE
"""
import httpx
import json
from app.core.config import settings
from typing import Optional, Dict

BETFAIR_API_BASE = "https://api.betfair.com/exchange/betting/json-rpc/v1"
BETFAIR_LOGIN_URL = "https://identitysso-cert.betfair.com/api/certlogin"


class BetfairClient:
    def __init__(self):
        self.session_token: Optional[str] = None
        self.headers = {
            "X-Application": settings.BETFAIR_APP_KEY,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def login(self) -> bool:
        """Login con certificado SSL a Betfair"""
        async with httpx.AsyncClient(
            cert=(settings.BETFAIR_CERT_PATH, settings.BETFAIR_KEY_PATH)
        ) as client:
            resp = await client.post(
                BETFAIR_LOGIN_URL,
                data={
                    "username": settings.BETFAIR_USERNAME,
                    "password": settings.BETFAIR_PASSWORD,
                },
                headers={"X-Application": settings.BETFAIR_APP_KEY},
            )
            data = resp.json()
            if data.get("loginStatus") == "SUCCESS":
                self.session_token = data["sessionToken"]
                self.headers["X-Authentication"] = self.session_token
                return True
            return False

    async def list_events(self, sport_id: str = "1") -> list:
        """Lista eventos disponibles (1 = fútbol)"""
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                BETFAIR_API_BASE,
                headers=self.headers,
                json=[{
                    "jsonrpc": "2.0",
                    "method": "SportsAPING/v1.0/listEvents",
                    "params": {
                        "filter": {"eventTypeIds": [sport_id]},
                    },
                    "id": 1,
                }]
            )
            return resp.json()[0].get("result", [])

    async def list_market_odds(self, market_id: str) -> Dict:
        """Obtiene odds actuales de un mercado"""
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                BETFAIR_API_BASE,
                headers=self.headers,
                json=[{
                    "jsonrpc": "2.0",
                    "method": "SportsAPING/v1.0/listMarketBook",
                    "params": {
                        "marketIds": [market_id],
                        "priceProjection": {
                            "priceData": ["EX_BEST_OFFERS"],
                        },
                    },
                    "id": 1,
                }]
            )
            return resp.json()[0].get("result", [{}])[0]

    async def place_bet(
        self,
        market_id: str,
        selection_id: int,
        side: str,          # "BACK" (a favor) o "LAY" (en contra)
        price: float,
        size: float,        # Monto en USD
        customer_ref: str = "",
    ) -> Dict:
        """
        Ejecuta una apuesta en Betfair Exchange.
        
        BACK: apostar a que algo ocurre (equivale a apostar en bookmaker normal)
        LAY: apostar a que algo NO ocurre (ser el bookmaker)
        """
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                BETFAIR_API_BASE,
                headers=self.headers,
                json=[{
                    "jsonrpc": "2.0",
                    "method": "SportsAPING/v1.0/placeOrders",
                    "params": {
                        "marketId": market_id,
                        "instructions": [{
                            "selectionId": selection_id,
                            "side": side,
                            "orderType": "LIMIT",
                            "limitOrder": {
                                "size": size,
                                "price": price,
                                "persistenceType": "LAPSE",  # Cancela si no matchea
                            },
                        }],
                        "customerRef": customer_ref,
                    },
                    "id": 1,
                }]
            )
            result = resp.json()[0].get("result", {})
            return result

    async def cancel_bet(self, market_id: str, bet_id: str) -> Dict:
        """Cancela una apuesta pendiente"""
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                BETFAIR_API_BASE,
                headers=self.headers,
                json=[{
                    "jsonrpc": "2.0",
                    "method": "SportsAPING/v1.0/cancelOrders",
                    "params": {
                        "marketId": market_id,
                        "instructions": [{"betId": bet_id}],
                    },
                    "id": 1,
                }]
            )
            return resp.json()[0].get("result", {})

    async def get_account_funds(self) -> Dict:
        """Obtiene el balance disponible en Betfair"""
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://api.betfair.com/exchange/account/json-rpc/v1",
                headers=self.headers,
                json=[{
                    "jsonrpc": "2.0",
                    "method": "AccountAPING/v1.0/getAccountFunds",
                    "params": {"wallet": "UK wallet"},
                    "id": 1,
                }]
            )
            return resp.json()[0].get("result", {})


# ── Auto-execution logic ──────────────────────────────────────────────────────

betfair_client = BetfairClient()


async def auto_execute_signal(signal: dict, user_bankroll: float, risk_pct: float) -> Dict:
    """
    Ejecuta automáticamente una señal en Betfair.
    Solo para usuarios ELITE con auto_execute activado.
    
    1. Login en Betfair
    2. Calcula stake basado en Kelly / risk_pct
    3. Ejecuta la apuesta
    4. Retorna resultado
    """
    if not betfair_client.session_token:
        logged_in = await betfair_client.login()
        if not logged_in:
            return {"success": False, "error": "No se pudo conectar a Betfair"}

    # Calcular stake
    stake = min(
        user_bankroll * (risk_pct / 100),
        user_bankroll * (signal.get("kelly_pct", 2) / 100)
    )
    stake = round(max(2.0, stake), 2)  # Mínimo $2

    # Verificar fondos
    funds = await betfair_client.get_account_funds()
    available = funds.get("availableToBetBalance", 0)
    if available < stake:
        return {"success": False, "error": f"Fondos insuficientes. Disponible: ${available}"}

    # Ejecutar (en producción mapear signal a market_id/selection_id real)
    result = await betfair_client.place_bet(
        market_id=signal.get("betfair_market_id", ""),
        selection_id=signal.get("betfair_selection_id", 0),
        side="BACK",
        price=signal.get("odd", 0),
        size=stake,
        customer_ref=f"gladiator_{signal.get('id', '')}",
    )

    status = result.get("status", "")
    if status == "SUCCESS":
        bet_id = result.get("instructionReports", [{}])[0].get("betId", "")
        return {
            "success": True,
            "bet_id": bet_id,
            "stake": stake,
            "odd": signal.get("odd"),
            "potential_win": round(stake * signal.get("odd", 1), 2),
        }
    else:
        return {"success": False, "error": result.get("errorCode", "Unknown error")}
