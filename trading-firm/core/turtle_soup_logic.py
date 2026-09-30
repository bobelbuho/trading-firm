"""
turtle_soup_logic.py — stratégie "Turtle Soup" (faux breakout / chasse aux
stops), en règles STRICTEMENT objectives, sans aucun jugement subjectif.

Signal VENTE (faux breakout haussier): le HIGH de la bougie courante dépasse
le plus haut des `lookback` bougies précédentes (bougie courante EXCLUE),
MAIS sa CLÔTURE repasse en dessous de ce niveau de référence — le breakout
est "faux", les acheteurs qui ont chassé les stops au-dessus se retrouvent
piégés. Entrée: SELL à l'ouverture de la bougie SUIVANTE (le délai d'un bar
est géré par backtesting/turtle_soup_engine.py, pas ici). Stop-loss: au-
dessus du HIGH de la bougie de faux breakout (niveau fixe). Take-profit:
ratio risque/récompense fixe (rr) depuis la clôture de la bougie de signal.

Signal ACHAT (faux breakout baissier): l'exact miroir sur le LOW/plus bas.
"""


def generate_turtle_soup_signal(bars: list[dict], lookback: int = 20, rr: float = 2.0) -> dict | None:
    if len(bars) < lookback + 1:
        return None

    reference_bars = bars[-(lookback + 1):-1]   # lookback bougies précédentes, bougie courante exclue
    current = bars[-1]
    price = current["close"]

    reference_high = max(bar["high"] for bar in reference_bars)
    reference_low = min(bar["low"] for bar in reference_bars)

    if current["high"] > reference_high and current["close"] < reference_high:
        side = "sell"
        stop_loss = current["high"]
        stop_distance = stop_loss - price
        take_profit = price - rr * stop_distance
        reason = (
            f"Faux breakout haussier: high={current['high']:.4f} > référence={reference_high:.4f} "
            f"sur {lookback} bougies, mais clôture={price:.4f} repasse en dessous (piège à acheteurs)"
        )
    elif current["low"] < reference_low and current["close"] > reference_low:
        side = "buy"
        stop_loss = current["low"]
        stop_distance = price - stop_loss
        take_profit = price + rr * stop_distance
        reason = (
            f"Faux breakout baissier: low={current['low']:.4f} < référence={reference_low:.4f} "
            f"sur {lookback} bougies, mais clôture={price:.4f} repasse au-dessus (piège à vendeurs)"
        )
    else:
        return None

    return {
        "side": side,
        "price": price,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "reason": reason,
    }
