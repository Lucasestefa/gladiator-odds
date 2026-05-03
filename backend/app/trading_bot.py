"""
BetScan Trading Bot — Motor de Inteligencia v3.0
=================================================
NOVEDADES v3:
  ✅ Universo dinámico de 50 activos por ciclo (market_scraper)
  ✅ Scraping automático: USA stocks + LATAM + Crypto + Forex
  ✅ Selección por volumen + momentum + sector fuerte del día
  ✅ Ya no hay lista fija de activos — el bot caza oportunidades en tiempo real

Variables integradas:
  Análisis Técnico:
    ✅ RSI contextual (40-45 alcista / 55-60 bajista / 30-70 lateral)
    ✅ MACD (momentum + cruces de señal)
    ✅ Divergencias alcistas y bajistas
    ✅ Medias móviles MA50 + MA200
    ✅ Niveles de Fibonacci (23.6%, 38.2%, 50%, 61.8%, 78.6%)
    ✅ VWAP (precio justo institucional)
    ✅ Volumen confirmado vs promedio 20 días
    ✅ Múltiples timeframes (Diario + 4 horas)
    ✅ Régimen de mercado Wyckoff

  Contexto Macro:
    ✅ Fear & Greed Index
    ✅ VIX — índice de volatilidad
    ✅ SPY — proxy apetito de riesgo global
    ✅ Funding Rate crypto (Binance API pública)
    ✅ Open Interest (Binance API pública)

  Gestión de Riesgo:
    ✅ Stop loss fijo -3%
    ✅ Take profit +7% (ratio 1:2.3)
    ✅ Trailing stop desde +5%
    ✅ Kelly Criterion dinámico (activo tras 20 trades)

  Psicología (9 filtros):
    ✅ Anti revenge trading (límite diario 6%)
    ✅ Anti racha negativa (pausa 3 pérdidas)
    ✅ Anti averaging down
    ✅ Anti FOMO (distancia del soporte)
    ✅ Anti overtrading (máx 5 posiciones)
    ✅ Anti euforia (Fear & Greed > 80)
    ✅ Límite mensual 15%
    ✅ Macro DANGER (VIX > 40)
    ✅ Funding rate sobrecargado
"""

import os
import time
import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import requests

# ---- Fee engine de Alpaca --------------------------------------
try:
    from app.alpaca_fees import AlpacaFeeEngine
    _FEE_ENGINE_AVAILABLE = True
except ImportError:
    try:
        from alpaca_fees import AlpacaFeeEngine
        _FEE_ENGINE_AVAILABLE = True
    except ImportError:
        _FEE_ENGINE_AVAILABLE = False
        logging.warning("[BOT] alpaca_fees no disponible — fees no se calcularán")

# ---- Importar el scraper de universo dinámico ------------------
try:
    from app.market_scraper import universe_builder
    DYNAMIC_UNIVERSE = True
except ImportError:
    DYNAMIC_UNIVERSE = False
    logging.warning("[BOT] market_scraper no disponible — usando universo fijo")

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
MAX_POSITION_PCT     = 0.20

# ---- Score ----------------------------------------------------
MIN_SIGNAL_SCORE = 4
SCORE_STRONG_BUY = 6

# ---- Psicología -----------------------------------------------
MAX_OPEN_POSITIONS     = 5
MAX_CONSECUTIVE_LOSSES = 3
DAILY_LOSS_LIMIT_PCT   = 0.06
MONTHLY_LOSS_LIMIT_PCT = 0.15
MAX_ENTRY_FROM_SUPPORT = 0.03
FEAR_GREED_EUFORIA     = 80
FEAR_GREED_PANICO      = 20

# ---- Macro ----------------------------------------------------
VIX_HIGH      = 30
VIX_VERY_HIGH = 40
FUNDING_HIGH  = 0.01
FUNDING_LOW   = -0.005

# ---- RSI zonas ------------------------------------------------
RSI_BUY_BULLISH  = (40, 45)
RSI_SELL_BEARISH = (55, 60)
RSI_BUY_LATERAL  = 30
RSI_SELL_LATERAL = 70

# ---- Universo FIJO (fallback si el scraper falla) -------------
CRYPTO_SYMBOLS_DEFAULT = ["BTC", "ETH", "SOL", "BNB", "AVAX", "MATIC", "LINK", "DOT"]
STOCK_SYMBOLS_DEFAULT  = [
    # Momentum fuerte mayo 2026
    "FIX", "TXN", "ONTO", "ENVA",
    # Largo plazo — moat fuerte
    "ABNB", "SHOP", "META",
    # LATAM
    "MELI", "YPF",
    # Core tech
    "NVDA", "MSFT", "AAPL",
    # ETFs índice
    "SPY", "QQQ",
]
FOREX_PAIRS_DEFAULT    = [("EUR", "USD"), ("GBP", "USD"), ("USD", "JPY"), ("USD", "BRL")]

# Mapeo Binance para funding rate
BINANCE_MAP = {
    "BTC": "BTCUSDT", "ETH": "ETHUSDT", "SOL": "SOLUSDT",
    "BNB": "BNBUSDT", "AVAX": "AVAXUSDT", "MATIC": "MATICUSDT",
    "LINK": "LINKUSDT", "DOT": "DOTUSDT", "ADA": "ADAUSDT",
}

FIB_LEVELS = [0.236, 0.382, 0.500, 0.618, 0.786]


# ================================================================
# DATA FETCHER
# ================================================================

class DataFetcher:

    def get_crypto_ohlcv_daily(self, symbol: str, limit: int = 200) -> List[dict]:
        url = "https://min-api.cryptocompare.com/data/v2/histoday"
        params = {"fsym": symbol, "tsym": "USDT", "limit": limit}
        headers = {"authorization": f"Apikey {CRYPTOCOMPARE_KEY}"} if CRYPTOCOMPARE_KEY else {}
        try:
            r = requests.get(url, params=params, headers=headers, timeout=10)
            return r.json().get("Data", {}).get("Data", [])
        except Exception as e:
            logging.error(f"CryptoCompare daily [{symbol}]: {e}")
            return []

    def get_crypto_ohlcv_4h(self, symbol: str, limit: int = 100) -> List[dict]:
        url = "https://min-api.cryptocompare.com/data/v2/histohour"
        params = {"fsym": symbol, "tsym": "USDT", "limit": limit * 4, "aggregate": 4}
        headers = {"authorization": f"Apikey {CRYPTOCOMPARE_KEY}"} if CRYPTOCOMPARE_KEY else {}
        try:
            r = requests.get(url, params=params, headers=headers, timeout=10)
            return r.json().get("Data", {}).get("Data", [])
        except Exception as e:
            logging.error(f"CryptoCompare 4h [{symbol}]: {e}")
            return []

    def get_alphavantage(self, params: dict) -> dict:
        params["apikey"] = ALPHAVANTAGE_KEY
        try:
            time.sleep(15)
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
            try:
                result.append({
                    "time": date, "open": float(v["1. open"]),
                    "high": float(v["2. high"]), "low": float(v["3. low"]),
                    "close": float(v["4. close"]), "volume": float(v["5. volume"]),
                })
            except:
                continue
        return result

    def get_forex_ohlcv(self, from_sym: str, to_sym: str) -> List[dict]:
        data = self.get_alphavantage({"function": "FX_DAILY", "from_symbol": from_sym, "to_symbol": to_sym})
        ts = data.get("Time Series FX (Daily)", {})
        result = []
        for date in sorted(ts.keys()):
            v = ts[date]
            try:
                result.append({
                    "time": date, "open": float(v["1. open"]),
                    "high": float(v["2. high"]), "low": float(v["3. low"]),
                    "close": float(v["4. close"]), "volume": 0.0,
                })
            except:
                continue
        return result

    def get_vix(self) -> float:
        data = self.get_alphavantage({"function": "TIME_SERIES_DAILY", "symbol": "VIX"})
        ts = data.get("Time Series (Daily)", {})
        if not ts:
            return 20.0
        return float(ts[sorted(ts.keys())[-1]]["4. close"])

    def get_spy_trend(self) -> str:
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

    def get_funding_rate(self, symbol: str) -> float:
        binance_sym = BINANCE_MAP.get(symbol)
        if not binance_sym:
            return 0.0
        try:
            r = requests.get(
                "https://fapi.binance.com/fapi/v1/fundingRate",
                params={"symbol": binance_sym, "limit": 1}, timeout=5
            )
            data = r.json()
            if data and isinstance(data, list):
                return float(data[-1].get("fundingRate", 0))
        except:
            pass
        return 0.0

    def get_open_interest(self, symbol: str) -> dict:
        binance_sym = BINANCE_MAP.get(symbol)
        if not binance_sym:
            return {}
        try:
            r = requests.get(
                "https://fapi.binance.com/fapi/v1/openInterest",
                params={"symbol": binance_sym}, timeout=5
            )
            return r.json()
        except:
            return {}

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

    def macd(self, closes: List[float], fast=12, slow=26, signal=9) -> dict:
        if len(closes) < slow + signal:
            return {}
        ema_fast  = self.ema(closes, fast)
        ema_slow  = self.ema(closes, slow)
        min_len   = min(len(ema_fast), len(ema_slow))
        macd_line = [ema_fast[-min_len+i] - ema_slow[-min_len+i] for i in range(min_len)]
        sig_line  = self.ema(macd_line, signal)
        if len(sig_line) < 2:
            return {}
        hist       = [macd_line[-len(sig_line)+i] - sig_line[i] for i in range(len(sig_line))]
        cross_up   = sig_line[-2] > macd_line[-len(sig_line)-2] and sig_line[-1] < macd_line[-1]
        cross_down = sig_line[-2] < macd_line[-len(sig_line)-2] and sig_line[-1] > macd_line[-1]
        return {
            "macd": round(macd_line[-1], 6), "signal": round(sig_line[-1], 6),
            "histogram": round(hist[-1], 6), "cross_up": cross_up,
            "cross_down": cross_down, "bullish": macd_line[-1] > sig_line[-1],
        }

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

    def market_regime(self, closes: List[float], volumes: List[float]) -> str:
        if len(closes) < 30 or len(volumes) < 30:
            return "UNDEFINED"
        rc = closes[-30:]
        rv = volumes[-30:]
        price_range = (max(rc) - min(rc)) / max(min(rc), 0.0001)
        vol_trend   = sum(rv[-10:]) / 10 - sum(rv[:10]) / 10
        price_trend = rc[-1] - rc[0]
        avg_price   = sum(rc) / len(rc)
        if price_range < 0.05 and vol_trend < 0 and rc[-1] < avg_price:
            return "ACUMULACION"
        if price_trend > 0 and vol_trend > 0:
            return "EXPANSION"
        if price_range < 0.05 and vol_trend < 0 and rc[-1] > avg_price:
            return "DISTRIBUCION"
        if price_trend < 0 and vol_trend > 0:
            return "CONTRACCION"
        return "INDEFINIDO"

    def fibonacci_levels(self, closes: List[float], lookback: int = 50) -> dict:
        if len(closes) < lookback:
            lookback = len(closes)
        recent = closes[-lookback:]
        swing_low, swing_high = min(recent), max(recent)
        diff = swing_high - swing_low
        levels = {f"fib_{int(f*1000)}": round(swing_high - diff * f, 6) for f in FIB_LEVELS}
        levels["swing_low"]  = swing_low
        levels["swing_high"] = swing_high
        return levels

    def price_at_fibonacci(self, price: float, fib_levels: dict, tolerance: float = 0.015) -> Optional[float]:
        for key, level in fib_levels.items():
            if key in ("swing_low", "swing_high"):
                continue
            if level > 0 and abs(price - level) / level <= tolerance:
                return float(key.replace("fib_", "")) / 1000
        return None

    def vwap(self, highs: List[float], lows: List[float], closes: List[float], volumes: List[float]) -> float:
        if not volumes or sum(volumes) == 0:
            return closes[-1] if closes else 0
        typical = [(h + l + c) / 3 for h, l, c in zip(highs, lows, closes)]
        total_v = sum(volumes)
        return round(sum(tp * v for tp, v in zip(typical, volumes)) / total_v, 6)

    def support_resistance(self, closes: List[float], window: int = 20) -> Tuple[float, float]:
        recent = closes[-window:] if len(closes) >= window else closes
        return min(recent), max(recent)

    def volume_above_average(self, volumes: List[float], multiplier: float = 1.1) -> bool:
        if len(volumes) < 21:
            return False
        avg = sum(volumes[-21:-1]) / 20
        return volumes[-1] > avg * multiplier if avg > 0 else False

    def divergence(self, closes: List[float], rsi_vals: List[float], lookback: int = 20) -> str:
        if len(closes) < lookback or len(rsi_vals) < lookback:
            return "NONE"
        rc, rr = closes[-lookback:], rsi_vals[-lookback:]
        pmins, rmins, pmaxs, rmaxs = [], [], [], []
        for i in range(1, len(rc) - 1):
            if rc[i] < rc[i-1] and rc[i] < rc[i+1]:
                pmins.append(rc[i]); rmins.append(rr[i])
            if rc[i] > rc[i-1] and rc[i] > rc[i+1]:
                pmaxs.append(rc[i]); rmaxs.append(rr[i])
        if len(pmins) >= 2 and pmins[-1] < pmins[-2] and rmins[-1] > rmins[-2]:
            return "BULLISH"
        if len(pmaxs) >= 2 and pmaxs[-1] > pmaxs[-2] and rmaxs[-1] < rmaxs[-2]:
            return "BEARISH"
        return "NONE"

    def full_analysis(self, ohlcv: List[dict], symbol: str = "") -> dict:
        if not ohlcv or len(ohlcv) < 30:
            return {"valid": False}
        closes  = [d["close"] for d in ohlcv if d.get("close")]
        highs   = [d.get("high", d["close"]) for d in ohlcv]
        lows    = [d.get("low", d["close"]) for d in ohlcv]
        volumes = [d.get("volumeto", d.get("volume", 0)) for d in ohlcv]
        if not closes:
            return {"valid": False}
        rsi_vals = self.rsi(closes)
        macd_d   = self.macd(closes)
        trend_v  = self.trend(closes)
        regime   = self.market_regime(closes, volumes)
        fib      = self.fibonacci_levels(closes)
        sup, res = self.support_resistance(closes)
        vwap_v   = self.vwap(highs, lows, closes, volumes)
        diverg   = self.divergence(closes, rsi_vals) if rsi_vals else "NONE"
        vol_ok   = self.volume_above_average(volumes)
        cur_rsi  = rsi_vals[-1] if rsi_vals else 50.0
        price    = closes[-1]
        return {
            "valid": True, "price": price, "trend": trend_v, "regime": regime,
            "rsi": cur_rsi, "rsi_zone": self.rsi_zone(cur_rsi, trend_v),
            "macd": macd_d, "divergence": diverg,
            "support": sup, "resistance": res,
            "vwap": vwap_v, "above_vwap": price > vwap_v,
            "fib_levels": fib, "fib_level": self.price_at_fibonacci(price, fib),
            "volume_ok": vol_ok,
            "dist_support": round((price - sup) / sup, 4) if sup > 0 else 0,
        }


# ================================================================
# CONTEXTO MACRO
# ================================================================

class MacroContext:

    def __init__(self):
        self.fetcher     = DataFetcher()
        self.cache       = {}
        self.last_update = None

    def update(self, crypto_symbols: List[str] = None) -> dict:
        if crypto_symbols is None:
            crypto_symbols = CRYPTO_SYMBOLS_DEFAULT
        logging.info("[MACRO] Actualizando contexto macro...")
        ctx = {}
        ctx["fear_greed"] = self.fetcher.get_fear_greed()

        # Funding rates de los crypto del universo dinámico
        ctx["funding_rates"] = {}
        for sym in crypto_symbols[:6]:  # máx 6 para no exceder rate limit
            ctx["funding_rates"][sym] = self.fetcher.get_funding_rate(sym)

        ctx["open_interest"] = {}
        for sym in crypto_symbols[:4]:
            oi = self.fetcher.get_open_interest(sym)
            ctx["open_interest"][sym] = float(oi.get("openInterest", 0))

        ctx["spy_trend"] = self.fetcher.get_spy_trend()
        ctx["vix"]       = self.fetcher.get_vix()
        ctx["macro_regime"]        = self._classify_macro(ctx)
        ctx["position_multiplier"] = self._position_multiplier(ctx)
        self.cache       = ctx
        self.last_update = datetime.now()
        logging.info(
            f"[MACRO] F&G:{ctx['fear_greed']} VIX:{ctx['vix']:.1f} "
            f"SPY:{ctx['spy_trend']} Regime:{ctx['macro_regime']}"
        )
        return ctx

    def _classify_macro(self, ctx: dict) -> str:
        vix, fg, spy = ctx.get("vix", 20), ctx.get("fear_greed", 50), ctx.get("spy_trend", "NEUTRAL")
        if vix > VIX_VERY_HIGH or fg < 10:
            return "DANGER"
        if vix > VIX_HIGH or fg < FEAR_GREED_PANICO or spy == "RISK_OFF":
            return "RISK_OFF"
        return "RISK_ON"

    def _position_multiplier(self, ctx: dict) -> float:
        regime, fg = ctx.get("macro_regime", "RISK_ON"), ctx.get("fear_greed", 50)
        if regime == "DANGER":   return 0.0
        if regime == "RISK_OFF": return 0.5
        if fg > FEAR_GREED_EUFORIA: return 0.5
        if fg < FEAR_GREED_PANICO:  return 1.5
        return 1.0

    def funding_signal(self, symbol: str) -> str:
        fr = self.cache.get("funding_rates", {}).get(symbol, 0)
        if fr > FUNDING_HIGH:  return "OVERCROWDED_LONG"
        if fr < FUNDING_LOW:   return "OVERCROWDED_SHORT"
        return "NEUTRAL"


# ================================================================
# SCORER — 8 condiciones
# ================================================================

class SignalScorer:

    def __init__(self):
        self.ta = TechnicalAnalysis()

    def score_buy(self, daily: dict, h4: dict, macro: dict, funding_sig: str) -> Tuple[int, dict]:
        checks = {}
        checks["tendencia_alcista"]      = daily.get("trend") in ("BULLISH", "LATERAL")
        checks["rsi_zona_compra"]        = daily.get("rsi_zone") == "BUY_ZONE"
        macd = daily.get("macd", {})
        checks["macd_alcista"]           = macd.get("bullish", False) or macd.get("cross_up", False)
        at_sup = daily.get("dist_support", 1) <= 0.02
        at_fib = daily.get("fib_level") in (0.382, 0.500, 0.618)
        checks["en_soporte_o_fibonacci"] = at_sup or at_fib
        checks["volumen_confirma"]       = daily.get("volume_ok", False)
        checks["divergencia_alcista"]    = daily.get("divergence") == "BULLISH"
        checks["4h_alineado"]            = h4.get("trend") != "BEARISH" if h4.get("valid") else True
        macro_ok   = macro.get("macro_regime") != "DANGER"
        funding_ok = funding_sig != "OVERCROWDED_LONG"
        regime_ok  = daily.get("regime") in ("ACUMULACION", "EXPANSION", "INDEFINIDO")
        checks["macro_favorable"]        = macro_ok and funding_ok and regime_ok
        score = sum(1 for v in checks.values() if v)
        return score, checks

    def score_sell(self, daily: dict, h4: dict, macro: dict, funding_sig: str) -> Tuple[int, dict]:
        checks = {}
        checks["tendencia_bajista"]   = daily.get("trend") in ("BEARISH", "LATERAL")
        checks["rsi_zona_venta"]      = daily.get("rsi_zone") == "SELL_ZONE"
        macd = daily.get("macd", {})
        checks["macd_bajista"]        = not macd.get("bullish", True) or macd.get("cross_down", False)
        res = daily.get("resistance", 0)
        at_res = res > 0 and abs(daily.get("price", 0) - res) / res <= 0.02
        checks["en_resistencia"]      = at_res
        checks["volumen_confirma"]    = daily.get("volume_ok", False)
        checks["divergencia_bajista"] = daily.get("divergence") == "BEARISH"
        checks["4h_alineado"]         = h4.get("trend") != "BULLISH" if h4.get("valid") else True
        checks["macro_desfavorable"]  = (
            macro.get("macro_regime") in ("RISK_OFF", "DANGER") or
            daily.get("regime") in ("DISTRIBUCION", "CONTRACCION")
        )
        score = sum(1 for v in checks.values() if v)
        return score, checks


# ================================================================
# KELLY CRITERION
# ================================================================

class KellyCriterion:

    def calculate(self, trades: List[dict], base_pct: float) -> float:
        sells = [t for t in trades if t.get("action") == "SELL" and "pnl" in t]
        if len(sells) < 20:
            return base_pct
        wins   = [t for t in sells if t["pnl"] > 0]
        losses = [t for t in sells if t["pnl"] <= 0]
        if not wins or not losses:
            return base_pct
        win_rate = len(wins) / len(sells)
        avg_win  = sum(t["pnl"] for t in wins) / len(wins)
        avg_loss = abs(sum(t["pnl"] for t in losses) / len(losses))
        if avg_loss == 0:
            return base_pct
        kelly = (win_rate / avg_loss) - ((1 - win_rate) / avg_win)
        return max(0.02, min(kelly * 0.5, MAX_POSITION_PCT))


# ================================================================
# FILTROS PSICOLÓGICOS
# ================================================================

class PsychologyFilters:

    def check_all(self, symbol: str, direction: str, portfolio: "Portfolio", macro: dict) -> Tuple[bool, List[str]]:
        failures     = []
        fear_greed   = macro.get("fear_greed", 50)
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
            if portfolio.positions[symbol]["current_price"] < portfolio.positions[symbol]["avg_price"]:
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
        self.capital               = INITIAL_CAPITAL
        self.positions: Dict[str, dict] = {}
        self.trades: List[dict]         = []
        self.equity_curve               = [INITIAL_CAPITAL]
        self.status                = "RUNNING"
        self.pause_reason          = ""
        self.consecutive_losses    = 0
        self.daily_pnl_pct         = 0.0
        self.monthly_pnl_pct       = 0.0
        self.start_of_day_equity   = INITIAL_CAPITAL
        self.start_of_month_equity = INITIAL_CAPITAL
        self.entry_distances: Dict[str, float] = {}
        # Fee engine de Alpaca
        self.fee_engine      = AlpacaFeeEngine() if _FEE_ENGINE_AVAILABLE else None
        self.total_fees_paid = 0.0

    def _get_asset_type(self, symbol: str) -> str:
        """Detecta si el activo es crypto, forex o stock"""
        crypto_syms = {"BTC","ETH","SOL","BNB","AVAX","MATIC","LINK","DOT","ADA",
                       "ORDI","ZEC","LTC","LAB","BIO","ORCA","TAO","UB","TRX"}
        if symbol in crypto_syms:
            return "crypto"
        if "/" in symbol:
            return "forex"
        return "stock"

    def pause(self, reason: str):
        self.status       = "PAUSED"
        self.pause_reason = reason
        logging.warning(f"[BOT PAUSADO] {reason}")

    def resume(self):
        self.status             = "RUNNING"
        self.pause_reason       = ""
        self.consecutive_losses = 0

    def reset_daily(self):
        pos_val = sum(p["qty"] * p["current_price"] for p in self.positions.values())
        self.start_of_day_equity = self.capital + pos_val
        self.daily_pnl_pct = 0.0
        if self.pause_reason == "Límite pérdida diaria 6%":
            self.resume()

    def open_position(self, symbol: str, price: float, signal_type: str, size_pct: float) -> bool:
        allocation = INITIAL_CAPITAL * size_pct
        if self.capital < allocation or price <= 0:
            return False
        qty = allocation / price

        # Calcular y descontar fees de Alpaca en la compra
        if self.fee_engine:
            asset_type = self._get_asset_type(symbol)
            fee_data   = self.fee_engine.calculate_buy_fees(symbol, price, qty, asset_type)
            buy_fee    = fee_data["total"]
            self.total_fees_paid += buy_fee
            # El fee reduce el capital disponible
            if self.capital < allocation + buy_fee:
                buy_fee = 0.0  # si no alcanza, absorbe el fee (centavos)
        else:
            buy_fee    = 0.0
            asset_type = self._get_asset_type(symbol)

        if symbol in self.positions:
            pos = self.positions[symbol]
            if pos["current_price"] < pos["avg_price"]:
                return False
            total_qty        = pos["qty"] + qty
            pos["avg_price"] = (pos["avg_price"] * pos["qty"] + price * qty) / total_qty
            pos["qty"]       = total_qty
        else:
            self.positions[symbol] = {
                "qty": qty, "avg_price": price, "current_price": price,
                "stop_loss":       round(price * (1 - STOP_LOSS_PCT), 6),
                "take_profit":     round(price * (1 + TAKE_PROFIT_PCT), 6),
                "trailing_stop":   None, "trailing_active": False,
                "max_price_seen":  price,
                "opened_at":       datetime.now().isoformat(),
                "signal_type":     signal_type,
                "asset_type":      asset_type,
            }
        self.capital -= (allocation + buy_fee)
        self.trades.append({
            "action": "BUY", "symbol": symbol, "price": price,
            "qty": qty, "allocation": round(allocation, 2),
            "fee": round(buy_fee, 6),
            "signal_type": signal_type, "timestamp": datetime.now().isoformat(),
        })
        logging.info(f"[OPEN] {signal_type} {symbol} @ ${price:,.4f} | alloc: ${allocation:,.0f} | fee: ${buy_fee:.4f}")
        return True

    def close_position(self, symbol: str, price: float, reason: str) -> Optional[float]:
        if symbol not in self.positions:
            return None
        pos      = self.positions[symbol]
        proceeds = pos["qty"] * price
        cost     = pos["qty"] * pos["avg_price"]

        # Calcular y descontar fees de Alpaca en la venta
        if self.fee_engine:
            asset_type = pos.get("asset_type", self._get_asset_type(symbol))
            fee_data   = self.fee_engine.calculate_sell_fees(
                symbol, price, pos["qty"], asset_type,
                shares=pos["qty"]  # para FINRA TAF
            )
            sell_fee = fee_data["total"]
            self.total_fees_paid += sell_fee
        else:
            sell_fee   = 0.0
            asset_type = self._get_asset_type(symbol)

        # P&L neto = proceeds - costo original - fee de venta
        net_proceeds = proceeds - sell_fee
        pnl          = net_proceeds - cost

        self.capital += net_proceeds
        self.trades.append({
            "action": "SELL", "symbol": symbol, "price": price,
            "qty": pos["qty"], "proceeds": round(proceeds, 2),
            "sell_fee": round(sell_fee, 6),
            "pnl": round(pnl, 2), "pnl_pct": round(pnl / max(cost, 0.01) * 100, 2),
            "reason": reason, "timestamp": datetime.now().isoformat(),
        })
        self.consecutive_losses = self.consecutive_losses + 1 if pnl < 0 else 0
        del self.positions[symbol]
        logging.info(f"[CLOSE] {reason} {symbol} @ ${price:,.4f} | P&L neto: ${pnl:+,.2f} | fee: ${sell_fee:.4f}")
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
            event["pnl"] = self.close_position(event["symbol"], event["price"], event["reason"])
        pos_val  = sum(p["qty"] * p["current_price"] for p in self.positions.values())
        total_eq = self.capital + pos_val
        self.equity_curve.append(round(total_eq, 2))
        if self.start_of_day_equity > 0:
            self.daily_pnl_pct = (total_eq - self.start_of_day_equity) / self.start_of_day_equity
        if self.start_of_month_equity > 0:
            self.monthly_pnl_pct = (total_eq - self.start_of_month_equity) / self.start_of_month_equity
        if self.monthly_pnl_pct <= -MONTHLY_LOSS_LIMIT_PCT:
            self.pause("Límite pérdida mensual 15%")
        return stops

    def get_summary(self) -> dict:
        pos_val  = sum(p["qty"] * p["current_price"] for p in self.positions.values())
        total_eq = self.capital + pos_val
        pnl      = total_eq - INITIAL_CAPITAL
        sells    = [t for t in self.trades if t["action"] == "SELL"]
        wins     = [t for t in sells if t.get("pnl", 0) > 0]
        return {
            "capital_libre":         round(self.capital, 2),
            "posiciones_valor":      round(pos_val, 2),
            "equity_total":          round(total_eq, 2),
            "pnl_neto":              round(pnl, 2),
            "pnl_pct":               round(pnl / INITIAL_CAPITAL * 100, 2),
            "posiciones_abiertas":   len(self.positions),
            "trades_totales":        len(self.trades),
            "win_rate":              round(len(wins) / len(sells) * 100, 1) if sells else 0,
            "perdidas_consecutivas": self.consecutive_losses,
            "daily_pnl_pct":         round(self.daily_pnl_pct * 100, 2),
            "monthly_pnl_pct":       round(self.monthly_pnl_pct * 100, 2),
            "status":                self.status,
            "pause_reason":          self.pause_reason,
            "equity_curve":          self.equity_curve[-60:],
            # Fees de Alpaca
            "fees_pagados_usd":      round(self.total_fees_paid, 4),
            "fee_breakdown":         self.fee_engine.get_summary() if self.fee_engine else {},
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
            logging.info(f"[TELEGRAM MOCK] {message[:80]}")
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
# BOT PRINCIPAL v3
# ================================================================

class TradingBot:

    def __init__(self):
        self.fetcher        = DataFetcher()
        self.ta             = TechnicalAnalysis()
        self.scorer         = SignalScorer()
        self.psych          = PsychologyFilters()
        self.kelly          = KellyCriterion()
        self.macro_ctx      = MacroContext()
        self.portfolio      = Portfolio()
        self.notifier       = Notifier()
        self.running        = False
        self.last_prices:   Dict[str, float] = {}
        self.last_signals:  List[dict]       = []
        self.last_universe: dict             = {}
        self.cycle_count    = 0
        self.macro: dict    = {}

    # ---- Análisis de un activo ---------------------------------

    def analyze(self, symbol: str, asset_type: str) -> Optional[dict]:
        try:
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
                logging.info(f"[SKIP] {symbol} — datos insuficientes ({len(daily_raw)} velas)")
                return None

            daily = self.ta.full_analysis(daily_raw, symbol)
            h4    = self.ta.full_analysis(h4_raw, symbol) if len(h4_raw) >= 30 else {"valid": False}

            if not daily.get("valid"):
                return None

            self.last_prices[symbol] = daily["price"]
            self.portfolio.entry_distances[symbol] = daily.get("dist_support", 1)

            funding_sig = self.macro_ctx.funding_signal(symbol) if asset_type == "crypto" else "NEUTRAL"

            buy_score,  buy_checks  = self.scorer.score_buy(daily, h4, self.macro, funding_sig)
            sell_score, sell_checks = self.scorer.score_sell(daily, h4, self.macro, funding_sig)

            if buy_score >= sell_score and buy_score >= MIN_SIGNAL_SCORE:
                direction, score, checks = "BUY", buy_score, buy_checks
            elif sell_score > buy_score and sell_score >= MIN_SIGNAL_SCORE:
                direction, score, checks = "SELL", sell_score, sell_checks
            else:
                return None

            signal_type = "STRONG_BUY" if direction == "BUY" and score >= SCORE_STRONG_BUY else direction

            return {
                "symbol": symbol, "asset_type": asset_type,
                "direction": direction, "signal_type": signal_type,
                "price": daily["price"], "score": score, "max_score": 8,
                "checks": checks, "daily": daily,
                "h4_valid": h4.get("valid", False),
                "funding": funding_sig, "timestamp": datetime.now().isoformat(),
            }
        except Exception as e:
            logging.error(f"[ANALYZE ERROR] {symbol}: {e}")
            return None

    # ---- Ejecutar señal ----------------------------------------

    def execute(self, signal: dict):
        symbol, direction = signal["symbol"], signal["direction"]
        price, signal_type = signal["price"], signal["signal_type"]
        score, daily = signal["score"], signal["daily"]
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
                    f"Tendencia: {daily['trend']} · RSI: {daily['rsi']:.1f} · "
                    f"MACD: {'✅' if daily.get('macd', {}).get('bullish') else '❌'}\n"
                    f"Régimen: {daily['regime']} · VWAP: {'↑' if daily['above_vwap'] else '↓'}\n"
                    f"Fib: {daily['fib_level'] or 'N/A'} · Funding: {signal['funding']}\n"
                    f"SL: `${pos.get('stop_loss', 0):,.4f}` · TP: `${pos.get('take_profit', 0):,.4f}`\n"
                    f"Macro: {self.macro.get('macro_regime')} · "
                    f"F&G: {self.macro.get('fear_greed')} · VIX: {self.macro.get('vix', 0):.1f}"
                )

        elif direction == "SELL" and symbol in self.portfolio.positions:
            pnl = self.portfolio.close_position(symbol, price, "SEÑAL_VENTA")
            if pnl is not None:
                emoji = "🟢" if pnl > 0 else "🔴"
                self.notifier.send(
                    f"{emoji} *SELL* `{symbol}` @ `${price:,.4f}`\n"
                    f"Score: {score}/8 · P&L: `${pnl:+,.2f}`\n"
                    f"RSI: {daily['rsi']:.1f} · Div: {daily['divergence']}"
                )

    # ---- Ciclo principal con universo dinámico -----------------

    def run_cycle(self) -> dict:
        self.cycle_count += 1
        logging.info(f"[CICLO {self.cycle_count}] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        # 1. Construir universo dinámico
        if DYNAMIC_UNIVERSE:
            try:
                universe_data = universe_builder.build()
                symbols       = universe_builder.get_symbols_by_type(universe_data["universe"])
                self.last_universe = universe_data
                crypto_syms   = symbols["crypto"]
                stock_syms    = symbols["stocks"]
                forex_pairs   = symbols["forex"]
                self.notifier.send(
                    f"🔍 *Universo del día*\n"
                    f"Total: *{universe_data['total']} activos*\n"
                    f"Crypto: {universe_data['breakdown']['crypto']} · "
                    f"USA+LATAM: {universe_data['breakdown']['usa'] + universe_data['breakdown']['latam']} · "
                    f"Forex: {universe_data['breakdown']['forex']}\n"
                    f"Sectores líderes: {', '.join(universe_data.get('leading_sectors', []))}"
                )
            except Exception as e:
                logging.error(f"[UNIVERSE ERROR] {e} — usando universo fijo")
                crypto_syms = CRYPTO_SYMBOLS_DEFAULT
                stock_syms  = STOCK_SYMBOLS_DEFAULT
                forex_pairs = FOREX_PAIRS_DEFAULT
        else:
            crypto_syms = CRYPTO_SYMBOLS_DEFAULT
            stock_syms  = STOCK_SYMBOLS_DEFAULT
            forex_pairs = FOREX_PAIRS_DEFAULT

        # 2. Actualizar contexto macro con los crypto del universo
        self.macro = self.macro_ctx.update(crypto_symbols=crypto_syms)

        if self.macro.get("macro_regime") == "DANGER":
            self.notifier.send(
                f"⚠️ *MACRO DANGER*\n"
                f"VIX: {self.macro.get('vix', 0):.1f} · F&G: {self.macro.get('fear_greed')}\n"
                f"No se abren nuevas posiciones."
            )

        signals_ok, signals_blocked = [], []

        # 3. Analizar crypto
        for sym in crypto_syms:
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

        # 4. Analizar stocks (USA + LATAM)
        for sym in stock_syms:
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

        # 5. Analizar forex
        for from_sym, to_sym in forex_pairs:
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

        # 6. Chequear stops automáticos
        stops = self.portfolio.update_prices(self.last_prices)
        for event in stops:
            emoji = {"STOP_LOSS": "🔴", "TRAILING_STOP": "🟡", "TAKE_PROFIT": "🟢"}.get(event["reason"], "⚪")
            self.notifier.send(
                f"{emoji} *{event['reason']}*\n"
                f"`{event['symbol']}` @ `${event['price']:,.4f}` · "
                f"P&L: `${event.get('pnl', 0):+,.2f}`"
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
            "universe_total":  len(crypto_syms) + len(stock_syms) + len(forex_pairs),
            "signals_ok":      len(signals_ok),
            "signals_blocked": len(signals_blocked),
            "stops":           len(stops),
            "summary":         summary,
        }

    # ---- Loop asíncrono ----------------------------------------

    async def start(self, interval_minutes: int = 60):
        self.running = True
        self.notifier.send(
            f"🚀 *BetScan Trading Bot v3.0 iniciado*\n"
            f"Capital: `$50,000` · Ciclo: {interval_minutes}min\n"
            f"Motor: RSI+MACD+Fibonacci+VWAP+Wyckoff\n"
            f"Universo: dinámico — top 50 activos del día\n"
            f"Score mínimo: {MIN_SIGNAL_SCORE}/8"
        )
        while self.running:
            try:
                self.run_cycle()
            except Exception as e:
                logging.error(f"[ERROR CICLO] {e}")
                self.notifier.send(f"⚠️ *Error en ciclo*\n`{str(e)}`")
            await asyncio.sleep(interval_minutes * 60)

    def stop(self):
        self.running = False
        self.notifier.send("⏹ *BetScan Trading Bot v3.0 detenido*")


# ================================================================
# INSTANCIA GLOBAL
# ================================================================

bot = TradingBot()
