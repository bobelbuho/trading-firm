"""
explore_gold_hourly.py — analyse EXPLORATOIRE (aucune décision de trading)
du biais directionnel horaire sur l'or, pour l'hypothèse
'gold_hourly_flow_bias'.

Charge l'historique GC=F (15m/60j), split train/test chronologique, et
verrouille IMMÉDIATEMENT le test set (data_split.lock_test_set() est appelé
avant toute analyse) — à partir de là, seul le train set est utilisé ici.

Sur le TRAIN uniquement: regroupe les bougies par heure UTC (0-23), calcule
le rendement moyen (close-open)/open par bougie, l'écart-type, le nombre
d'observations, et un t-stat (moyenne / (écart-type / sqrt(n))) pour juger
si le rendement moyen de chaque heure s'écarte significativement de zéro.

Chaque heure testée est comptée comme un essai auprès d'OverfittingGuard —
24 essais au total. Le budget par défaut (20) est volontairement dépassé:
tester 24 hypothèses simultanément sur du bruit potentiel augmente
mécaniquement le risque de "découvrir" un faux signal par hasard — c'est le
point même de la garde anti-p-hacking.

Usage: python research/explore_gold_hourly.py
"""

import logging
import math
import sys
from collections import defaultdict
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(name)s | %(message)s")

from backtesting.data_loader import fetch_multiple
from research.overfitting.guards import OverfittingGuard
from research.validation.data_split import DataSplit

SYMBOL = "XAU/USD"
HYPOTHESIS_ID = "gold_hourly_flow_bias"


def main() -> None:
    price_series = fetch_multiple([SYMBOL], interval="15m", period="60d")
    bars = price_series[SYMBOL]
    print(f"{SYMBOL}: {len(bars)} bougies récupérées (15m/60j).")

    data_split = DataSplit()
    train_data, test_data = data_split.split(price_series, test_ratio=0.2)
    data_split.lock_test_set()   # verrouillé immédiatement — le test set n'est PAS consulté ici
    print(
        f"Train: {len(train_data[SYMBOL])} bougies (explorées ci-dessous) | "
        f"Test: {len(test_data[SYMBOL])} bougies (verrouillées, non consultées)."
    )
    print()

    train_bars = train_data[SYMBOL]

    by_hour: dict[int, list[float]] = defaultdict(list)
    for bar in train_bars:
        hour = bar["timestamp"].hour   # timestamps déjà en UTC (voir backtesting/data_loader.py)
        ret_pct = (bar["close"] - bar["open"]) / bar["open"] * 100 if bar["open"] else 0.0
        by_hour[hour].append(ret_pct)

    guard = OverfittingGuard()
    rows = []
    for hour in range(24):
        returns = by_hour.get(hour, [])
        n = len(returns)
        guard.record_trial(HYPOTHESIS_ID)   # chaque heure testée = un essai

        if n < 2:
            rows.append((hour, 0.0, 0.0, n, 0.0))
            continue

        mean = sum(returns) / n
        variance = sum((r - mean) ** 2 for r in returns) / (n - 1)
        std = variance ** 0.5
        t_stat = mean / (std / math.sqrt(n)) if std > 0 else 0.0
        rows.append((hour, mean, std, n, t_stat))

    rows.sort(key=lambda row: abs(row[4]), reverse=True)

    print("=== Rendement moyen par heure UTC (TRAIN uniquement) — trié par |t-stat| décroissant ===")
    print(f"{'heure':>5s} {'rendement moyen %':>18s} {'écart-type %':>13s} {'n':>6s} {'t-stat':>8s}")
    for hour, mean, std, n, t_stat in rows:
        print(f"{hour:5d} {mean:18.4f} {std:13.4f} {n:6d} {t_stat:8.2f}")

    print()
    within_budget = guard.check_trial_budget(HYPOTHESIS_ID, max_trials=20)
    print(f"Essais enregistrés pour '{HYPOTHESIS_ID}': {guard.trials_count[HYPOTHESIS_ID]} (budget respecté: {within_budget})")


if __name__ == "__main__":
    main()
