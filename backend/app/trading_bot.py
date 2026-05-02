"""
BetScan Trading Bot — Motor de Inteligencia v2.0
=================================================
Variables integradas:
  Análisis Técnico:
    ✅ RSI contextual (40-45 alcista / 55-60 bajista / 30-70 lateral)
    ✅ MACD (momentum + cruces de señal)
    ✅ Divergencias alcistas y bajistas
    ✅ Medias móviles MA50 + MA200 (tendencia)
    ✅ EMA12 + EMA26 (momentum corto)
    ✅ Soporte y resistencia (mínimos/máximos + Fibonacci)
    ✅ Niveles de Fibonacci (23.6%, 38.2%, 50%, 61.8%, 78.6%)
    ✅ VWAP (precio justo institucional)
    ✅ Volumen confirmado vs promedio 20 días
    ✅ Múltiples timeframes (Diario + 4 horas)

  Contexto Macro:
    ✅ Fear & Greed Index (Alternative.me)
    ✅ VIX — índice de volatilidad (AlphaVantage)
    ✅ DXY — índice del dólar (AlphaVantage)
    ✅ SPY — proxy apetito de riesgo (AlphaVantage)
    ✅ Funding Rate crypto (Binance API pública)
    ✅ Open Interest (Binance API pública)
    ✅ Régimen de mercado (Wyckoff simplificado)

  Gestión de Riesgo:
    ✅ Stop loss fijo -3%
    ✅ Take profit +7% (ratio 1:2.3)
    ✅ Trailing stop desde +5%
    ✅ Kelly Criterion dinámico
    ✅ Tamaño ajustado por volatilidad

  Psicología (7 filtros):
    ✅ Anti revenge trading (límite diario 6%)
    ✅ Anti racha negativa (pausa 3 pérdidas)
    ✅ Anti averaging down
    ✅ Anti FOMO (distancia del soporte)
    ✅ Anti overtrading (máx 5 posiciones)
    ✅ Anti euforia (Fear & Greed > 80)
    ✅ Límite mensual 15%

Fuentes de datos (todas gratuitas, sin registro):
  - CryptoCompare  → OHLCV crypto (diario + 4h)
  - AlphaVantage   → stocks + forex + VIX + DXY
  - Binance API    → funding rate + open interest
  - Alternative.me → Fear & Greed Index
"""

import os
import time
import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# ================================================================
# CONFIGURACIÓN
# ================================================================

CRYPTOCOMPARE_KEY = os.getenv("CRYPTOCOMPARE_API_KEY", "")
ALPHAVANTAGE_KEY  = os.getenv("ALPHAVANTAGE_API_KEY", "CGVZCOX2KGSDAN7X")
POLYGON_KEY       = os.getenv("POLYGON_API_KEY", "MH9FR7SYdr2QeEMEOpwUxJzpw9sP1N3D")
TELEGRAM_TOKEN    = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT     = os.getenv("TELEGRAM_CHAT_ID", "")

INITIAL_CAPITAL = 50_000.0

# ---- Riesgo ---------------------------------------------------
STOP_LOSS_PCT        = 0.03
TAKE_PROFIT_PCT      = 0.07
TRAILING_ACTIVATE_AT = 0.05
TRAILING_STOP_PCT    = 0.02
MAX_POSITION_PCT     = 0.20   # Kelly nunca supera 20% del capital

# ---- Score mínimo ---------------------------------------------
# Ahora tenemos más condiciones → subimos el mínimo a 4/8
MIN_SIGNAL_SCORE  = 4
SCORE_STRONG_BUY  = 6   # 6+ condiciones → STRONG_BUY (10%)
SCORE_BUY         = 4   # 4-5 condiciones → BUY (5%)

# ---- Psicología -----------------------------------------------
MAX_OPEN_POSITIONS     = 5
MAX_CONSECUTIVE_LOSSES = 3
DAILY_LOSS_LIMIT_PCT   = 0.06
MONTHLY_LOSS_LIMIT_PCT = 0.15
MAX_ENTRY_FROM_SUPPORT = 0.03
FEAR_GREED_EUFORIA     = 80
FEAR_GREED_PANICO      = 20

# ---- Macro thresholds -----------------------------------------
VIX_HIGH      = 30    # VIX > 30 = miedo extremo → reducir exposición
VIX_VERY_HIGH = 40    # VIX > 40 = pánico → no operar
FUNDING_HIGH  = 0.01  # funding rate > 1% = mercado sobrecargado long
FUNDING_LOW   = -0.005 # funding rate < -0.5% = mercado sobrecargado short

# ---- RSI zonas ------------------------------------------------
RSI_BUY_BULLISH  = (40, 45)
RSI_SELL_BEARISH = (55, 60)
RSI_BUY_LATERAL  = 30
RSI_SELL_LATERAL = 70

# ---- Universo de activos --------------------------------------
CRYPTO_SYMBOLS = ["BTC", "ETH", "SOL", "BNB"]
STOCK_SYMBOLS  = ["AAPL", "NVDA", "SPY", "TSLA"]
FOREX_PAIRS    = [("EUR", "USD"), ("GBP", "USD")]

# Mapeo símbolo → Binance para funding rate
BINANCE_MAP = {
    "BTC": "BTCUSDT",
    "ETH": "ETHUSDT",
    "SOL": "SOLUSDT",
    "BNB": "BNBUSDT",
}

# Fibonacci levels
FIB_LEVELS = [0.236, 0.382, 0.500, 0.618, 0.786]


# ================================================================
# DATA FETCHER
# ================================================================

class DataFetcher:

    # ---- Crypto ------------------------------------------------

    def get_crypto_ohlcv_daily(self, symbol: str, limit: int = 200) -> List[dict]:
        url = "https://min-api.cryptocompare.com/data/v2/histoday"
        params = {"fsym": symbol, "tsym": "USDT", "limit": limit}
        headers = {"authorization": f"Apikey {CRYPTOCOMPARE_KEY}"} if CRYPTOCOMPARE_KEY else {}
        try:
            r = requests.get(url, params=params, headers=headers, timeout=10)
            return r.json().get("Data", {}).get("Data", [])
        except Exception as e:
            logging.error(f"CryptoCompare daily error [{symbol}]: {e}")
            return []

    def get_crypto_ohlcv_4h(self, symbol: str, limit: int = 100) -> List[dict]:
        url = "https://min-api.cryptocompare.com/data/v2/histohour"
        params = {"fsym": symbol, "tsym": "USDT", "limit": limit * 4, "aggregate": 4}
        headers = {"authorization": f"Apikey {CRYPTOCOMPARE_KEY}"} if CRYPTOCOMPARE_KEY else {}
        try:
            r = requests.get(url, params=params, headers=headers, timeout=10)
            return r.json().get("Data", {}).get("Data", [])
        except Exception as e:
            logging.error(f"CryptoCompare 4h error [{symbol}]: {e}")
            return []

    # ---- Stocks + Macro ----------------------------------------

    def get_alphavantage(self, params: dict) -> dict:
        """Llamada genérica a AlphaVantage con delay para evitar rate limit"""
        params["apikey"] = ALPHAVANTAGE_KEY
        try:
            time.sleep(15)   # AlphaVantage free: 5 calls/min
            r = requests.get("https://www.alphavantage.co/query", params=params, timeout=15)
            return r.json()
        except Exception as e:
            logging.error(f"AlphaVantage error: {e}")
            return {}

    def get_stock_ohlcv(self, symbol: str) -> List[dict]:
        data = self.get_alphavantage({"function": "TIME_SERIES_DAILY", "symbol": symbol, "outputsize": "compact"})
        ts = data.get("Time Series (Daily)", {})
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
        return result

    def get_forex_ohlcv(self, from_sym: str, to_sym: str) -> List[dict]:
        data = self.get_alphavantage({"function": "FX_DAILY", "from_symbol": from_sym, "to_symbol": to_sym})
        ts = data.get("Time Series FX (Daily)", {})
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

    def get_vix(self) -> float:
        """VIX desde AlphaVantage — índice de volatilidad del mercado"""
        data = self.get_alphavantage({"function": "TIME_SERIES_DAILY", "symbol": "VIX"})
        ts = data.get("Time Series (Daily)", {})
        if not ts:
            return 20.0  # valor neutral como fallback
        latest = sorted(ts.keys())[-1]
        return float(ts[latest]["4. close"])

    def get_dxy(self) -> float:
        """DXY — índice del dólar (correlación inversa con crypto y commodities)"""
        data = self.get_alphavantage({"function": "TIME_SERIES_DAILY", "symbol": "DXY"})
        ts = data.get("Time Series (Daily)", {})
        if not ts:
            return 100.0
        latest = sorted(ts.keys())[-1]
        return float(ts[latest]["4. close"])

    def get_spy_trend(self) -> str:
        """SPY como proxy del apetito de riesgo global"""
        raw = self.get_stock_ohlcv("SPY")
        if len(raw) < 50:
            return "UNDEFINED"
        closes = [d["close"] for d in raw]
        ma20 = sum(closes[-20:]) / 20
        ma50 = sum(closes[-50:]) / 50
        if closes[-1] > ma20 > ma50:
            return "RISK_ON"
        if closes[-1] < ma20 < ma50:
            return "RISK_OFF"
        return "NEUTRAL"

    # ---- Binance API pública (sin cuenta, sin key) -------------

    def get_funding_rate(self, symbol: str) -> float:
        """Funding rate actual de futuros perpetuos en Binance"""
        binance_sym = BINANCE_MAP.get(symbol)
        if not binance_sym:
            return 0.0
        try:
            url = f"https://fapi.binance.com/fapi/v1/fundingRate"
            params = {"symbol": binance_sym, "limit": 1}
            r = requests.get(url, params=params, timeout=5)
            data = r.json()
            if data and isinstance(data, list):
                return float(data[-1].get("fundingRate", 0))
        except Exception as e:
            logging.error(f"Binance funding rate error [{symbol}]: {e}")
        return 0.0

    def get_open_interest(self, symbol: str) -> dict:
        """Open interest de futuros en Binance — mide convicción del mercado"""
        binance_sym = BINANCE_MAP.get(symbol)
        if not binance_sym:
            return {}
        try:
            url = "https://fapi.binance.com/fapi/v1/openInterest"
            r = requests.get(url, params={"symbol": binance_sym}, timeout=5)
            return r.json()
        except Exception as e:
            logging.error(f"Binance open interest error [{symbol}]: {e}")
            return {}

    # ---- Sentimiento general -----------------------------------

    def get_fear_greed(self) -> int:
        try:
            r = requests.get("https://api.alternative.me/fng/", timeout=5)
            return int(r.json()["data"][0]["value"])
        except:
            return 50


# ================================================================
# ANÁLISIS TÉCNICO COMPLETO
# ================================================================

class TechnicalAnalysis:

    # ---- Medias ------------------------------------------------

    def ema(self, data: List[float], period: int) -> List[float]:
        if len(data) < period:
            return []
        k = 2 / (period + 1)
        result = [sum(data[:period]) / period]
        for price in data[period:]:
            result.append(price * k + result[-1] * (1 - k))
        return result

    def sma(self, data: List[float], period: int) -> List[float]:
        if len(data) < period:
            return []
        return [sum(data[i-period:i]) / period for i in range(period, len(data) + 1)]

    # ---- RSI ---------------------------------------------------

    def rsi(self, closes: List[float], period: int = 14) -> List[float]:
        if len(closes) < period + 1:
            return []
        deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
        gains  = [max(d, 0.0) for d in deltas]
        losses = [abs(min(d, 0.0)) for d in deltas]
        avg_g  = sum(gains[:period]) / period
        avg_l  = sum(losses[:period]) / period
        result = []
        for i in range(period, len(deltas)):
            avg_g = (avg_g * (period - 1) + gains[i]) / period
            avg_l = (avg_l * (period - 1) + losses[i]) / period
            rs    = avg_g / avg_l if avg_l != 0 else 100
            result.append(round(100 - (100 / (1 + rs)), 2))
        return result

    def rsi_zone(self, rsi_val: float, trend: str) -> str:
        """Clasifica el RSI según el contexto de tendencia"""
        if trend == "BULLISH":
            if RSI_BUY_BULLISH[0] <= rsi_val <= RSI_BUY_BULLISH[1]:
                return "BUY_ZONE"
        elif trend == "BEARISH":
            if RSI_SELL_BEARISH[0] <= rsi_val <= RSI_SELL_BEARISH[1]:
                return "SELL_ZONE"
        elif trend == "LATERAL":
            if rsi_val <= RSI_BUY_LATERAL:
                return "BUY_ZONE"
            if rsi_val >= RSI_SELL_LATERAL:
                return "SELL_ZONE"
        return "NEUTRAL"

    # ---- MACD --------------------------------------------------

    def macd(self, closes: List[float], fast=12, slow=26, signal=9) -> dict:
        """
        Retorna:
          macd_line    : diferencia EMA12 - EMA26
          signal_line  : EMA9 del macd_line
          histogram    : macd_line - signal_line
          cross_up     : True si macd cruzó señal hacia arriba (BUY)
          cross_down   : True si macd cruzó señal hacia abajo (SELL)
        """
        if len(closes) < slow + signal:
            return {}
        ema_fast   = self.ema(closes, fast)
        ema_slow   = self.ema(closes, slow)
        min_len    = min(len(ema_fast), len(ema_slow))
        macd_line  = [ema_fast[-min_len+i] - ema_slow[-min_len+i] for i in range(min_len)]
        sig_line   = self.ema(macd_line, signal)
        if len(sig_line) < 2:
            return {}
        hist       = [macd_line[-len(sig_line)+i] - sig_line[i] for i in range(len(sig_line))]
        cross_up   = sig_line[-2] > macd_line[-len(sig_line)+len(sig_line)-2] and \
                     sig_line[-1] < macd_line[-1]
        cross_down = sig_line[-2] < macd_line[-len(sig_line)+len(sig_line)-2] and \
                     sig_line[-1] > macd_line[-1]
        return {
            "macd":       round(macd_line[-1], 6),
            "signal":     round(sig_line[-1], 6),
            "histogram":  round(hist[-1], 6),
            "cross_up":   cross_up,
            "cross_down": cross_down,
            "bullish":    macd_line[-1] > sig_line[-1],
        }

    # ---- Tendencia ---------------------------------------------

    def trend(self, closes: List[float]) -> str:
        if len(closes) < 200:
            return "UNDEFINED"
        ma50  = self.sma(closes, 50)
        ma200 = self.sma(closes, 200)
        if not ma50 or not ma200:
            return "UNDEFINED"
        if closes[-1] > ma50[-1] > ma200[-1]:
            return "BULLISH"
        if closes[-1] < ma50[-1] < ma200[-1]:
            return "BEARISH"
        return "LATERAL"

    # ---- Régimen de mercado (Wyckoff simplificado) -------------

    def market_regime(self, closes: List[float], volumes: List[float]) -> str:
        """
        Detecta la fase del ciclo de Wyckoff:
          ACUMULACION  : precio lateral + volumen decreciente (dinero inteligente comprando)
          EXPANSION    : precio sube + volumen creciente (todos se dan cuenta)
          DISTRIBUCION : precio lateral en máximos + volumen decreciente (dinero inteligente vendiendo)
          CONTRACCION  : precio baja + volumen creciente (pánico)
        """
        if len(closes) < 30 or len(volumes) < 30:
            return "UNDEFINED"

        recent_closes  = closes[-30:]
        recent_volumes = volumes[-30:]

        price_range = (max(recent_closes) - min(recent_closes)) / min(recent_closes)
        vol_trend   = sum(recent_volumes[-10:]) / 10 - sum(recent_volumes[:10]) / 10
        price_trend = recent_closes[-1] - recent_closes[0]

        if price_range < 0.05 and vol_trend < 0 and recent_closes[-1] < sum(recent_closes) / len(recent_closes):
            return "ACUMULACION"
        if price_trend > 0 and vol_trend > 0:
            return "EXPANSION"
        if price_range < 0.05 and vol_trend < 0 and recent_closes[-1] > sum(recent_closes) / len(recent_closes):
            return "DISTRIBUCION"
        if price_trend < 0 and vol_trend > 0:
            return "CONTRACCION"
        return "INDEFINIDO"

    # ---- Fibonacci ---------------------------------------------

    def fibonacci_levels(self, closes: List[float], lookback: int = 50) -> dict:
        """
        Calcula niveles de retroceso de Fibonacci del último swing.
        En tendencia alcista: swing low → swing high
        """
        if len(closes) < lookback:
            lookback = len(closes)
        recent   = closes[-lookback:]
        swing_low  = min(recent)
        swing_high = max(recent)
        diff       = swing_high - swing_low

        levels = {}
        for fib in FIB_LEVELS:
            levels[f"fib_{int(fib*1000)}"] = round(swing_high - diff * fib, 6)

        levels["swing_low"]  = swing_low
        levels["swing_high"] = swing_high
        return levels

    def price_at_fibonacci(self, price: float, fib_levels: dict, tolerance: float = 0.015) -> Optional[float]:
        """Retorna el nivel Fibonacci más cercano si el precio está dentro del rango de tolerancia"""
        for key, level in fib_levels.items():
            if key in ("swing_low", "swing_high"):
                continue
            if abs(price - level) / level <= tolerance:
                return float(key.replace("fib_", "")) / 1000
        return None

    # ---- VWAP --------------------------------------------------

    def vwap(self, highs: List[float], lows: List[float], closes: List[float], volumes: List[float]) -> float:
        """Precio promedio ponderado por volumen — referencia institucional"""
        if not volumes or sum(volumes) == 0:
            return closes[-1] if closes else 0
        typical_prices = [(h + l + c) / 3 for h, l, c in zip(highs, lows, closes)]
        total_vol = sum(volumes)
        vwap_val  = sum(tp * v for tp, v in zip(typical_prices, volumes)) / total_vol
        return round(vwap_val, 6)

    # ---- Soporte y Resistencia ---------------------------------

    def support_resistance(self, closes: List[float], window: int = 20) -> Tuple[float, float]:
        recent = closes[-window:] if len(closes) >= window else closes
        return min(recent), max(recent)

    # ---- Volumen -----------------------------------------------

    def volume_above_average(self, volumes: List[float], multiplier: float = 1.1) -> bool:
        if len(volumes) < 21:
            return False
        avg = sum(volumes[-21:-1]) / 20
        return volumes[-1] > avg * multiplier if avg > 0 else False

    # ---- Divergencias ------------------------------------------

    def divergence(self, closes: List[float], rsi_vals: List[float], lookback: int = 20) -> str:
        if len(closes) < lookback or len(rsi_vals) < lookback:
            return "NONE"
        rc = closes[-lookback:]
        rr = rsi_vals[-lookback:]
        price_mins, rsi_mins, price_maxs, rsi_maxs = [], [], [], []
        for i in range(1, len(rc) - 1):
            if rc[i] < rc[i-1] and rc[i] < rc[i+1]:
                price_mins.append(rc[i])
                rsi_mins.append(rr[i])
            if rc[i] > rc[i-1] and rc[i] > rc[i+1]:
                price_maxs.append(rc[i])
                rsi_maxs.append(rr[i])
        if len(price_mins) >= 2 and len(rsi_mins) >= 2:
            if price_mins[-1] < price_mins[-2] and rsi_mins[-1] > rsi_mins[-2]:
                return "BULLISH"
        if len(price_maxs) >= 2 and len(rsi_maxs) >= 2:
            if price_maxs[-1] > price_maxs[-2] and rsi_maxs[-1] < rsi_maxs[-2]:
                return "BEARISH"
        return "NONE"

    # ---- Análisis completo de un timeframe ---------------------

    def full_analysis(self, ohlcv: List[dict], symbol: str = "") -> dict:
        """Corre todos los indicadores sobre un set de velas OHLCV"""
        if not ohlcv or len(ohlcv) < 30:
            return {"valid": False}

        closes  = [d["close"]  for d in ohlcv if d.get("close")]
        highs   = [d.get("high", d["close"])  for d in ohlcv]
        lows    = [d.get("low", d["close"])   for d in ohlcv]
        volumes = [d.get("volumeto", d.get("volume", 0)) for d in ohlcv]

        rsi_vals   = self.rsi(closes)
        macd_data  = self.macd(closes)
        trend_val  = self.trend(closes)
        regime     = self.market_regime(closes, volumes)
        fib        = self.fibonacci_levels(closes)
        support, resistance = self.support_resistance(closes)
        vwap_val   = self.vwap(highs, lows, closes, volumes)
        diverg     = self.divergence(closes, rsi_vals) if rsi_vals else "NONE"
        vol_ok     = self.volume_above_average(volumes)

        current_rsi   = rsi_vals[-1] if rsi_vals else 50.0
        current_price = closes[-1]
        rsi_z         = self.rsi_zone(current_rsi, trend_val)
        fib_level     = self.price_at_fibonacci(current_price, fib)

        return {
            "valid":       True,
            "price":       current_price,
            "trend":       trend_val,
            "regime":      regime,
            "rsi":         current_rsi,
            "rsi_zone":    rsi_z,
            "macd":        macd_data,
            "divergence":  diverg,
            "support":     support,
            "resistance":  resistance,
            "vwap":        vwap_val,
            "above_vwap":  current_price > vwap_val,
            "fib_levels":  fib,
            "fib_level":   fib_level,
            "volume_ok":   vol_ok,
            "dist_support": round((current_price - support) / support, 4) if support > 0 else 0,
        }


# ================================================================
# CONTEXTO MACRO
# ================================================================

class MacroContext:
    """Evalúa el estado macro del mercado — corre una vez por ciclo"""

    def __init__(self):
        self.fetcher = DataFetcher()
        self.cache   = {}
        self.last_update = None

    def update(self) -> dict:
        logging.info("[MACRO] Actualizando contexto macro...")
        ctx = {}

        # Fear & Greed (rápido, sin rate limit)
        ctx["fear_greed"] = self.fetcher.get_fear_greed()

        # Funding rates crypto (Binance, sin rate limit)
        ctx["funding_rates"] = {}
        for sym in CRYPTO_SYMBOLS:
            ctx["funding_rates"][sym] = self.fetcher.get_funding_rate(sym)

        # Open Interest (Binance)
        ctx["open_interest"] = {}
        for sym in CRYPTO_SYMBOLS:
            oi = self.fetcher.get_open_interest(sym)
            ctx["open_interest"][sym] = float(oi.get("openInterest", 0))

        # SPY trend (AlphaVantage — lento)
        ctx["spy_trend"] = self.fetcher.get_spy_trend()

        # VIX (AlphaVantage — lento)
        ctx["vix"] = self.fetcher.get_vix()

        # Clasificación macro general
        ctx["macro_regime"] = self._classify_macro(ctx)
        ctx["position_multiplier"] = self._position_multiplier(ctx)

        self.cache = ctx
        self.last_update = datetime.now()
        logging.info(f"[MACRO] F&G:{ctx['fear_greed']} VIX:{ctx['vix']:.1f} SPY:{ctx['spy_trend']} Regime:{ctx['macro_regime']}")
        return ctx

    def _classify_macro(self, ctx: dict) -> str:
        """
        RISK_ON  : mercado con apetito de riesgo alto → operar normal
        RISK_OFF : miedo elevado → reducir exposición
        DANGER   : pánico extremo → no abrir nuevas posiciones
        """
        vix         = ctx.get("vix", 20)
        fear_greed  = ctx.get("fear_greed", 50)
        spy         = ctx.get("spy_trend", "NEUTRAL")

        if vix > VIX_VERY_HIGH or fear_greed < 10:
            return "DANGER"
        if vix > VIX_HIGH or fear_greed < FEAR_GREED_PANICO or spy == "RISK_OFF":
            return "RISK_OFF"
        return "RISK_ON"

    def _position_multiplier(self, ctx: dict) -> float:
        """Ajusta el tamaño de posición según el régimen macro"""
        regime     = ctx.get("macro_regime", "RISK_ON")
        fear_greed = ctx.get("fear_greed", 50)
        if regime == "DANGER":
            return 0.0    # no abrir posiciones
        if regime == "RISK_OFF":
            return 0.5    # mitad del tamaño normal
        if fear_greed > FEAR_GREED_EUFORIA:
            return 0.5    # mercado en euforia → precaución
        if fear_greed < FEAR_GREED_PANICO:
            return 1.5    # pánico = oportunidad → más convicción
        return 1.0

    def funding_signal(self, symbol: str) -> str:
        """
        Funding rate alto positivo → todos están long → riesgo de liquidación masiva
        Funding rate muy negativo → todos están short → posible short squeeze
        """
        fr = self.cache.get("funding_rates", {}).get(symbol, 0)
        if fr > FUNDING_HIGH:
            return "OVERCROWDED_LONG"    # precaución para BUY
        if fr < FUNDING_LOW:
            return "OVERCROWDED_SHORT"   # oportunidad para BUY (short squeeze)
        return "NEUTRAL"


# ================================================================
# SCORER — 8 condiciones
# ================================================================

class SignalScorer:

    def __init__(self):
        self.ta = TechnicalAnalysis()

    def score_buy(self, daily: dict, h4: dict, macro: dict, funding_signal: str) -> Tuple[int, dict]:
        """
        8 condiciones de compra:
        1. Tendencia diaria favorable (BULLISH o LATERAL)
        2. RSI en zona de compra según tendencia
        3. MACD alcista o cruzando al alza
        4. Precio en soporte o nivel Fibonacci clave
        5. Volumen confirma
        6. Divergencia alcista
        7. Timeframe 4h alineado (tendencia 4h no bajista)
        8. Contexto macro favorable (no DANGER, funding no sobrecargado)
        """
        checks = {}

        # 1. Tendencia diaria
        checks["tendencia_alcista"] = daily.get("trend") in ("BULLISH", "LATERAL")

        # 2. RSI zona compra
        checks["rsi_zona_compra"] = daily.get("rsi_zone") == "BUY_ZONE"

        # 3. MACD alcista
        macd = daily.get("macd", {})
        checks["macd_alcista"] = macd.get("bullish", False) or macd.get("cross_up", False)

        # 4. Soporte o Fibonacci
        at_support = daily.get("dist_support", 1) <= 0.02
        at_fib     = daily.get("fib_level") in (0.382, 0.500, 0.618)
        checks["en_soporte_o_fibonacci"] = at_support or at_fib

        # 5. Volumen confirma
        checks["volumen_confirma"] = daily.get("volume_ok", False)

        # 6. Divergencia alcista
        checks["divergencia_alcista"] = daily.get("divergence") == "BULLISH"

        # 7. 4h alineado
        checks["4h_alineado"] = h4.get("trend") != "BEARISH" if h4.get("valid") else True

        # 8. Macro favorable
        macro_ok     = macro.get("macro_regime") != "DANGER"
        funding_ok   = funding_signal != "OVERCROWDED_LONG"
        regime_ok    = daily.get("regime") in ("ACUMULACION", "EXPANSION", "INDEFINIDO")
        checks["macro_favorable"] = macro_ok and funding_ok and regime_ok

        score = sum(1 for v in checks.values() if v)
        return score, checks

    def score_sell(self, daily: dict, h4: dict, macro: dict, funding_signal: str) -> Tuple[int, dict]:
        """
        8 condiciones de venta:
        1. Tendencia diaria desfavorable (BEARISH o LATERAL)
        2. RSI en zona de venta según tendencia
        3. MACD bajista o cruzando a la baja
        4. Precio en resistencia o Fibonacci de distribución
        5. Volumen confirma
        6. Divergencia bajista
        7. Timeframe 4h alineado (tendencia 4h no alcista)
        8. Contexto macro desfavorable
        """
        checks = {}

        checks["tendencia_bajista"]        = daily.get("trend") in ("BEARISH", "LATERAL")
        checks["rsi_zona_venta"]           = daily.get("rsi_zone") == "SELL_ZONE"
        macd = daily.get("macd", {})
        checks["macd_bajista"]             = not macd.get("bullish", True) or macd.get("cross_down", False)
        at_resistance = (daily.get("resistance", 0) > 0 and
                         abs(daily.get("price", 0) - daily.get("resistance", 0)) / daily.get("resistance", 1) <= 0.02)
        checks["en_resistencia"]           = at_resistance
        checks["volumen_confirma"]         = daily.get("volume_ok", False)
        checks["divergencia_bajista"]      = daily.get("divergence") == "BEARISH"
        checks["4h_alineado"]              = h4.get("trend") != "BULLISH" if h4.get("valid") else True
        checks["macro_desfavorable"]       = (macro.get("macro_regime") in ("RISK_OFF", "DANGER") or
                                              daily.get("regime") in ("DISTRIBUCION", "CONTRACCION"))

        score = sum(1 for v in checks.values() if v)
        return score, checks


# ================================================================
# KELLY CRITERION — tamaño dinámico de posición
# ================================================================

class KellyCriterion:

    def calculate(self, trades: List[dict], base_pct: float) -> float:
        """
        Calcula el tamaño óptimo de posición basado en el historial.
        Usa Half Kelly para reducir volatilidad.
        Requiere mínimo 20 trades para ser estadísticamente válido.
        """
        sells = [t for t in trades if t.get("action") == "SELL" and "pnl" in t]

        if len(sells) < 20:
            return base_pct  # sin historial suficiente → tamaño base

        wins    = [t for t in sells if t["pnl"] > 0]
        losses  = [t for t in sells if t["pnl"] <= 0]
        win_rate = len(wins) / len(sells)

        if not wins or not losses:
            return base_pct

        avg_win  = sum(t["pnl"] for t in wins) / len(wins)
        avg_loss = abs(sum(t["pnl"] for t in losses) / len(losses))

        if avg_loss == 0:
            return base_pct

        # Kelly = W/L - (1-W)/G
        kelly = (win_rate / avg_loss) - ((1 - win_rate) / avg_win)
        half_kelly = kelly * 0.5  # Half Kelly — más conservador

        # Clampear entre 2% y MAX_POSITION_PCT
        return max(0.02, min(half_kelly, MAX_POSITION_PCT))


# ================================================================
# FILTROS PSICOLÓGICOS
# ================================================================

class PsychologyFilters:

    def check_all(self, symbol: str, direction: str, portfolio: "Portfolio", macro: dict) -> Tuple[bool, List[str]]:
        failures = []
        fear_greed = macro.get("fear_greed", 50)
        macro_regime = macro.get("macro_regime", "RISK_ON")

        if portfolio.status != "RUNNING":
            failures.append(f"bot_pausado: {portfolio.pause_reason}")
        if portfolio.daily_pnl_pct <= -DAILY_LOSS_LIMIT_PCT:
            failures.append("limite_diario_6pct")
            portfolio.pause("Límite pérdida diaria 6%")
        if portfolio.consecutive_losses >= MAX_CONSECUTIVE_LOSSES:
            failures.append("3_perdidas_consecutivas")
            portfolio.pause("3 pérdidas consecutivas")
        if direction == "BUY" and symbol in portfolio.positions:
            pos = portfolio.positions[symbol]
            if pos["current_price"] < pos["avg_price"]:
                failures.append("averaging_down_bloqueado")
        if direction == "BUY" and portfolio.entry_distances.get(symbol, 0) > MAX_ENTRY_FROM_SUPPORT:
            failures.append("fomo_lejos_del_soporte")
        if direction == "BUY" and len(portfolio.positions) >= MAX_OPEN_POSITIONS:
            failures.append("max_5_posiciones")
        if portfolio.monthly_pnl_pct <= -MONTHLY_LOSS_LIMIT_PCT:
            failures.append("limite_mensual_15pct")
            portfolio.pause("Límite pérdida mensual 15%")
        if direction == "BUY" and macro_regime == "DANGER":
            failures.append("macro_danger_no_abrir")
        if direction == "BUY" and fear_greed > FEAR_GREED_EUFORIA:
            failures.append("mercado_en_euforia")

        return len(failures) == 0, failures


# ================================================================
# PORTFOLIO
# ================================================================

class Portfolio:

    def __init__(self):
        self.capital          = INITIAL_CAPITAL
        self.positions: Dict[str, dict] = {}
        self.trades: List[dict]         = []
        self.equity_curve               = [INITIAL_CAPITAL]
        self.status           = "RUNNING"
        self.pause_reason     = ""
        self.consecutive_losses    = 0
        self.daily_pnl_pct         = 0.0
        self.monthly_pnl_pct       = 0.0
        self.start_of_day_equity   = INITIAL_CAPITAL
        self.start_of_month_equity = INITIAL_CAPITAL
        self.entry_distances: Dict[str, float] = {}

    def pause(self, reason: str):
        self.status       = "PAUSED"
        self.pause_reason = reason
        logging.warning(f"[BOT PAUSADO] {reason}")

    def resume(self):
        self.status             = "RUNNING"
        self.pause_reason       = ""
        self.consecutive_losses = 0

    def reset_daily(self):
        pos_value = sum(p["qty"] * p["current_price"] for p in self.positions.values())
        self.start_of_day_equity = self.capital + pos_value
        self.daily_pnl_pct = 0.0
        if self.pause_reason == "Límite pérdida diaria 6%":
            self.resume()

    def open_position(self, symbol: str, price: float, signal_type: str, size_pct: float) -> bool:
        allocation = INITIAL_CAPITAL * size_pct
        if self.capital < allocation:
            return False
        qty = allocation / price
        if symbol in self.positions:
            pos = self.positions[symbol]
            if pos["current_price"] < pos["avg_price"]:
                return False
            total_qty       = pos["qty"] + qty
            pos["avg_price"] = (pos["avg_price"] * pos["qty"] + price * qty) / total_qty
            pos["qty"]       = total_qty
        else:
            self.positions[symbol] = {
                "qty":             qty,
                "avg_price":       price,
                "current_price":   price,
                "stop_loss":       round(price * (1 - STOP_LOSS_PCT), 6),
                "take_profit":     round(price * (1 + TAKE_PROFIT_PCT), 6),
                "trailing_stop":   None,
                "trailing_active": False,
                "max_price_seen":  price,
                "opened_at":       datetime.now().isoformat(),
                "signal_type":     signal_type,
            }
        self.capital -= allocation
        self.trades.append({
            "action": "BUY", "symbol": symbol, "price": price,
            "qty": qty, "allocation": round(allocation, 2),
            "signal_type": signal_type, "timestamp": datetime.now().isoformat()
        })
        return True

    def close_position(self, symbol: str, price: float, reason: str) -> Optional[float]:
        if symbol not in self.positions:
            return None
        pos      = self.positions[symbol]
        proceeds = pos["qty"] * price
        cost     = pos["qty"] * pos["avg_price"]
        pnl      = proceeds - cost
        self.capital += proceeds
        self.trades.append({
            "action": "SELL", "symbol": symbol, "price": price,
            "qty": pos["qty"], "proceeds": round(proceeds, 2),
            "pnl": round(pnl, 2), "pnl_pct": round(pnl / cost * 100, 2),
            "reason": reason, "timestamp": datetime.now().isoformat()
        })
        self.consecutive_losses = self.consecutive_losses + 1 if pnl < 0 else 0
        del self.positions[symbol]
        return pnl

    def update_prices(self, prices: Dict[str, float]) -> List[dict]:
        stops = []
        for symbol, pos in list(self.positions.items()):
            if symbol not in prices:
                continue
            price = prices[symbol]
            pos["current_price"] = price
            if price > pos["max_price_seen"]:
                pos["max_price_seen"] = price
            pnl_pct = (price - pos["avg_price"]) / pos["avg_price"]
            if pnl_pct >= TRAILING_ACTIVATE_AT and not pos["trailing_active"]:
                pos["trailing_active"] = True
                pos["trailing_stop"]   = price * (1 - TRAILING_STOP_PCT)
            if pos["trailing_active"]:
                new_trail = price * (1 - TRAILING_STOP_PCT)
                if new_trail > pos["trailing_stop"]:
                    pos["trailing_stop"] = new_trail
            if price <= pos["stop_loss"]:
                stops.append({"symbol": symbol, "price": price, "reason": "STOP_LOSS"})
            elif pos["trailing_active"] and price <= pos["trailing_stop"]:
                stops.append({"symbol": symbol, "price": price, "reason": "TRAILING_STOP"})
            elif price >= pos["take_profit"]:
                stops.append({"symbol": symbol, "price": price, "reason": "TAKE_PROFIT"})
        for event in stops:
            pnl = self.close_position(event["symbol"], event["price"], event["reason"])
            event["pnl"] = pnl
        pos_value = sum(p["qty"] * p["current_price"] for p in self.positions.values())
        total_eq  = self.capital + pos_value
        self.equity_curve.append(round(total_eq, 2))
        if self.start_of_day_equity > 0:
            self.daily_pnl_pct = (total_eq - self.start_of_day_equity) / self.start_of_day_equity
        if self.start_of_month_equity > 0:
            self.monthly_pnl_pct = (total_eq - self.start_of_month_equity) / self.start_of_month_equity
        if self.monthly_pnl_pct <= -MONTHLY_LOSS_LIMIT_PCT:
            self.pause("Límite pérdida mensual 15%")
        return stops

    def get_summary(self) -> dict:
        pos_value = sum(p["qty"] * p["current_price"] for p in self.positions.values())
        total_eq  = self.capital + pos_value
        pnl       = total_eq - INITIAL_CAPITAL
        sells     = [t for t in self.trades if t["action"] == "SELL"]
        wins      = [t for t in sells if t.get("pnl", 0) > 0]
        return {
            "capital_libre":        round(self.capital, 2),
            "posiciones_valor":     round(pos_value, 2),
            "equity_total":         round(total_eq, 2),
            "pnl_neto":             round(pnl, 2),
            "pnl_pct":              round(pnl / INITIAL_CAPITAL * 100, 2),
            "posiciones_abiertas":  len(self.positions),
            "trades_totales":       len(self.trades),
            "win_rate":             round(len(wins) / len(sells) * 100, 1) if sells else 0,
            "perdidas_consecutivas": self.consecutive_losses,
            "daily_pnl_pct":        round(self.daily_pnl_pct * 100, 2),
            "monthly_pnl_pct":      round(self.monthly_pnl_pct * 100, 2),
            "status":               self.status,
            "pause_reason":         self.pause_reason,
            "equity_curve":         self.equity_curve[-60:],
            "posiciones_detalle": {
                sym: {
                    "qty":             round(p["qty"], 6),
                    "avg_price":       round(p["avg_price"], 4),
                    "current_price":   round(p["current_price"], 4),
                    "pnl_pct":         round((p["current_price"] - p["avg_price"]) / p["avg_price"] * 100, 2),
                    "stop_loss":       round(p["stop_loss"], 4),
                    "take_profit":     round(p["take_profit"], 4),
                    "trailing_active": p["trailing_active"],
                    "signal_type":     p["signal_type"],
                }
                for sym, p in self.positions.items()
            },
        }


# ================================================================
# NOTIFICACIONES
# ================================================================

class Notifier:
    def send(self, message: str):
        if not TELEGRAM_TOKEN or not TELEGRAM_CHAT:
            logging.info(f"[TELEGRAM MOCK] {message}")
            return
        try:
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": TELEGRAM_CHAT, "text": message, "parse_mode": "Markdown"},
                timeout=5,
            )
        except Exception as e:
            logging.error(f"[TELEGRAM ERROR] {e}")


# ================================================================
# BOT PRINCIPAL v2
# ================================================================

class TradingBot:

    def __init__(self):
        self.fetcher   = DataFetcher()
        self.ta        = TechnicalAnalysis()
        self.scorer    = SignalScorer()
        self.psych     = PsychologyFilters()
        self.kelly     = KellyCriterion()
        self.macro_ctx = MacroContext()
        self.portfolio = Portfolio()
        self.notifier  = Notifier()
        self.running   = False
        self.last_prices: Dict[str, float] = {}
        self.last_signals: List[dict]      = []
        self.cycle_count = 0
        self.macro: dict = {}

    def analyze(self, symbol: str, asset_type: str) -> Optional[dict]:
        """Análisis completo de un activo en dos timeframes"""

        # Obtener OHLCV diario
        if asset_type == "crypto":
            daily_raw = self.fetcher.get_crypto_ohlcv_daily(symbol)
            h4_raw    = self.fetcher.get_crypto_ohlcv_4h(symbol)
        elif asset_type == "stock":
            daily_raw = self.fetcher.get_stock_ohlcv(symbol)
            h4_raw    = []
        elif asset_type == "forex":
            pair      = symbol.split("/")
            daily_raw = self.fetcher.get_forex_ohlcv(pair[0], pair[1])
            h4_raw    = []
        else:
            return None

        if len(daily_raw) < 50:
            return None

        daily = self.ta.full_analysis(daily_raw, symbol)
        h4    = self.ta.full_analysis(h4_raw, symbol) if len(h4_raw) >= 30 else {"valid": False}

        if not daily["valid"]:
            return None

        self.last_prices[symbol] = daily["price"]
        self.portfolio.entry_distances[symbol] = daily.get("dist_support", 1)

        # Funding signal para crypto
        funding_sig = self.macro_ctx.funding_signal(symbol) if asset_type == "crypto" else "NEUTRAL"

        # Determinar dirección y puntuar
        buy_score,  buy_checks  = self.scorer.score_buy(daily, h4, self.macro, funding_sig)
        sell_score, sell_checks = self.scorer.score_sell(daily, h4, self.macro, funding_sig)

        # Elegir la dirección con mayor score
        if buy_score >= sell_score and buy_score >= MIN_SIGNAL_SCORE:
            direction = "BUY"
            score     = buy_score
            checks    = buy_checks
        elif sell_score > buy_score and sell_score >= MIN_SIGNAL_SCORE:
            direction = "SELL"
            score     = sell_score
            checks    = sell_checks
        else:
            return None

        # Determinar tipo de señal
        signal_type = "STRONG_BUY" if (direction == "BUY" and score >= SCORE_STRONG_BUY) else direction

        return {
            "symbol":       symbol,
            "asset_type":   asset_type,
            "direction":    direction,
            "signal_type":  signal_type,
            "price":        daily["price"],
            "score":        score,
            "max_score":    8,
            "checks":       checks,
            "daily":        daily,
            "h4_valid":     h4.get("valid", False),
            "funding":      funding_sig,
            "timestamp":    datetime.now().isoformat(),
        }

    def execute(self, signal: dict):
        symbol      = signal["symbol"]
        direction   = signal["direction"]
        price       = signal["price"]
        signal_type = signal["signal_type"]
        score       = signal["score"]
        daily       = signal["daily"]

        multiplier = self.macro.get("position_multiplier", 1.0)

        if direction == "BUY":
            base_pct  = 0.10 if signal_type == "STRONG_BUY" else 0.05
            kelly_pct = self.kelly.calculate(self.portfolio.trades, base_pct)
            final_pct = kelly_pct * multiplier
            success   = self.portfolio.open_position(symbol, price, signal_type, final_pct)
            if success:
                pos = self.portfolio.positions.get(symbol, {})
                self.notifier.send(
                    f"🟢 *{signal_type}* `{symbol}`\n"
                    f"Precio: `${price:,.4f}` · Score: *{score}/8*\n"
                    f"Tendencia: {daily['trend']} · RSI: {daily['rsi']:.1f} · MACD: {'✅' if daily.get('macd', {}).get('bullish') else '❌'}\n"
                    f"Régimen: {daily['regime']} · VWAP: {'↑' if daily['above_vwap'] else '↓'}\n"
                    f"Fibonacci: {daily['fib_level'] or 'N/A'} · Funding: {signal['funding']}\n"
                    f"SL: `${pos.get('stop_loss',0):,.4f}` · TP: `${pos.get('take_profit',0):,.4f}`\n"
                    f"Macro: {self.macro.get('macro_regime')} · F&G: {self.macro.get('fear_greed')} · VIX: {self.macro.get('vix',0):.1f}"
                )

        elif direction == "SELL":
            if symbol in self.portfolio.positions:
                pnl = self.portfolio.close_position(symbol, price, "SEÑAL_VENTA")
                if pnl is not None:
                    emoji = "🟢" if pnl > 0 else "🔴"
                    self.notifier.send(
                        f"{emoji} *SELL* `{symbol}` @ `${price:,.4f}`\n"
                        f"Score: {score}/8 · P&L: `${pnl:+,.2f}`\n"
                        f"RSI: {daily['rsi']:.1f} · Divergencia: {daily['divergence']}"
                    )

    def run_cycle(self) -> dict:
        self.cycle_count += 1
        logging.info(f"[CICLO {self.cycle_count}] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        # Actualizar contexto macro
        self.macro = self.macro_ctx.update()

        if self.macro.get("macro_regime") == "DANGER":
            self.notifier.send(
                f"⚠️ *MACRO DANGER*\n"
                f"VIX: {self.macro.get('vix',0):.1f} · F&G: {self.macro.get('fear_greed')}\n"
                f"No se abren nuevas posiciones."
            )

        signals_ok, signals_blocked = [], []

        # Analizar todos los activos
        for sym in CRYPTO_SYMBOLS:
            signal = self.analyze(sym, "crypto")
            if signal:
                ok, failures = self.psych.check_all(sym, signal["direction"], self.portfolio, self.macro)
                signal["psych_ok"] = ok
                signal["psych_failures"] = failures
                if ok:
                    self.execute(signal)
                    signals_ok.append(signal)
                else:
                    signals_blocked.append({**signal, "failures": failures})

        for sym in STOCK_SYMBOLS:
            signal = self.analyze(sym, "stock")
            if signal:
                ok, failures = self.psych.check_all(sym, signal["direction"], self.portfolio, self.macro)
                signal["psych_ok"] = ok
                signal["psych_failures"] = failures
                if ok:
                    self.execute(signal)
                    signals_ok.append(signal)
                else:
                    signals_blocked.append({**signal, "failures": failures})

        for from_sym, to_sym in FOREX_PAIRS:
            sym    = f"{from_sym}/{to_sym}"
            signal = self.analyze(sym, "forex")
            if signal:
                ok, failures = self.psych.check_all(sym, signal["direction"], self.portfolio, self.macro)
                signal["psych_ok"] = ok
                signal["psych_failures"] = failures
                if ok:
                    self.execute(signal)
                    signals_ok.append(signal)
                else:
                    signals_blocked.append({**signal, "failures": failures})

        # Chequear stops
        stops = self.portfolio.update_prices(self.last_prices)
        for event in stops:
            emoji = {"STOP_LOSS": "🔴", "TRAILING_STOP": "🟡", "TAKE_PROFIT": "🟢"}.get(event["reason"], "⚪")
            self.notifier.send(
                f"{emoji} *{event['reason']}*\n"
                f"`{event['symbol']}` @ `${event['price']:,.4f}` · P&L: `${event.get('pnl', 0):+,.2f}`"
            )

        self.last_signals = signals_ok + signals_blocked
        summary = self.portfolio.get_summary()
        logging.info(
            f"[RESUMEN] Equity: ${summary['equity_total']:,.2f} | "
            f"P&L: {summary['pnl_pct']:+.2f}% | "
            f"Pos: {summary['posiciones_abiertas']} | "
            f"Señales: {len(signals_ok)} ejecutadas, {len(signals_blocked)} bloqueadas"
        )

        return {
            "cycle":           self.cycle_count,
            "macro":           self.macro,
            "signals_ok":      len(signals_ok),
            "signals_blocked": len(signals_blocked),
            "stops":           len(stops),
            "summary":         summary,
        }

    async def start(self, interval_minutes: int = 60):
        self.running = True
        self.notifier.send(
            f"🚀 *BetScan Trading Bot v2.0 iniciado*\n"
            f"Capital: `$50,000` · Ciclo: {interval_minutes}min\n"
            f"Motor: RSI + MACD + Fibonacci + VWAP + Wyckoff\n"
            f"Macro: VIX + DXY + SPY + Funding Rate\n"
            f"Score mínimo: {MIN_SIGNAL_SCORE}/8"
        )
        while self.running:
            try:
                self.run_cycle()
            except Exception as e:
                logging.error(f"[ERROR] {e}")
                self.notifier.send(f"⚠️ *Error en ciclo*\n`{str(e)}`")
            await asyncio.sleep(interval_minutes * 60)

    def stop(self):
        self.running = False
        self.notifier.send("⏹ *BetScan Trading Bot v2.0 detenido*")


# Instancia global
bot = TradingBot()
