"""
BetScan Market Scraper — Universo Dinámico v1.0
================================================
Encuentra las 50 mejores oportunidades del día combinando:
  - Volumen relativo (volumen hoy vs promedio 20 días)
  - Momentum     (% cambio en el día)
  - Sector fuerte (sectores líderes del día)

Mercados cubiertos:
  - USA stocks  → Finviz screener (NYSE + NASDAQ)
  - LATAM stocks → lista curada + AlphaVantage
  - Crypto      → CryptoCompare top por volumen 24h
  - Forex       → pares principales + LATAM

Resultado: lista de 50 activos rankeados por score compuesto
           que el bot analiza con el motor de inteligencia v2

Integración:
  - Se importa en trading_bot.py
  - Corre al inicio de cada ciclo
  - Reemplaza CRYPTO_SYMBOLS, STOCK_SYMBOLS, FOREX_PAIRS fijos
"""

import os
import time
import logging
import requests
from typing import List, Dict, Optional
from datetime import datetime

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

ALPHAVANTAGE_KEY  = os.getenv("ALPHAVANTAGE_API_KEY", "CGVZCOX2KGSDAN7X")
CRYPTOCOMPARE_KEY = os.getenv("CRYPTOCOMPARE_API_KEY", "")

# ================================================================
# LISTAS BASE
# ================================================================

# LATAM — lista curada manual (no hay screener público confiable)
LATAM_STOCKS = [
    "YPF",   # YPF Argentina
    "MELI",  # MercadoLibre
    "GLOB",  # Globant
    "BBAR",  # Banco BBVA Argentina
    "GGAL",  # Grupo Financiero Galicia
    "SUPV",  # Supervielle
    "LOMA",  # Loma Negra
    "CEPU",  # Central Puerto
    "VSTA",  # Vista Energy
    "PBR",   # Petrobras Brasil
    "ITUB",  # Itaú Unibanco Brasil
    "VALE",  # Vale Brasil
    "NU",    # Nubank
    "AMXL",  # América Móvil México
    "BSAC",  # Banco Santander Chile
]

# Forex — majors + pares LATAM
FOREX_UNIVERSE = [
    ("EUR", "USD"),
    ("GBP", "USD"),
    ("USD", "JPY"),
    ("AUD", "USD"),
    ("USD", "CHF"),
    ("USD", "BRL"),  # Dólar vs Real
    ("USD", "MXN"),  # Dólar vs Peso mexicano
    ("USD", "CLP"),  # Dólar vs Peso chileno
]

# Sectores fuertes — se actualizan en cada ciclo
SECTOR_ETFS = {
    "tech":       "XLK",
    "energy":     "XLE",
    "health":     "XLV",
    "finance":    "XLF",
    "consumer":   "XLY",
    "materials":  "XLB",
    "utilities":  "XLU",
    "industrial": "XLI",
    "real_estate":"XLRE",
    "crypto":     "BITO",
}

# Top 30 stocks USA como base (Finviz las filtra y rankea)
USA_BASE = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO",
    "TSM",  "AMD",  "ORCL", "NFLX", "CRM",   "ADBE", "QCOM", "INTC",
    "SNDK", "MSTR", "PLTR", "COIN", "HOOD",  "RBLX", "UBER", "LYFT",
    "SOFI", "RIVN", "NIO",  "LCID", "XPEV",  "F",    "GM",   "GE",
    "BA",   "CAT",  "XOM",  "CVX",  "TPL",   "SLB",  "OXY",  "MRK",
    "PFE",  "MRNA", "ABBV", "JNJ",  "LLY",   "JPM",  "BAC",  "GS",
    "WFC",  "V",    "MA",   "PYPL", "SQ",    "SPY",  "QQQ",  "GLD",
    "TLT",  "EEM",  "IWM",  "DIA",
]


# ================================================================
# SECTOR DETECTOR — detecta qué sectores lideran hoy
# ================================================================

class SectorDetector:

    def get_leading_sectors(self) -> List[str]:
        """
        Obtiene el rendimiento diario de cada sector ETF
        y retorna los top 3 sectores del día.
        """
        performances = {}
        for sector, etf in SECTOR_ETFS.items():
            perf = self._get_daily_change(etf)
            if perf is not None:
                performances[sector] = perf
            time.sleep(12)  # AlphaVantage rate limit

        if not performances:
            return ["tech", "energy", "finance"]  # fallback

        sorted_sectors = sorted(performances.items(), key=lambda x: x[1], reverse=True)
        top3 = [s[0] for s in sorted_sectors[:3]]
        logging.info(f"[SECTORES] Top hoy: {top3} | Performances: {dict(sorted_sectors[:5])}")
        return top3

    def _get_daily_change(self, symbol: str) -> Optional[float]:
        try:
            url = "https://www.alphavantage.co/query"
            params = {
                "function": "GLOBAL_QUOTE",
                "symbol": symbol,
                "apikey": ALPHAVANTAGE_KEY,
            }
            r = requests.get(url, params=params, timeout=10)
            quote = r.json().get("Global Quote", {})
            change_pct = quote.get("10. change percent", "0%").replace("%", "")
            return float(change_pct)
        except:
            return None


# ================================================================
# USA SCREENER — Finviz + AlphaVantage
# ================================================================

class USAScreener:

    def get_top_movers(self, limit: int = 30) -> List[Dict]:
        """
        Intenta Finviz primero. Si falla (bloqueo), usa AlphaVantage
        con la lista base USA_BASE.
        """
        candidates = self._scrape_finviz()
        if not candidates:
            logging.info("[USA] Finviz bloqueado — usando AlphaVantage con lista base")
            candidates = self._alphavantage_screen()

        # Calcular score compuesto y rankear
        scored = []
        for c in candidates:
            score = self._composite_score(c)
            scored.append({**c, "composite_score": score})

        scored.sort(key=lambda x: x["composite_score"], reverse=True)
        return scored[:limit]

    def _scrape_finviz(self) -> List[Dict]:
        """
        Scrapea Finviz screener filtrando por:
        - Volumen > 1M
        - Cambio % > 2% o < -2%
        - Precio > $5 (evita penny stocks)
        """
        if BeautifulSoup is None:
            return []
        try:
            url = (
                "https://finviz.com/screener.ashx"
                "?v=111&f=sh_price_o5,sh_vol_o1000,ta_change_u2&o=-volume"
            )
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/120.0.0.0 Safari/537.36"
            }
            r = requests.get(url, headers=headers, timeout=15)
            if r.status_code != 200:
                return []
            soup = BeautifulSoup(r.text, "lxml")
            table = soup.find("table", {"id": "screener-views-table"})
            if not table:
                # Intentar tabla alternativa
                tables = soup.find_all("table", class_="table-light")
                if not tables:
                    return []
                table = tables[0]

            rows = table.find_all("tr")[1:]
            results = []
            for row in rows[:50]:
                cols = row.find_all("td")
                if len(cols) < 10:
                    continue
                try:
                    symbol     = cols[1].text.strip()
                    price      = float(cols[8].text.strip().replace(",", ""))
                    change_pct = float(cols[9].text.strip().replace("%", ""))
                    volume     = self._parse_volume(cols[10].text.strip())
                    results.append({
                        "symbol":     symbol,
                        "price":      price,
                        "change_pct": change_pct,
                        "volume":     volume,
                        "source":     "finviz",
                        "asset_type": "stock",
                        "market":     "USA",
                    })
                except:
                    continue
            logging.info(f"[FINVIZ] {len(results)} candidatos encontrados")
            return results
        except Exception as e:
            logging.error(f"[FINVIZ] Error: {e}")
            return []

    def _alphavantage_screen(self) -> List[Dict]:
        """Fallback: evalúa la lista base con Global Quote de AlphaVantage"""
        results = []
        for symbol in USA_BASE[:20]:  # limitado por rate limit
            try:
                url = "https://www.alphavantage.co/query"
                params = {
                    "function": "GLOBAL_QUOTE",
                    "symbol": symbol,
                    "apikey": ALPHAVANTAGE_KEY,
                }
                r = requests.get(url, params=params, timeout=10)
                quote = r.json().get("Global Quote", {})
                if not quote:
                    continue
                change_str = quote.get("10. change percent", "0%").replace("%", "")
                results.append({
                    "symbol":     symbol,
                    "price":      float(quote.get("05. price", 0)),
                    "change_pct": float(change_str),
                    "volume":     float(quote.get("06. volume", 0)),
                    "source":     "alphavantage",
                    "asset_type": "stock",
                    "market":     "USA",
                })
                time.sleep(12)
            except:
                continue
        return results

    def _parse_volume(self, vol_str: str) -> float:
        vol_str = vol_str.replace(",", "").upper()
        if "M" in vol_str:
            return float(vol_str.replace("M", "")) * 1_000_000
        if "K" in vol_str:
            return float(vol_str.replace("K", "")) * 1_000
        try:
            return float(vol_str)
        except:
            return 0.0

    def _composite_score(self, c: Dict) -> float:
        """
        Score compuesto 0-100:
          40% volumen relativo
          40% momentum (% cambio)
          20% precio (filtra penny stocks)
        """
        vol_score  = min(c.get("volume", 0) / 10_000_000 * 40, 40)
        mom_score  = min(abs(c.get("change_pct", 0)) * 4, 40)
        price_score = 20 if c.get("price", 0) >= 10 else 10
        return round(vol_score + mom_score + price_score, 2)


# ================================================================
# CRYPTO SCREENER — CryptoCompare top por volumen
# ================================================================

class CryptoScreener:

    def get_top_crypto(self, limit: int = 15) -> List[Dict]:
        """
        Top cryptos por volumen 24h usando CryptoCompare.
        Filtra stablecoins y retorna las más activas.
        """
        STABLECOINS = {"USDT", "USDC", "BUSD", "DAI", "TUSD", "USDP", "FRAX", "GUSD"}
        try:
            url = "https://min-api.cryptocompare.com/data/top/totalvolfull"
            params = {"limit": 50, "tsym": "USDT"}
            headers = {"authorization": f"Apikey {CRYPTOCOMPARE_KEY}"} if CRYPTOCOMPARE_KEY else {}
            r = requests.get(url, params=params, headers=headers, timeout=10)
            data = r.json().get("Data", [])

            results = []
            for item in data:
                coin_info = item.get("CoinInfo", {})
                raw       = item.get("RAW", {}).get("USDT", {})
                symbol    = coin_info.get("Name", "")

                if symbol in STABLECOINS:
                    continue
                if not raw:
                    continue

                price      = raw.get("PRICE", 0)
                change_pct = raw.get("CHANGEPCT24HOUR", 0)
                volume_24h = raw.get("TOTALVOLUME24HTO", 0)

                score = self._composite_score(volume_24h, change_pct, price)
                results.append({
                    "symbol":     symbol,
                    "price":      price,
                    "change_pct": change_pct,
                    "volume":     volume_24h,
                    "composite_score": score,
                    "source":     "cryptocompare",
                    "asset_type": "crypto",
                    "market":     "CRYPTO",
                })

            results.sort(key=lambda x: x["composite_score"], reverse=True)
            logging.info(f"[CRYPTO] {len(results[:limit])} candidatos: {[r['symbol'] for r in results[:limit]]}")
            return results[:limit]

        except Exception as e:
            logging.error(f"[CRYPTO SCREENER] Error: {e}")
            # Fallback a lista base
            return [
                {"symbol": s, "asset_type": "crypto", "market": "CRYPTO",
                 "composite_score": 50, "source": "fallback"}
                for s in ["BTC", "ETH", "SOL", "BNB", "AVAX", "MATIC", "LINK", "DOT"]
            ]

    def _composite_score(self, volume: float, change_pct: float, price: float) -> float:
        vol_score  = min(volume / 1_000_000_000 * 40, 40)   # escala en billones
        mom_score  = min(abs(change_pct) * 4, 40)
        price_score = 20 if price >= 1 else 5
        return round(vol_score + mom_score + price_score, 2)


# ================================================================
# LATAM SCREENER
# ================================================================

class LATAMScreener:

    def get_top_latam(self, limit: int = 8) -> List[Dict]:
        """Evalúa la lista curada LATAM con Global Quote de AlphaVantage"""
        results = []
        for symbol in LATAM_STOCKS:
            try:
                url = "https://www.alphavantage.co/query"
                params = {
                    "function": "GLOBAL_QUOTE",
                    "symbol":   symbol,
                    "apikey":   ALPHAVANTAGE_KEY,
                }
                r = requests.get(url, params=params, timeout=10)
                quote = r.json().get("Global Quote", {})
                if not quote or not quote.get("05. price"):
                    time.sleep(12)
                    continue
                change_str = quote.get("10. change percent", "0%").replace("%", "")
                change_pct = float(change_str)
                volume     = float(quote.get("06. volume", 0))
                price      = float(quote.get("05. price", 0))
                score      = self._composite_score(volume, change_pct, price)
                results.append({
                    "symbol":          symbol,
                    "price":           price,
                    "change_pct":      change_pct,
                    "volume":          volume,
                    "composite_score": score,
                    "source":          "alphavantage",
                    "asset_type":      "stock",
                    "market":          "LATAM",
                })
                time.sleep(12)
            except Exception as e:
                logging.error(f"[LATAM] {symbol}: {e}")
                continue

        results.sort(key=lambda x: x["composite_score"], reverse=True)
        logging.info(f"[LATAM] {len(results[:limit])} candidatos: {[r['symbol'] for r in results[:limit]]}")
        return results[:limit]

    def _composite_score(self, volume: float, change_pct: float, price: float) -> float:
        vol_score   = min(volume / 1_000_000 * 40, 40)
        mom_score   = min(abs(change_pct) * 4, 40)
        price_score = 20 if price >= 5 else 10
        return round(vol_score + mom_score + price_score, 2)


# ================================================================
# FOREX SCREENER
# ================================================================

class ForexScreener:

    def get_top_forex(self, limit: int = 5) -> List[Dict]:
        """Evalúa los pares forex por volatilidad del día"""
        results = []
        for from_sym, to_sym in FOREX_UNIVERSE:
            try:
                url = "https://www.alphavantage.co/query"
                params = {
                    "function":    "CURRENCY_EXCHANGE_RATE",
                    "from_currency": from_sym,
                    "to_currency":   to_sym,
                    "apikey":        ALPHAVANTAGE_KEY,
                }
                r = requests.get(url, params=params, timeout=10)
                data = r.json().get("Realtime Currency Exchange Rate", {})
                if not data:
                    time.sleep(12)
                    continue
                rate = float(data.get("5. Exchange Rate", 0))
                # Forex no tiene % diario en este endpoint — usamos variación estimada
                results.append({
                    "symbol":          f"{from_sym}/{to_sym}",
                    "from_sym":        from_sym,
                    "to_sym":          to_sym,
                    "price":           rate,
                    "change_pct":      0.0,   # se calcula en análisis técnico
                    "volume":          0.0,
                    "composite_score": 30.0,  # score base para forex
                    "source":          "alphavantage",
                    "asset_type":      "forex",
                    "market":          "FOREX",
                })
                time.sleep(12)
            except Exception as e:
                logging.error(f"[FOREX] {from_sym}/{to_sym}: {e}")
                continue

        # Priorizar los majors clásicos
        priority = ["EUR/USD", "GBP/USD", "USD/JPY"]
        results.sort(key=lambda x: (x["symbol"] not in priority, -x["composite_score"]))
        logging.info(f"[FOREX] {len(results[:limit])} pares seleccionados")
        return results[:limit]


# ================================================================
# UNIVERSE BUILDER — orquesta todo y devuelve los 50
# ================================================================

class UniverseBuilder:
    """
    Construye el universo dinámico de 50 activos para el ciclo actual.

    Distribución objetivo:
      30 stocks USA    (los más activos del día)
       8 stocks LATAM  (lista curada rankeada)
      10 crypto        (top por volumen 24h)
       5 forex         (majors + LATAM relevantes)
      -- hasta 3 bonus de sectores fuertes del día --
    """

    def __init__(self):
        self.usa_screener    = USAScreener()
        self.crypto_screener = CryptoScreener()
        self.latam_screener  = LATAMScreener()
        self.forex_screener  = ForexScreener()
        self.sector_detector = SectorDetector()

    def build(self) -> Dict:
        """
        Corre todos los screeners y retorna el universo del día.
        Tiempo estimado: 8-12 minutos (limitado por AlphaVantage rate limit)
        """
        start = datetime.now()
        logging.info("[UNIVERSE] Construyendo universo dinámico del día...")

        # 1. Detectar sectores líderes
        leading_sectors = self.sector_detector.get_leading_sectors()

        # 2. Crypto — rápido, sin rate limit
        crypto = self.crypto_screener.get_top_crypto(limit=10)

        # 3. USA stocks — Finviz o AlphaVantage fallback
        usa = self.usa_screener.get_top_movers(limit=30)

        # 4. LATAM — AlphaVantage
        latam = self.latam_screener.get_top_latam(limit=8)

        # 5. Forex
        forex = self.forex_screener.get_top_forex(limit=5)

        # Combinar y deduplicar
        all_assets = crypto + usa + latam + forex
        seen = set()
        universe = []
        for asset in all_assets:
            sym = asset["symbol"]
            if sym not in seen:
                seen.add(sym)
                universe.append(asset)

        # Ordenar por score compuesto descendente
        universe.sort(key=lambda x: x.get("composite_score", 0), reverse=True)
        universe = universe[:50]

        elapsed = (datetime.now() - start).seconds
        logging.info(
            f"[UNIVERSE] ✅ {len(universe)} activos seleccionados en {elapsed}s\n"
            f"  Sectores líderes: {leading_sectors}\n"
            f"  Crypto: {[a['symbol'] for a in universe if a['asset_type']=='crypto']}\n"
            f"  USA:    {[a['symbol'] for a in universe if a['market']=='USA'][:10]}...\n"
            f"  LATAM:  {[a['symbol'] for a in universe if a['market']=='LATAM']}\n"
            f"  Forex:  {[a['symbol'] for a in universe if a['asset_type']=='forex']}"
        )

        return {
            "universe":        universe,
            "leading_sectors": leading_sectors,
            "total":           len(universe),
            "built_at":        datetime.now().isoformat(),
            "breakdown": {
                "crypto": len([a for a in universe if a["asset_type"] == "crypto"]),
                "usa":    len([a for a in universe if a["market"] == "USA"]),
                "latam":  len([a for a in universe if a["market"] == "LATAM"]),
                "forex":  len([a for a in universe if a["asset_type"] == "forex"]),
            }
        }

    def get_symbols_by_type(self, universe: list) -> Dict:
        """Separa el universo por tipo para el bot"""
        return {
            "crypto": [a["symbol"] for a in universe if a["asset_type"] == "crypto"],
            "stocks": [a["symbol"] for a in universe if a["asset_type"] == "stock"],
            "forex":  [
                (a["from_sym"], a["to_sym"])
                for a in universe if a["asset_type"] == "forex"
            ],
        }


# Instancia global
universe_builder = UniverseBuilder()
