"""
Logique de risk management — fonctions pures, sans état ni dépendance au bus.

Utilisées à la fois par RiskManager (mode live/paper) et par le moteur de
backtesting, pour garantir que le sizing et les stops sont identiques dans
les deux contextes.
"""

from config.settings import RiskConfig


def compute_stop_distance_pct(price: float, volatility: float | None) -> float:
    return min(max((volatility / price) if volatility else 0.003, 0.001), 0.02)


def compute_position_size(signal: dict, capital: float, config: RiskConfig) -> float:
    """Position sizing basé sur le % de capital risqué et la distance au stop,
    plafonné par l'exposition notionnelle max autorisée sur un symbole."""
    risk_amount = capital * (config.max_risk_per_trade_pct / 100)
    price = signal["price"]

    volatility = signal.get("indicators", {}).get("volatility")
    stop_distance_pct = compute_stop_distance_pct(price, volatility)
    stop_distance = price * stop_distance_pct
    size = risk_amount / stop_distance if stop_distance > 0 else 0

    max_notional = capital * (config.max_exposure_per_symbol_pct / 100)
    size = min(size, max_notional / price)
    return round(size, 6)


def compute_stops(signal: dict, side: str, config: RiskConfig) -> tuple[float, float]:
    price = signal["price"]
    volatility = signal.get("indicators", {}).get("volatility")
    stop_distance_pct = compute_stop_distance_pct(price, volatility)
    stop_distance = price * stop_distance_pct
    rr = config.min_risk_reward_ratio

    if side == "buy":
        stop_loss = price - stop_distance
        default_take_profit = price + stop_distance * rr
    else:
        stop_loss = price + stop_distance
        default_take_profit = price - stop_distance * rr

    suggested = signal.get("suggested_take_profit")
    if suggested is not None and stop_distance > 0:
        correct_direction = (side == "buy" and suggested > price) or (side == "sell" and suggested < price)
        reward = abs(suggested - price)
        if correct_direction and (reward / stop_distance) >= rr:
            return stop_loss, suggested

    return stop_loss, default_take_profit
