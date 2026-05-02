"""
BetScan Trading Bot — Full Auto v1.0
=====================================
Psicología + Análisis Técnico + Gestión de Riesgo

Archivo: app/trading_bot.py
Se importa desde: app/main.py

Fuentes de datos:
  - CryptoCompare  → crypto OHLCV
  - AlphaVantage   → stocks + forex OHLCV
  - Polygon.io     → backup stocks
  - Alternative.me → Fear & Greed Index

Integración:
  - Telegram @betscansignals → notificaciones
  - FastAPI → endpoints de control desde el dashboard
"""

import os
import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# ================================================================
# CONFIGURACIÓN — todas las keys desde variables de entorno
# ================================================================

CRYPTOCOMPARE_KEY  = os.getenv("CRYPTOCOMPARE_API_KEY", "")
ALPHAVANTAGE_KEY   = os.getenv("ALPHAVANTAGE_API_KEY", "CGVZCOX2KGSDAN7X")
POLYGON_KEY        = os.getenv("POLYGON_API_KEY", "MH9FR7SYdr2QeEMEOpwUxJzpw9sP1N3D")
TELEGRAM_TOKEN     = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT      = os.getenv("TELEGRAM_CHAT_ID", "")

# Capital virtual
INITIAL_CAPITAL = 50_000.0

# ---- Reglas de riesgo ----------------------------------------
RISK_STRONG_BUY      = 0.10   # 10% del capital inicial por STRONG_BUY
RISK_BUY             = 0.05   # 5%  del capital inicial por BUY
STOP_LOSS_PCT        = 0.03   # -3%  → cierra posición automáticamente
TAKE_PROFIT_PCT      = 0.07   # +7%  → toma ganancia (ratio 1:2.3)
TRAILING_ACTIVATE_AT = 0.05   # +5%  → activa el trailing stop
TRAILING_STOP_PCT    = 0.02   # trailing de 2% por debajo del máximo

# ---- Filtros psicológicos ------------------------------------
MAX_OPEN_POSITIONS       = 5
MAX_CONSECUTIVE_LOSSES   = 3
DAILY_LOSS_LIMIT_PCT     = 0.06   # 6%  → pausa el bot por el día
MONTHLY_LOSS_LIMIT_PCT   = 0.15   # 15% → pausa el bot + alerta revisión
MIN_SIGNAL_SCORE         = 3      # mínimo 3/5 condiciones para entrar
MAX_ENTRY_FROM_SUPPORT   = 0.03   # no entrar si el precio está +3% del soporte (anti-FOMO)
FEAR_GREED_EUFORIA       = 80     # mercado en euforia → reducir posición
FEAR_GREED_PANICO        = 20     # mercado en pánico  → aumentar convicción

# ---- RSI: zonas según contexto de tendencia ------------------
RSI_BUY_BULLISH_MIN  = 40   # en tendencia alcista: comprar en la zona 40-45
RSI_BUY_BULLISH_MAX  = 45
RSI_SELL_BEARISH_MIN = 55   # en tendencia bajista: vender en la zona 55-60
RSI_SELL_BEARISH_MAX = 60
RSI_BUY_LATERAL      = 30   # en lateral: comprar cerca de 30
RSI_SELL_LATERAL     = 70   # en lateral: vender cerca de 70

# ---- Universo de activos -------------------------------------
CRYPTO_SYMBOLS = ["BTC", "ETH", "SOL", "BNB"]
STOCK_SYMBOLS  = ["AAPL", "NVDA", "SPY", "TSLA"]
FOREX_PAIRS    = [("EUR", "USD"), ("GBP", "USD")]


# ================================================================
# DATA FETCHER — obtiene OHLCV de cada fuente
# ================================================================

class DataFetcher:

    def get_crypto_ohlcv(self, symbol: str, limit: int = 200) -> List[dict]:
        """CryptoCompare — histórico diario de crypto"""
        url = "https://min-api.cryptocompare.com/data/v2/histoday"
        params = {"fsym": symbol, "tsym": "USDT", "limit": limit}
        headers = {"authorization": f"Apikey {CRYPTOCOMPARE_KEY}"} if CRYPTOCOMPARE_KEY else {}
        try:
            r = requests.get(url, params=params, headers=headers, timeout=10)
            r.raise_for_status()
            return r.json().get("Data", {}).get("Data", [])
        except Exception as e:
            logging.error(f"CryptoCompare error [{symbol}]: {e}")
            return []

    def get_stock_ohlcv(self, symbol: str) -> List[dict]:
        """AlphaVantage — histórico diario de acciones"""
        url = "https://www.alphavantage.co/query"
        params = {
            "function":   "TIME_SERIES_DAILY",
            "symbol":     symbol,
            "outputsize": "compact",
            "apikey":     ALPHAVANTAGE_KEY,
        }
        try:
            r = requests.get(url, params=params, timeout=10)
            r.raise_for_status()
            ts = r.json().get("Time Series (Daily)", {})
            result = []
            for date in sorted(ts.keys()):
                v = ts[date]
                result.append({
                    "time":   date,
                    "open":   float(v["1. open"]),
                    "high":   float(v["2. high"]),
                    "low":    float(v["3. low"]),
                    "close":  float(v["4. close"]),
                    "volume": float(v["5. volume"]),
                })
            time.sleep(15)
            return result
        except Exception as e:
            logging.error(f"AlphaVantage error [{symbol}]: {e}")
            return []

    def get_forex_ohlcv(self, from_sym: str, to_sym: str) -> List[dict]:
        """AlphaVantage — histórico diario de forex"""
        url = "https://www.alphavantage.co/query"
        params = {
            "function":    "FX_DAILY",
            "from_symbol": from_sym,
            "to_symbol":   to_sym,
            "outputsize":  "compact",
            "apikey":      ALPHAVANTAGE_KEY,
        }
        try:
            r = requests.get(url, params=params, timeout=10)
            r.raise_for_status()
            ts = r.json().get("Time Series FX (Daily)", {})
            result = []
            for date in sorted(ts.keys()):
                v = ts[date]
                result.append({
                    "time":   date,
                    "open":   float(v["1. open"]),
                    "high":   float(v["2. high"]),
                    "low":    float(v["3. low"]),
                    "close":  float(v["4. close"]),
                    "volume": 0.0,
                })
            return result
        except Exception as e:
            logging.error(f"AlphaVantage Forex error [{from_sym}/{to_sym}]: {e}")
            return []

    def get_fear_greed(self) -> int:
        """Alternative.me Fear & Greed Index (0=pánico, 100=euforia)"""
        try:
            r = requests.get("https://api.alternative.me/fng/", timeout=5)
            return int(r.json()["data"][0]["value"])
        except:
            return 50  # neutral como fallback


# ================================================================
# ANÁLISIS TÉCNICO
# ================================================================

class TechnicalAnalysis:

    # ---- RSI ---------------------------------------------------

    def calculate_rsi(self, closes: List[float], period: int = 14) -> List[float]:
        if len(closes) < period + 1:
            return []
        deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
        gains  = [max(d, 0.0) for d in deltas]
        losses = [abs(min(d, 0.0)) for d in deltas]

        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period
        rsi_list = []

        for i in range(period, len(deltas)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period
            if avg_loss == 0:
                rsi_list.append(100.0)
            else:
                rs = avg_gain / avg_loss
                rsi_list.append(round(100 - (100 / (1 + rs)), 2))

        return rsi_list

    def rsi_in_buy_zone(self, rsi: float, trend: str) -> bool:
        """
        Tendencia alcista : comprar cuando RSI toca 40-45
        Tendencia lateral : comprar cuando RSI toca ~30
        (No esperar 30 en alcista — el precio nunca llega ahí)
        """
        if trend == "BULLISH":
            return RSI_BUY_BULLISH_MIN <= rsi <= RSI_BUY_BULLISH_MAX
        if trend == "LATERAL":
            return rsi <= RSI_BUY_LATERAL
        return False

    def rsi_in_sell_zone(self, rsi: float, trend: str) -> bool:
        """
        Tendencia bajista : vender cuando RSI toca 55-60
        Tendencia lateral : vender cuando RSI toca ~70
        """
        if trend == "BEARISH":
            return RSI_SELL_BEARISH_MIN <= rsi <= RSI_SELL_BEARISH_MAX
        if trend == "LATERAL":
            return rsi >= RSI_SELL_LATERAL
        return False

    # ---- Medias Móviles ----------------------------------------

    def calculate_ma(self, closes: List[float], period: int) -> List[float]:
        if len(closes) < period:
            return []
        return [sum(closes[i - period:i]) / period for i in range(period, len(closes) + 1)]

    # ---- Tendencia ---------------------------------------------

    def detect_trend(self, closes: List[float]) -> str:
        """
        BULLISH : precio > MA50 > MA200
        BEARISH : precio < MA50 < MA200
        LATERAL : cualquier otra combinación
        """
        if len(closes) < 200:
            return "UNDEFINED"
        ma50  = self.calculate_ma(closes, 50)
        ma200 = self.calculate_ma(closes, 200)
        if not ma50 or not ma200:
            return "UNDEFINED"
        price = closes[-1]
        if price > ma50[-1] > ma200[-1]:
            return "BULLISH"
        if price < ma50[-1] < ma200[-1]:
            return "BEARISH"
        return "LATERAL"

    # ---- Divergencias ------------------------------------------

    def detect_divergence(self, closes: List[float], rsi: List[float], lookback: int = 20) -> str:
        """
        Divergencia ALCISTA:
            precio hace mínimo MÁS BAJO   → RSI hace mínimo MÁS ALTO
            → el precio cae pero el momentum no → reversión probable

        Divergencia BAJISTA:
            precio hace máximo MÁS ALTO   → RSI hace máximo MÁS BAJO
            → el precio sube pero el momentum se agota → techo probable
        """
        if len(closes) < lookback or len(rsi) < lookback:
            return "NONE"

        rc = closes[-lookback:]
        rr = rsi[-lookback:]

        price_mins, rsi_mins, price_maxs, rsi_maxs = [], [], [], []

        for i in range(1, len(rc) - 1):
            if rc[i] < rc[i - 1] and rc[i] < rc[i + 1]:
                price_mins.append(rc[i])
                rsi_mins.append(rr[i])
            if rc[i] > rc[i - 1] and rc[i] > rc[i + 1]:
                price_maxs.append(rc[i])
                rsi_maxs.append(rr[i])

        # Divergencia alcista
        if len(price_mins) >= 2 and len(rsi_mins) >= 2:
            if price_mins[-1] < price_mins[-2] and rsi_mins[-1] > rsi_mins[-2]:
                return "BULLISH_DIVERGENCE"

        # Divergencia bajista
        if len(price_maxs) >= 2 and len(rsi_maxs) >= 2:
            if price_maxs[-1] > price_maxs[-2] and rsi_maxs[-1] < rsi_maxs[-2]:
                return "BEARISH_DIVERGENCE"

        return "NONE"

    # ---- Soporte y Resistencia ---------------------------------

    def find_support_resistance(self, closes: List[float], window: int = 20) -> Tuple[float, float]:
        """Mínimo y máximo de los últimos N cierres"""
        recent = closes[-window:] if len(closes) >= window else closes
        return min(recent), max(recent)

    # ---- Volumen -----------------------------------------------

    def volume_confirms(self, volumes: List[float]) -> bool:
        """El volumen actual supera el promedio de 20 días en al menos 10%"""
        if len(volumes) < 21:
            return False
        avg = sum(volumes[-21:-1]) / 20
        return volumes[-1] > avg * 1.1 if avg > 0 else False


# ================================================================
# SIGNAL SCORER — puntúa 0 a 5
# ================================================================

class SignalScorer:

    def __init__(self):
        self.ta = TechnicalAnalysis()

    def score(
        self,
        closes:    List[float],
        volumes:   List[float],
        direction: str,
    ) -> Tuple[int, dict]:
        """
        Evalúa 5 condiciones independientes.
        Retorna (puntaje, detalle).
        Mínimo necesario para operar: MIN_SIGNAL_SCORE (3)

        Condiciones BUY:
          1. Tendencia favorable (BULLISH o LATERAL)
          2. RSI en zona de compra según tendencia
          3. Precio cerca del soporte (≤2%)
          4. Volumen por encima del promedio
          5. Divergencia alcista detectada

        Condiciones SELL:
          1. Tendencia favorable (BEARISH o LATERAL)
          2. RSI en zona de venta según tendencia
          3. Precio cerca de la resistencia (≤2%)
          4. Volumen por encima del promedio
          5. Divergencia bajista detectada
        """
        rsi_values = self.ta.calculate_rsi(closes)
        if not rsi_values:
            return 0, {"error": "datos insuficientes para RSI"}

        current_rsi = rsi_values[-1]
        trend       = self.ta.detect_trend(closes)
        divergence  = self.ta.detect_divergence(closes, rsi_values)
        support, resistance = self.ta.find_support_resistance(closes)
        price       = closes[-1]

        checks = {}

        if direction == "BUY":
            checks["tendencia_favorable"] = trend in ("BULLISH", "LATERAL")
            checks["rsi_zona_compra"]     = self.ta.rsi_in_buy_zone(current_rsi, trend)
            checks["precio_en_soporte"]   = abs(price - support) / support <= 0.02
            checks["volumen_confirma"]    = self.ta.volume_confirms(volumes)
            checks["divergencia_alcista"] = divergence == "BULLISH_DIVERGENCE"

        elif direction == "SELL":
            checks["tendencia_favorable"]    = trend in ("BEARISH", "LATERAL")
            checks["rsi_zona_venta"]         = self.ta.rsi_in_sell_zone(current_rsi, trend)
            checks["precio_en_resistencia"]  = abs(price - resistance) / resistance <= 0.02
            checks["volumen_confirma"]       = self.ta.volume_confirms(volumes)
            checks["divergencia_bajista"]    = divergence == "BEARISH_DIVERGENCE"

        score = sum(1 for v in checks.values() if v)

        return score, {
            "score":      score,
            "rsi":        current_rsi,
            "trend":      trend,
            "divergence": divergence,
            "support":    round(support, 6),
            "resistance": round(resistance, 6),
            "checks":     checks,
        }


# ================================================================
# FILTROS PSICOLÓGICOS — 7 sesgos eliminados
# ================================================================

class PsychologyFilters:
    """
    Cada método bloquea un sesgo cognitivo específico.

    Sesgo 1 — Euforia/Pánico    : ajusta tamaño según Fear & Greed
    Sesgo 2 — Revenge trading   : pausa tras límite de pérdida diaria
    Sesgo 3 — Racha negativa    : pausa tras N pérdidas consecutivas
    Sesgo 4 — Averaging down    : bloquea comprar lo que está en pérdida
    Sesgo 5 — FOMO              : bloquea entrar lejos del soporte
    Sesgo 6 — Overtrading       : límite de posiciones simultáneas
    Sesgo 7 — Límite mensual    : pausa si la pérdida mensual es excesiva
    """

    def get_position_multiplier(self, fear_greed: int) -> float:
        """Ajusta el tamaño de posición según el estado emocional del mercado"""
        if fear_greed > FEAR_GREED_EUFORIA:
            return 0.5   # mercado en euforia → mitad del tamaño normal
        if fear_greed < FEAR_GREED_PANICO:
            return 1.5   # mercado en pánico  → mayor convicción, más tamaño
        return 1.0

    def check_all(
        self,
        symbol:      str,
        direction:   str,
        portfolio:   "Portfolio",
        fear_greed:  int,
    ) -> Tuple[bool, List[str]]:
        """
        Corre los 7 filtros en orden.
        Retorna (todo_ok, lista_de_fallos).
        """
        failures = []

        # 1. Bot activo
        if portfolio.status != "RUNNING":
            failures.append(f"bot_pausado: {portfolio.pause_reason}")

        # 2. Límite de pérdida diaria (anti revenge trading)
        if portfolio.daily_pnl_pct <= -DAILY_LOSS_LIMIT_PCT:
            failures.append("limite_diario_6pct_alcanzado")
            portfolio.pause("Límite pérdida diaria 6%")

        # 3. Racha de pérdidas consecutivas (anti revenge trading)
        if portfolio.consecutive_losses >= MAX_CONSECUTIVE_LOSSES:
            failures.append("3_perdidas_consecutivas_pausa_24h")
            portfolio.pause("3 pérdidas consecutivas")

        # 4. Anti averaging down — no comprar posición que está en pérdida
        if direction == "BUY" and symbol in portfolio.positions:
            pos = portfolio.positions[symbol]
            if pos["current_price"] < pos["avg_price"]:
                failures.append("averaging_down_bloqueado")

        # 5. Anti FOMO — no entrar si el precio ya subió mucho desde el soporte
        if direction == "BUY" and symbol in portfolio.entry_distances:
            if portfolio.entry_distances[symbol] > MAX_ENTRY_FROM_SUPPORT:
                failures.append("fomo_precio_lejos_del_soporte")

        # 6. Máximo de posiciones simultáneas (anti overtrading)
        if direction == "BUY" and len(portfolio.positions) >= MAX_OPEN_POSITIONS:
            failures.append("maximo_5_posiciones_abiertas")

        # 7. Límite de pérdida mensual
        if portfolio.monthly_pnl_pct <= -MONTHLY_LOSS_LIMIT_PCT:
            failures.append("limite_mensual_15pct_revision_requerida")
            portfolio.pause("Límite pérdida mensual 15%")

        return len(failures) == 0, failures


# ================================================================
# PORTFOLIO — estado completo del capital y posiciones
# ================================================================

class Portfolio:

    def __init__(self):
        self.capital         = INITIAL_CAPITAL
        self.positions: Dict[str, dict] = {}
        self.trades:    List[dict]      = []
        self.equity_curve               = [INITIAL_CAPITAL]

        # Estado del bot
        self.status       = "RUNNING"
        self.pause_reason = ""

        # Métricas de riesgo
        self.consecutive_losses   = 0
        self.daily_pnl_pct        = 0.0
        self.monthly_pnl_pct      = 0.0
        self.start_of_day_equity  = INITIAL_CAPITAL
        self.start_of_month_equity = INITIAL_CAPITAL
        self.entry_distances: Dict[str, float] = {}

    # ---- Control del bot ---------------------------------------

    def pause(self, reason: str):
        self.status       = "PAUSED"
        self.pause_reason = reason
        logging.warning(f"[BOT PAUSADO] {reason}")

    def resume(self):
        self.status             = "RUNNING"
        self.pause_reason       = ""
        self.consecutive_losses = 0
        logging.info("[BOT REANUDADO]")

    def reset_daily(self):
        """Llamar al inicio de cada día de trading"""
        pos_value = sum(p["qty"] * p["current_price"] for p in self.positions.values())
        self.start_of_day_equity = self.capital + pos_value
        self.daily_pnl_pct       = 0.0
        # Si el bot estaba pausado por límite diario, se reactiva
        if self.pause_reason == "Límite pérdida diaria 6%":
            self.resume()

    # ---- Abrir posición ----------------------------------------

    def open_position(self, symbol: str, price: float, signal_type: str, multiplier: float = 1.0) -> bool:
        base_alloc = INITIAL_CAPITAL * (RISK_STRONG_BUY if signal_type == "STRONG_BUY" else RISK_BUY)
        allocation = base_alloc * multiplier

        if self.capital < allocation:
            logging.warning(f"[SKIP] Capital insuficiente para {symbol} (necesita ${allocation:,.0f})")
            return False

        qty         = allocation / price
        stop_loss   = round(price * (1 - STOP_LOSS_PCT), 6)
        take_profit = round(price * (1 + TAKE_PROFIT_PCT), 6)

        if symbol in self.positions:
            # Pyramiding permitido solo si la posición está en ganancia
            pos = self.positions[symbol]
            if pos["current_price"] < pos["avg_price"]:
                logging.warning(f"[SKIP] Pyramiding bloqueado en {symbol} — posición en pérdida")
                return False
            total_qty       = pos["qty"] + qty
            pos["avg_price"] = (pos["avg_price"] * pos["qty"] + price * qty) / total_qty
            pos["qty"]       = total_qty
        else:
            self.positions[symbol] = {
                "qty":              qty,
                "avg_price":        price,
                "current_price":    price,
                "stop_loss":        stop_loss,
                "take_profit":      take_profit,
                "trailing_stop":    None,
                "trailing_active":  False,
                "max_price_seen":   price,
                "opened_at":        datetime.now().isoformat(),
                "signal_type":      signal_type,
            }

        self.capital -= allocation
        self.trades.append({
            "action":      "BUY",
            "symbol":      symbol,
            "price":       price,
            "qty":         qty,
            "allocation":  round(allocation, 2),
            "signal_type": signal_type,
            "timestamp":   datetime.now().isoformat(),
        })
        logging.info(f"[OPEN] {signal_type} {symbol} @ ${price:,.4f} | SL: ${stop_loss:,.4f} | TP: ${take_profit:,.4f}")
        return True

    # ---- Cerrar posición ---------------------------------------

    def close_position(self, symbol: str, price: float, reason: str) -> Optional[float]:
        if symbol not in self.positions:
            return None

        pos      = self.positions[symbol]
        proceeds = pos["qty"] * price
        cost     = pos["qty"] * pos["avg_price"]
        pnl      = proceeds - cost
        pnl_pct  = pnl / cost * 100

        self.capital += proceeds

        self.trades.append({
            "action":    "SELL",
            "symbol":    symbol,
            "price":     price,
            "qty":       pos["qty"],
            "proceeds":  round(proceeds, 2),
            "pnl":       round(pnl, 2),
            "pnl_pct":   round(pnl_pct, 2),
            "reason":    reason,
            "timestamp": datetime.now().isoformat(),
        })

        if pnl < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0

        del self.positions[symbol]
        logging.info(f"[CLOSE] {reason} {symbol} @ ${price:,.4f} | P&L: ${pnl:+,.2f} ({pnl_pct:+.2f}%)")
        return pnl

    # ---- Actualizar precios y chequear stops -------------------

    def update_prices(self, prices: Dict[str, float]) -> List[dict]:
        """
        En cada tick:
        1. Actualiza precios de posiciones abiertas
        2. Activa/actualiza trailing stop si corresponde
        3. Chequea stop loss, trailing stop y take profit
        4. Cierra las posiciones que tocaron algún límite
        5. Actualiza la curva de equity
        6. Recalcula P&L diario y mensual
        """
        stops_triggered = []

        for symbol, pos in list(self.positions.items()):
            if symbol not in prices:
                continue

            price   = prices[symbol]
            pos["current_price"] = price

            # Actualizar máximo histórico de la posición
            if price > pos["max_price_seen"]:
                pos["max_price_seen"] = price

            pnl_pct = (price - pos["avg_price"]) / pos["avg_price"]

            # ---- Trailing stop ---------------------------------
            # Se activa cuando la ganancia supera TRAILING_ACTIVATE_AT (+5%)
            if pnl_pct >= TRAILING_ACTIVATE_AT and not pos["trailing_active"]:
                pos["trailing_active"] = True
                pos["trailing_stop"]   = price * (1 - TRAILING_STOP_PCT)
                logging.info(f"[TRAILING] Activado {symbol} → stop en ${pos['trailing_stop']:,.4f}")

            # Actualizar nivel del trailing (solo sube, nunca baja)
            if pos["trailing_active"]:
                new_trail = price * (1 - TRAILING_STOP_PCT)
                if new_trail > pos["trailing_stop"]:
                    pos["trailing_stop"] = new_trail

            # ---- Chequeo de stops ------------------------------
            if price <= pos["stop_loss"]:
                stops_triggered.append({"symbol": symbol, "price": price, "reason": "STOP_LOSS"})

            elif pos["trailing_active"] and price <= pos["trailing_stop"]:
                stops_triggered.append({"symbol": symbol, "price": price, "reason": "TRAILING_STOP"})

            elif price >= pos["take_profit"]:
                stops_triggered.append({"symbol": symbol, "price": price, "reason": "TAKE_PROFIT"})

        # Ejecutar los cierres
        for event in stops_triggered:
            pnl = self.close_position(event["symbol"], event["price"], event["reason"])
            event["pnl"] = pnl

        # ---- Actualizar equity ---------------------------------
        pos_value = sum(p["qty"] * p["current_price"] for p in self.positions.values())
        total_eq  = self.capital + pos_value
        self.equity_curve.append(round(total_eq, 2))

        # P&L diario y mensual
        if self.start_of_day_equity > 0:
            self.daily_pnl_pct = (total_eq - self.start_of_day_equity) / self.start_of_day_equity
        if self.start_of_month_equity > 0:
            self.monthly_pnl_pct = (total_eq - self.start_of_month_equity) / self.start_of_month_equity

        return stops_triggered

    # ---- Resumen -----------------------------------------------

    def get_summary(self) -> dict:
        pos_value = sum(p["qty"] * p["current_price"] for p in self.positions.values())
        total_eq  = self.capital + pos_value
        pnl       = total_eq - INITIAL_CAPITAL
        sells     = [t for t in self.trades if t["action"] == "SELL"]
        wins      = [t for t in sells if t.get("pnl", 0) > 0]
        stops     = [t for t in sells if t.get("reason") == "STOP_LOSS"]

        return {
            "capital_libre":        round(self.capital, 2),
            "posiciones_valor":     round(pos_value, 2),
            "equity_total":         round(total_eq, 2),
            "pnl_neto":             round(pnl, 2),
            "pnl_pct":              round(pnl / INITIAL_CAPITAL * 100, 2),
            "posiciones_abiertas":  len(self.positions),
            "trades_totales":       len(self.trades),
            "win_rate":             round(len(wins) / len(sells) * 100, 1) if sells else 0,
            "stop_losses_fired":    len(stops),
            "perdidas_consecutivas": self.consecutive_losses,
            "daily_pnl_pct":        round(self.daily_pnl_pct * 100, 2),
            "monthly_pnl_pct":      round(self.monthly_pnl_pct * 100, 2),
            "status":               self.status,
            "pause_reason":         self.pause_reason,
            "equity_curve":         self.equity_curve[-60:],  # últimos 60 puntos
            "posiciones_detalle":   {
                sym: {
                    "qty":             round(p["qty"], 6),
                    "avg_price":       round(p["avg_price"], 4),
                    "current_price":   round(p["current_price"], 4),
                    "pnl_pct":         round((p["current_price"] - p["avg_price"]) / p["avg_price"] * 100, 2),
                    "stop_loss":       round(p["stop_loss"], 4),
                    "take_profit":     round(p["take_profit"], 4),
                    "trailing_active": p["trailing_active"],
                    "trailing_stop":   round(p["trailing_stop"], 4) if p["trailing_stop"] else None,
                    "opened_at":       p["opened_at"],
                    "signal_type":     p["signal_type"],
                }
                for sym, p in self.positions.items()
            },
        }


# ================================================================
# NOTIFICACIONES TELEGRAM
# ================================================================

class Notifier:

    def send(self, message: str):
        if not TELEGRAM_TOKEN or not TELEGRAM_CHAT:
            logging.info(f"[TELEGRAM MOCK] {message}")
            return
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            requests.post(
                url,
                json={"chat_id": TELEGRAM_CHAT, "text": message, "parse_mode": "Markdown"},
                timeout=5,
            )
        except Exception as e:
            logging.error(f"[TELEGRAM ERROR] {e}")


# ================================================================
# BOT PRINCIPAL
# ================================================================

class TradingBot:
    """
    Orquesta todo el flujo:
    DataFetcher → TechnicalAnalysis → SignalScorer
    → PsychologyFilters → Portfolio → Notifier

    Cada ciclo:
    1. Obtiene Fear & Greed Index
    2. Analiza cada activo del universo
    3. Puntúa las señales (mínimo 3/5)
    4. Pasa los 7 filtros psicológicos
    5. Ejecuta las señales válidas
    6. Actualiza precios y chequea stops automáticamente
    7. Notifica por Telegram
    """

    def __init__(self):
        self.fetcher    = DataFetcher()
        self.scorer     = SignalScorer()
        self.psych      = PsychologyFilters()
        self.portfolio  = Portfolio()
        self.notifier   = Notifier()
        self.running    = False
        self.fear_greed = 50
        self.last_prices: Dict[str, float] = {}
        self.last_signals: List[dict]      = []
        self.cycle_count = 0

    # ---- Análisis de un activo ---------------------------------

    def analyze_asset(self, symbol: str, asset_type: str) -> Optional[dict]:
        """
        Analiza un activo, retorna señal si supera el score mínimo.
        """
        # Obtener OHLCV
        if asset_type == "crypto":
            raw     = self.fetcher.get_crypto_ohlcv(symbol)
            closes  = [d["close"]    for d in raw if d.get("close")]
            volumes = [d.get("volumeto", 0) for d in raw]
        elif asset_type == "stock":
            raw     = self.fetcher.get_stock_ohlcv(symbol)
            closes  = [d["close"]  for d in raw]
            volumes = [d["volume"] for d in raw]
        elif asset_type == "forex":
            pair    = symbol.split("/")
            raw     = self.fetcher.get_forex_ohlcv(pair[0], pair[1])
            closes  = [d["close"]  for d in raw]
            volumes = [0.0] * len(closes)
        else:
            return None

        if len(closes) < 50:
            logging.warning(f"[SKIP] {symbol} — datos insuficientes ({len(closes)} velas)")
            return None

        # Guardar precio actual
        current_price = closes[-1]
        self.last_prices[symbol] = current_price

        # Calcular indicadores rápidos para determinar dirección sugerida
        ta          = self.scorer.ta
        rsi_values  = ta.calculate_rsi(closes)
        trend       = ta.detect_trend(closes)
        divergence  = ta.detect_divergence(closes, rsi_values) if rsi_values else "NONE"
        current_rsi = rsi_values[-1] if rsi_values else 50.0
        support, _  = ta.find_support_resistance(closes)

        # Distancia del precio al soporte (para filtro FOMO)
        dist_from_support = (current_price - support) / support if support > 0 else 0
        self.portfolio.entry_distances[symbol] = dist_from_support

        # Determinar dirección
        direction = None
        if ta.rsi_in_buy_zone(current_rsi, trend) or divergence == "BULLISH_DIVERGENCE":
            direction = "BUY"
        elif ta.rsi_in_sell_zone(current_rsi, trend) or divergence == "BEARISH_DIVERGENCE":
            direction = "SELL"

        if not direction:
            return None

        # Puntuar señal
        score, analysis = self.scorer.score(closes, volumes, direction)

        if score < MIN_SIGNAL_SCORE:
            logging.info(f"[SKIP] {symbol} score {score}/5 < mínimo {MIN_SIGNAL_SCORE}")
            return None

        return {
            "symbol":      symbol,
            "asset_type":  asset_type,
            "direction":   direction,
            "price":       current_price,
            "score":       score,
            "signal_type": "STRONG_BUY" if score >= 4 and direction == "BUY" else direction,
            "analysis":    analysis,
            "timestamp":   datetime.now().isoformat(),
        }

    # ---- Ejecutar señal ----------------------------------------

    def execute_signal(self, signal: dict, multiplier: float = 1.0):
        symbol      = signal["symbol"]
        direction   = signal["direction"]
        price       = signal["price"]
        signal_type = signal["signal_type"]
        score       = signal["score"]
        analysis    = signal["analysis"]

        if direction == "BUY":
            success = self.portfolio.open_position(symbol, price, signal_type, multiplier)
            if success:
                pos = self.portfolio.positions.get(symbol, {})
                self.notifier.send(
                    f"🟢 *{signal_type}* ejecutado\n"
                    f"*{symbol}* @ `${price:,.4f}`\n"
                    f"Score: {score}/5 · RSI: {analysis['rsi']} · Tendencia: {analysis['trend']}\n"
                    f"Divergencia: {analysis['divergence']}\n"
                    f"SL: `${pos.get('stop_loss', 0):,.4f}` · TP: `${pos.get('take_profit', 0):,.4f}`"
                )

        elif direction == "SELL":
            if symbol in self.portfolio.positions:
                pnl = self.portfolio.close_position(symbol, price, "SEÑAL_VENTA")
                if pnl is not None:
                    emoji = "🟢" if pnl > 0 else "🔴"
                    self.notifier.send(
                        f"{emoji} *SELL* ejecutado\n"
                        f"*{symbol}* @ `${price:,.4f}`\n"
                        f"Score: {score}/5 · P&L: `${pnl:+,.2f}`"
                    )

    # ---- Ciclo completo ----------------------------------------

    def run_cycle(self) -> dict:
        """
        Un ciclo de análisis completo.
        Llamado automáticamente cada N minutos por el loop.
        También expuesto vía FastAPI para llamada manual desde el dashboard.
        """
        self.cycle_count += 1
        logging.info(f"[CICLO {self.cycle_count}] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        # 1. Estado emocional del mercado
        self.fear_greed = self.fetcher.get_fear_greed()
        multiplier      = self.psych.get_position_multiplier(self.fear_greed)
        logging.info(f"[MARKET] Fear & Greed: {self.fear_greed} → multiplicador: {multiplier}x")

        signals_found    = []
        signals_blocked  = []

        # 2. Analizar crypto
        for sym in CRYPTO_SYMBOLS:
            signal = self.analyze_asset(sym, "crypto")
            if signal:
                ok, failures = self.psych.check_all(sym, signal["direction"], self.portfolio, self.fear_greed)
                signal["psych_ok"]       = ok
                signal["psych_failures"] = failures
                if ok:
                    self.execute_signal(signal, multiplier)
                    signals_found.append(signal)
                else:
                    logging.info(f"[BLOQUEADO] {sym} → {failures}")
                    signals_blocked.append({**signal, "failures": failures})

        # 3. Analizar stocks
        for sym in STOCK_SYMBOLS:
            signal = self.analyze_asset(sym, "stock")
            if signal:
                ok, failures = self.psych.check_all(sym, signal["direction"], self.portfolio, self.fear_greed)
                signal["psych_ok"]       = ok
                signal["psych_failures"] = failures
                if ok:
                    self.execute_signal(signal, multiplier)
                    signals_found.append(signal)
                else:
                    signals_blocked.append({**signal, "failures": failures})

        # 4. Analizar forex
        for from_sym, to_sym in FOREX_PAIRS:
            sym    = f"{from_sym}/{to_sym}"
            signal = self.analyze_asset(sym, "forex")
            if signal:
                ok, failures = self.psych.check_all(sym, signal["direction"], self.portfolio, self.fear_greed)
                signal["psych_ok"]       = ok
                signal["psych_failures"] = failures
                if ok:
                    self.execute_signal(signal, multiplier)
                    signals_found.append(signal)
                else:
                    signals_blocked.append({**signal, "failures": failures})

        # 5. Actualizar precios y chequear stops automáticamente
        stops = self.portfolio.update_prices(self.last_prices)
        for event in stops:
            emoji = {"STOP_LOSS": "🔴", "TRAILING_STOP": "🟡", "TAKE_PROFIT": "🟢"}.get(event["reason"], "⚪")
            self.notifier.send(
                f"{emoji} *{event['reason']}*\n"
                f"*{event['symbol']}* @ `${event['price']:,.4f}` · "
                f"P&L: `${event.get('pnl', 0):+,.2f}`"
            )

        self.last_signals = signals_found + signals_blocked
        summary = self.portfolio.get_summary()

        logging.info(
            f"[RESUMEN] Equity: ${summary['equity_total']:,.2f} | "
            f"P&L: {summary['pnl_pct']:+.2f}% | "
            f"Pos: {summary['posiciones_abiertas']} | "
            f"Status: {summary['status']}"
        )

        return {
            "cycle":            self.cycle_count,
            "fear_greed":       self.fear_greed,
            "multiplier":       multiplier,
            "signals_executed": len(signals_found),
            "signals_blocked":  len(signals_blocked),
            "stops_triggered":  len(stops),
            "summary":          summary,
        }

    # ---- Loop principal ----------------------------------------

    async def start(self, interval_minutes: int = 60):
        """Loop asíncrono — corre cada N minutos"""
        self.running = True
        logging.info(f"[BOT] Iniciado — ciclo cada {interval_minutes} minutos")
        self.notifier.send(
            f"🚀 *BetScan Trading Bot iniciado*\n"
            f"Capital: `${INITIAL_CAPITAL:,.0f}` · Ciclo: {interval_minutes}min\n"
            f"Universo: {len(CRYPTO_SYMBOLS)} crypto · {len(STOCK_SYMBOLS)} stocks · {len(FOREX_PAIRS)} forex"
        )
        while self.running:
            try:
                self.run_cycle()
            except Exception as e:
                logging.error(f"[ERROR CICLO] {e}")
                self.notifier.send(f"⚠️ *Error en ciclo del bot*\n`{str(e)}`")
            await asyncio.sleep(interval_minutes * 60)

    def stop(self):
        self.running = False
        logging.info("[BOT] Detenido")
        self.notifier.send("⏹ *BetScan Trading Bot detenido*")


# ================================================================
# INSTANCIA GLOBAL — importada desde main.py
# ================================================================

bot = TradingBot()
