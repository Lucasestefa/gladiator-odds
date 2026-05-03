"""
BetScan — Alpaca Fee Engine
============================
Calcula todos los costos reales de operar con Alpaca Markets
para que el P&L del bot refleje ganancia neta real.

Fuente: https://alpaca.markets/disclosures/library/BrokFeeSched.pdf
        https://docs.alpaca.markets/docs/crypto-fees
        Actualizado: Mayo 2026

Estructura de costos:
  STOCKS / ETFs USA:
    Comisión Alpaca:  $0.00 (commission-free)
    SEC fee (ventas): $5.10 por $1,000,000 → 0.00000510 por dólar vendido
    FINRA TAF (ventas): $0.000119 por acción, máx $5.95 por orden
    Clearing:         $0.00 (Alpaca cubre)

  CRYPTO:
    Taker (market orders): 0.25% del valor del trade
    Maker (limit orders):  0.15% del valor del trade
    El bot usa market orders → 0.25%

  FOREX:
    Spread implícito: ~0.01% a 0.05% (via AlphaVantage mock)
    Comisión directa: $0.00

  RETIROS BANCARIOS:
    ACH:               $0.00
    Wire doméstico:    $25.00
    Wire internacional: $50.00

  MARGEN (si se usa):
    Tasa APR: 6.25%
    Daily: 6.25% / 365 = 0.01712% por día
"""


# ================================================================
# CONSTANTES — Alpaca Fee Schedule (Mayo 2026)
# ================================================================

# SEC Transaction Fee (solo en ventas de acciones/ETFs)
SEC_FEE_RATE = 5.10 / 1_000_000   # $5.10 por cada $1,000,000 vendido

# FINRA Trading Activity Fee (solo en ventas de acciones/ETFs)
FINRA_TAF_PER_SHARE = 0.000119    # $0.000119 por acción
FINRA_TAF_MAX        = 5.95       # máximo $5.95 por orden

# Crypto fees (Alpaca Exchange)
CRYPTO_TAKER_FEE = 0.0025  # 0.25% para market orders (taker)
CRYPTO_MAKER_FEE = 0.0015  # 0.15% para limit orders (maker)

# Retiros bancarios
ACH_WITHDRAWAL_FEE               = 0.00   # gratis
WIRE_DOMESTIC_FEE                = 25.00  # $25 USD
WIRE_INTERNATIONAL_FEE           = 50.00  # $50 USD

# Margen
MARGIN_APR        = 0.0625               # 6.25% anual
MARGIN_DAILY_RATE = MARGIN_APR / 365     # ~0.01712% diario

# ACH reversal (fondos insuficientes, etc.)
ACH_REVERSAL_FEE = 30.00  # $30 por reversal


# ================================================================
# ALPACA FEE ENGINE
# ================================================================

class AlpacaFeeEngine:
    """
    Calcula todos los fees de Alpaca para cada operación.
    Se integra en el Portfolio del bot para que el P&L sea real.

    Uso:
        engine = AlpacaFeeEngine()

        # Compra de stocks
        cost = engine.calculate_buy_fees("AAPL", price=195.0, qty=10, asset_type="stock")

        # Venta de stocks
        cost = engine.calculate_sell_fees("AAPL", price=200.0, qty=10, asset_type="stock")

        # Compra de crypto
        cost = engine.calculate_buy_fees("BTC", price=95000, qty=0.05, asset_type="crypto")
    """

    def __init__(self):
        self.total_fees_paid  = 0.0
        self.fee_log: list    = []

    def calculate_buy_fees(
        self,
        symbol:     str,
        price:      float,
        qty:        float,
        asset_type: str = "stock",  # "stock", "crypto", "forex"
        order_type: str = "market", # "market" (taker) o "limit" (maker)
    ) -> dict:
        """
        Calcula los fees al COMPRAR un activo.

        Stocks/ETFs: $0 comisión en compras.
        Crypto:      0.25% taker / 0.15% maker sobre el valor de la orden.
        Forex:       $0 directo (spread implícito ya en el precio).
        """
        trade_value = price * qty
        fees = {}

        if asset_type == "stock":
            # Alpaca es commission-free en compras de acciones
            fees["commission"] = 0.0
            fees["sec_fee"]    = 0.0   # solo en ventas
            fees["finra_taf"]  = 0.0   # solo en ventas
            fees["total"]      = 0.0

        elif asset_type == "crypto":
            fee_rate = CRYPTO_TAKER_FEE if order_type == "market" else CRYPTO_MAKER_FEE
            crypto_fee = trade_value * fee_rate
            fees["commission"] = round(crypto_fee, 6)
            fees["fee_rate"]   = fee_rate
            fees["total"]      = round(crypto_fee, 6)

        elif asset_type == "forex":
            fees["commission"] = 0.0
            fees["total"]      = 0.0

        fees["side"]        = "BUY"
        fees["symbol"]      = symbol
        fees["price"]       = price
        fees["qty"]         = qty
        fees["trade_value"] = round(trade_value, 4)
        fees["asset_type"]  = asset_type

        self._log_fee(fees)
        return fees

    def calculate_sell_fees(
        self,
        symbol:     str,
        price:      float,
        qty:        float,
        asset_type: str = "stock",
        order_type: str = "market",
        shares:     float = None,  # para FINRA TAF en stocks
    ) -> dict:
        """
        Calcula los fees al VENDER un activo.

        Stocks/ETFs:
          - SEC fee: $5.10 por $1,000,000 vendido
          - FINRA TAF: $0.000119 por acción (máx $5.95)

        Crypto:
          - 0.25% taker / 0.15% maker

        Forex:
          - $0 directo
        """
        trade_value  = price * qty
        shares_count = shares if shares is not None else qty

        fees = {}

        if asset_type == "stock":
            sec_fee   = round(trade_value * SEC_FEE_RATE, 6)
            finra_taf = round(min(shares_count * FINRA_TAF_PER_SHARE, FINRA_TAF_MAX), 6)
            total     = round(sec_fee + finra_taf, 6)
            fees["commission"] = 0.0
            fees["sec_fee"]    = sec_fee
            fees["finra_taf"]  = finra_taf
            fees["total"]      = total

        elif asset_type == "crypto":
            fee_rate   = CRYPTO_TAKER_FEE if order_type == "market" else CRYPTO_MAKER_FEE
            crypto_fee = round(trade_value * fee_rate, 6)
            fees["commission"] = crypto_fee
            fees["fee_rate"]   = fee_rate
            fees["total"]      = crypto_fee

        elif asset_type == "forex":
            fees["commission"] = 0.0
            fees["total"]      = 0.0

        fees["side"]        = "SELL"
        fees["symbol"]      = symbol
        fees["price"]       = price
        fees["qty"]         = qty
        fees["trade_value"] = round(trade_value, 4)
        fees["asset_type"]  = asset_type

        self._log_fee(fees)
        return fees

    def calculate_withdrawal_fee(self, method: str = "ach") -> float:
        """
        Calcula el costo de retirar fondos a una cuenta bancaria.

        method: "ach" | "wire_domestic" | "wire_international"
        """
        method = method.lower()
        if method == "ach":
            fee = ACH_WITHDRAWAL_FEE
        elif method == "wire_domestic":
            fee = WIRE_DOMESTIC_FEE
        elif method == "wire_international":
            fee = WIRE_INTERNATIONAL_FEE
        else:
            fee = ACH_WITHDRAWAL_FEE

        self.total_fees_paid += fee
        return fee

    def calculate_margin_fee(self, borrowed: float, days: int = 1) -> float:
        """
        Calcula el costo de usar margen.
        borrowed: monto prestado en USD
        days:     días que se mantuvo el margen
        """
        daily_cost = borrowed * MARGIN_DAILY_RATE * days
        return round(daily_cost, 4)

    def estimate_round_trip_cost(
        self,
        symbol:     str,
        price:      float,
        qty:        float,
        asset_type: str = "stock",
    ) -> dict:
        """
        Estima el costo total de una operación completa (compra + venta).
        Útil para calcular el break-even point antes de ejecutar.

        Returns:
            total_cost:    costo total en USD
            pct_of_trade:  % del valor de la operación
            break_even:    precio al que hay que vender para no perder
        """
        trade_value = price * qty
        buy_fees    = self.calculate_buy_fees(symbol, price, qty, asset_type)
        sell_fees   = self.calculate_sell_fees(symbol, price, qty, asset_type)

        total_cost  = buy_fees["total"] + sell_fees["total"]
        pct         = (total_cost / trade_value * 100) if trade_value > 0 else 0

        # Precio mínimo de venta para cubrir fees
        break_even  = price + (total_cost / qty) if qty > 0 else price

        return {
            "symbol":        symbol,
            "asset_type":    asset_type,
            "trade_value":   round(trade_value, 2),
            "buy_fees":      buy_fees["total"],
            "sell_fees":     sell_fees["total"],
            "total_cost":    round(total_cost, 6),
            "pct_of_trade":  round(pct, 4),
            "break_even":    round(break_even, 6),
            "note":          f"Necesitás que suba {round(pct, 4)}% para cubrir fees",
        }

    def get_summary(self) -> dict:
        """Resumen de todos los fees pagados en la sesión"""
        by_type   = {}
        total_sec = total_finra = total_crypto = 0.0

        for f in self.fee_log:
            atype = f.get("asset_type", "unknown")
            by_type[atype] = by_type.get(atype, 0) + f.get("total", 0)
            total_sec    += f.get("sec_fee", 0)
            total_finra  += f.get("finra_taf", 0)
            total_crypto += f.get("commission", 0) if atype == "crypto" else 0

        return {
            "total_fees_usd":   round(self.total_fees_paid, 4),
            "by_asset_type":    {k: round(v, 4) for k, v in by_type.items()},
            "sec_fees_total":   round(total_sec, 4),
            "finra_fees_total": round(total_finra, 4),
            "crypto_fees_total":round(total_crypto, 4),
            "operations_count": len(self.fee_log),
        }

    def _log_fee(self, fee_data: dict):
        total = fee_data.get("total", 0)
        self.total_fees_paid += total
        self.fee_log.append({**fee_data, "timestamp": __import__("datetime").datetime.now().isoformat()})


# ================================================================
# INTEGRACIÓN EN PORTFOLIO — patch para open/close_position
# ================================================================
"""
Para integrar en trading_bot.py, reemplazar los métodos
open_position y close_position del Portfolio por estos:

En __init__ del Portfolio agregar:
    from app.alpaca_fees import AlpacaFeeEngine
    self.fee_engine = AlpacaFeeEngine()
    self.total_fees_paid = 0.0

En open_position, después de calcular qty:
    fee_data = self.fee_engine.calculate_buy_fees(
        symbol=symbol, price=price, qty=qty,
        asset_type="crypto" if "/" not in symbol and len(symbol) <= 5 else "stock"
    )
    allocation += fee_data["total"]   # fee descontado del capital
    self.total_fees_paid += fee_data["total"]

En close_position, antes de calcular pnl:
    fee_data = self.fee_engine.calculate_sell_fees(
        symbol=symbol, price=price, qty=pos["qty"],
        asset_type="crypto" if "/" not in symbol and len(symbol) <= 5 else "stock"
    )
    proceeds -= fee_data["total"]    # fee descontado de los proceeds
    self.total_fees_paid += fee_data["total"]

En get_summary() agregar:
    "fees_pagados":     round(self.total_fees_paid, 4),
    "fee_breakdown":    self.fee_engine.get_summary(),
"""


# ================================================================
# UTILIDADES — cálculos rápidos para el dashboard
# ================================================================

def estimate_withdrawal_cost(amount: float, method: str = "wire_international") -> dict:
    """
    ¿Cuánto llega a tu cuenta si retirás $X de Alpaca?

    Ejemplo:
        estimate_withdrawal_cost(10000, "wire_international")
        → {"gross": 10000, "fee": 50, "net": 9950, "fee_pct": 0.5}
    """
    fees = {
        "ach":               ACH_WITHDRAWAL_FEE,
        "wire_domestic":     WIRE_DOMESTIC_FEE,
        "wire_international":WIRE_INTERNATIONAL_FEE,
    }
    fee = fees.get(method.lower(), ACH_WITHDRAWAL_FEE)
    net = amount - fee
    return {
        "gross":   amount,
        "method":  method,
        "fee":     fee,
        "net":     round(net, 2),
        "fee_pct": round(fee / amount * 100, 4) if amount > 0 else 0,
    }


def estimate_annual_trading_cost(
    trades_per_year:    int   = 500,
    avg_trade_value:    float = 5000.0,
    crypto_pct:         float = 0.40,  # 40% crypto, 60% stocks
) -> dict:
    """
    Proyección anual de fees según frecuencia y volumen de trading.
    Útil para evaluar si el bot es rentable neto de costos.
    """
    engine = AlpacaFeeEngine()

    stock_trades  = int(trades_per_year * (1 - crypto_pct))
    crypto_trades = int(trades_per_year * crypto_pct)
    avg_price     = avg_trade_value / 10  # asume qty ~10

    # Stocks: SEC + FINRA en ventas (la mitad de los trades)
    stock_sell_cost = 0.0
    for _ in range(stock_trades // 2):
        f = engine.calculate_sell_fees("STOCK", avg_price, 10, "stock", shares=10)
        stock_sell_cost += f["total"]

    # Crypto: 0.25% en cada trade (compra y venta)
    crypto_cost = 0.0
    for _ in range(crypto_trades):
        fb = engine.calculate_buy_fees("CRYPTO", avg_price, 1, "crypto")
        fs = engine.calculate_sell_fees("CRYPTO", avg_price * 1.05, 1, "crypto")
        crypto_cost += fb["total"] + fs["total"]

    total = stock_sell_cost + crypto_cost

    return {
        "trades_por_año":      trades_per_year,
        "valor_promedio":      avg_trade_value,
        "stock_trades":        stock_trades,
        "crypto_trades":       crypto_trades,
        "costo_stocks_usd":    round(stock_sell_cost, 2),
        "costo_crypto_usd":    round(crypto_cost, 2),
        "costo_total_anual":   round(total, 2),
        "costo_por_trade":     round(total / trades_per_year, 4),
        "pct_del_capital_50k": round(total / 50000 * 100, 4),
        "nota": "Stocks casi gratis. Crypto es el costo principal vía 0.25% taker fee."
    }


# ================================================================
# INSTANCIA GLOBAL
# ================================================================

fee_engine = AlpacaFeeEngine()
