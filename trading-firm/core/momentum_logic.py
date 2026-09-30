"""
momentum_logic.py — stratégie de suivi de tendance (momentum) par croisement
de moyennes mobiles. Approche OPPOSÉE au mean reversion de
core/strategy_logic.py: au lieu de parier sur un retour à la moyenne après un
excès de prix, on suit la tendance tant qu'elle dure.

Signal ACHAT: la MM rapide croise AU-DESSUS de la MM lente (golden cross).
Signal VENTE: la MM rapide croise EN DESSOUS de la MM lente (death cross).

Pas de suggested_take_profit fixe ici: en momentum, la sortie se fait au
croisement inverse des moyennes (voir backtesting/momentum_engine.py), pas à
un retour à une moyenne — la moyenne mobile lente EST la ligne de tendance
qu'on suit, pas un niveau de retour à atteindre.
"""

from core.indicators import sma


def generate_momentum_signal(bars: list[dict], fast_period: int = 20, slow_period: int = 50) -> dict | None:
    if len(bars) < slow_period + 1:
        return None

    fast_now = sma(bars, fast_period)
    slow_now = sma(bars, slow_period)
    fast_prev = sma(bars[:-1], fast_period)
    slow_prev = sma(bars[:-1], slow_period)

    crossed_up = fast_prev <= slow_prev and fast_now > slow_now
    crossed_down = fast_prev >= slow_prev and fast_now < slow_now

    if crossed_up:
        side = "buy"
    elif crossed_down:
        side = "sell"
    else:
        return None

    price = bars[-1]["close"]
    return {
        "side": side,
        "price": price,
        "reason": (
            f"Croisement MM{fast_period}/MM{slow_period} "
            f"{'haussier' if side == 'buy' else 'baissier'} "
            f"(MM{fast_period}={fast_now:.4f}, MM{slow_period}={slow_now:.4f})"
        ),
        "indicators": {"sma_fast": fast_now, "sma_slow": slow_now},
    }
