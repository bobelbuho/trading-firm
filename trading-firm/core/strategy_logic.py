"""
Logique de décision de la stratégie — fonction pure, sans état ni dépendance
au bus. Mean reversion par confluence Bollinger + RSI : un signal n'est émis
que si le prix sort des bandes de Bollinger ET que le RSI confirme l'excès
(survente/surachat). L'ADX filtre les marchés en tendance trop forte, où le
mean reversion n'a pas de sens. La cible de sortie proposée est le retour
à la moyenne (bb_middle).

Utilisée à la fois par StrategyAgent (mode live/paper) et par le moteur de
backtesting.
"""


def generate_signal(
    price: float,
    indicators: dict,
    rsi_oversold: float = 35,
    rsi_overbought: float = 65,
    adx_max: float = 25.0,
) -> dict | None:
    if not indicators:
        return None

    adx = indicators.get("adx_14")
    if adx is not None and adx >= adx_max:
        return None  # tendance trop forte pour du mean reversion

    rsi = indicators.get("rsi_14")
    bb_lower = indicators.get("bb_lower")
    bb_upper = indicators.get("bb_upper")
    bb_middle = indicators.get("bb_middle")
    if rsi is None or bb_lower is None or bb_upper is None or bb_middle is None:
        return None

    side = None
    if price <= bb_lower and rsi < rsi_oversold:
        side = "buy"
    elif price >= bb_upper and rsi > rsi_overbought:
        side = "sell"

    if side is None:
        return None

    adx_label = f"{adx:.1f} (range)" if adx is not None else "n/a"

    return {
        "side": side,
        "price": price,
        "confidence": _compute_confidence(price, rsi, bb_lower, bb_upper, side),
        "reason": f"RSI={rsi:.1f}, ADX={adx_label}, prix hors bande de Bollinger",
        "suggested_take_profit": bb_middle,
        "indicators": indicators,
    }


def _compute_confidence(price: float, rsi: float, bb_lower: float, bb_upper: float, side: str) -> float:
    """Combine la distance aux bandes et la distance du RSI à 50 (neutre)."""
    half_width = (bb_upper - bb_lower) / 2
    if side == "buy":
        band_component = (bb_lower - price) / half_width if half_width > 0 else 0.0
    else:
        band_component = (price - bb_upper) / half_width if half_width > 0 else 0.0
    band_component = min(max(band_component, 0.0), 1.0)

    rsi_component = min(max(abs(50 - rsi) / 50, 0.0), 1.0)

    return round((band_component + rsi_component) / 2, 4)
