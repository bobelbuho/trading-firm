"""
Indicateurs techniques — fonctions pures, sans état ni dépendance au bus.

Prennent en entrée une liste de bougies OHLC (dicts avec open/high/low/close),
pas de simples prix — nécessaire pour l'ADX qui a besoin de high/low.

Utilisées à la fois par MarketDataAgent (mode live/paper) et par le moteur
de backtesting, pour garantir que la stratégie voit exactement les mêmes
chiffres dans les deux contextes.
"""


def _closes(bars: list[dict]) -> list[float]:
    return [bar["close"] for bar in bars]


def sma(bars: list[dict], period: int) -> float:
    closes = _closes(bars)
    return sum(closes[-period:]) / period


def rsi(bars: list[dict], period: int = 14) -> float:
    closes = _closes(bars)
    deltas = [closes[i] - closes[i - 1] for i in range(len(closes) - period, len(closes))]
    gains = [d for d in deltas if d > 0]
    losses = [-d for d in deltas if d < 0]
    avg_gain = sum(gains) / period if gains else 0.0001
    avg_loss = sum(losses) / period if losses else 0.0001
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def volatility(bars: list[dict], period: int = 20) -> float:
    closes = _closes(bars)
    window = closes[-period:]
    mean = sum(window) / len(window)
    variance = sum((p - mean) ** 2 for p in window) / len(window)
    return variance ** 0.5


def compute_adx(bars: list[dict], period: int = 14) -> float | None:
    """ADX de Wilder — force de la tendance, indépendamment de sa direction.

    Nécessite au moins 2*period bougies: period valeurs de TR/+DM/-DM pour
    amorcer le lissage de Wilder, puis period valeurs de DX supplémentaires
    pour amorcer le lissage de l'ADX lui-même.
    """
    if len(bars) < 2 * period:
        return None

    trs, plus_dms, minus_dms = [], [], []
    for i in range(1, len(bars)):
        high, low = bars[i]["high"], bars[i]["low"]
        prev_high, prev_low, prev_close = bars[i - 1]["high"], bars[i - 1]["low"], bars[i - 1]["close"]

        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        up_move = high - prev_high
        down_move = prev_low - low

        plus_dm = up_move if (up_move > down_move and up_move > 0) else 0.0
        minus_dm = down_move if (down_move > up_move and down_move > 0) else 0.0

        trs.append(tr)
        plus_dms.append(plus_dm)
        minus_dms.append(minus_dm)

    def wilder_smooth(values: list[float]) -> list[float]:
        smoothed = [sum(values[:period])]
        for v in values[period:]:
            smoothed.append(smoothed[-1] - (smoothed[-1] / period) + v)
        return smoothed

    atr = wilder_smooth(trs)
    plus_dm_smooth = wilder_smooth(plus_dms)
    minus_dm_smooth = wilder_smooth(minus_dms)

    dx_values = []
    for a, pdm, mdm in zip(atr, plus_dm_smooth, minus_dm_smooth):
        if a == 0:
            dx_values.append(0.0)
            continue
        plus_di = 100 * (pdm / a)
        minus_di = 100 * (mdm / a)
        di_sum = plus_di + minus_di
        dx_values.append(100 * abs(plus_di - minus_di) / di_sum if di_sum > 0 else 0.0)

    if len(dx_values) < period:
        return None

    adx = sum(dx_values[:period]) / period
    for dx in dx_values[period:]:
        adx = (adx * (period - 1) + dx) / period

    return adx


def compute_indicators(bars: list[dict]) -> dict:
    if len(bars) < 14:
        return {}

    indicators = {
        "sma_10": sma(bars, 10),
        "sma_50": sma(bars, 50) if len(bars) >= 50 else None,
        "rsi_14": rsi(bars, 14),
        "volatility": volatility(bars, 20),
    }

    if len(bars) >= 20:
        bb_middle = sma(bars, 20)
        bb_std = volatility(bars, 20)
        bb_upper = bb_middle + 2 * bb_std
        bb_lower = bb_middle - 2 * bb_std
        band_width = bb_upper - bb_lower
        last_close = bars[-1]["close"]
        bb_pct = (last_close - bb_lower) / band_width if band_width > 0 else 0.5
        indicators.update({
            "bb_middle": bb_middle,
            "bb_upper": bb_upper,
            "bb_lower": bb_lower,
            "bb_pct": bb_pct,
        })

    indicators["adx_14"] = compute_adx(bars, 14) if len(bars) >= 28 else None

    return indicators
