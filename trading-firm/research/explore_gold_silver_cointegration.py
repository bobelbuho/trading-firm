"""
explore_gold_silver_cointegration.py — explore si l'or (XAU/USD) et l'argent
(XAG/USD) sont cointégrés, AVANT toute construction de stratégie ou
extension du moteur. Horizon swing (bougies journalières, 2 ans).

Discipline train/test stricte: tout se calcule sur le TRAIN uniquement
(régression, tests de cointégration, z-score, demi-vie), sauf l'étape 6 qui
déverrouille UNE SEULE FOIS le test set pour vérifier que la relation tient
hors échantillon — le test décisif contre la cointégration fantôme (une
relation qui a l'air stationnaire sur une fenêtre mais qui n'est qu'un
artefact de cette fenêtre précise).

Ne construit AUCUNE stratégie et n'étend PAS le moteur de backtest — c'est
une exploration statistique pure, qui se conclut par un verdict GO/NO-GO sur
la seule question: "est-ce que ça vaut le coup de construire un moteur de
trading de paires ?"

Usage: python research/explore_gold_silver_cointegration.py
"""

import logging
import math
import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(name)s | %(message)s")

import statsmodels.api as sm
from statsmodels.tsa.stattools import adfuller, coint

from backtesting.data_loader import fetch_multiple
from research.validation.data_split import DataSplit

GOLD, SILVER = "XAU/USD", "XAG/USD"
Z_ENTRY_THRESHOLD = 2.0
Z_REVERSION_THRESHOLD = 0.5
REVERSION_HORIZONS = (5, 10, 20)

MAX_BETA_DRIFT_PCT = 30.0
MAX_HALF_LIFE_DAYS = 30.0
MIN_REVERSION_RATE_20D_PCT = 50.0


def align_by_date(series_a: list[dict], series_b: list[dict]) -> tuple[list[dict], list[dict]]:
    """Ne garde que les dates où on a un prix pour les deux séries — l'or et
    l'argent peuvent avoir des trous différents (jours fériés, maintenance)."""
    by_date_a = {bar["timestamp"].date(): bar for bar in series_a}
    by_date_b = {bar["timestamp"].date(): bar for bar in series_b}
    common_dates = sorted(set(by_date_a) & set(by_date_b))
    return [by_date_a[d] for d in common_dates], [by_date_b[d] for d in common_dates]


def closes(bars: list[dict]) -> list[float]:
    return [bar["close"] for bar in bars]


def fit_hedge_ratio(gold_closes: list[float], silver_closes: list[float]) -> tuple[float, float]:
    """OLS: prix_or = beta * prix_argent + alpha. Retourne (beta, alpha)."""
    X = sm.add_constant(silver_closes)
    model = sm.OLS(gold_closes, X).fit()
    alpha, beta = model.params[0], model.params[1]
    return beta, alpha


def build_spread(gold_closes: list[float], silver_closes: list[float], beta: float, alpha: float) -> list[float]:
    return [g - (beta * s + alpha) for g, s in zip(gold_closes, silver_closes)]


def describe(values: list[float]) -> dict:
    n = len(values)
    mean = sum(values) / n
    variance = sum((v - mean) ** 2 for v in values) / (n - 1)
    return {"mean": mean, "std": variance ** 0.5, "min": min(values), "max": max(values), "n": n}


def half_life(spread: list[float]) -> float | None:
    """Demi-vie du retour à la moyenne via régression AR(1):
    delta_spread[t] = lambda * spread[t-1] + const. half_life = -ln(2)/lambda
    (en jours). None si lambda >= 0 (pas de retour à la moyenne détectable)."""
    lagged = spread[:-1]
    delta = [spread[i] - spread[i - 1] for i in range(1, len(spread))]
    model = sm.OLS(delta, sm.add_constant(lagged)).fit()
    lam = model.params[1]
    return -math.log(2) / lam if lam < 0 else None


def analyze_zscore(spread: list[float], mean: float, std: float) -> dict:
    z = [(s - mean) / std for s in spread]

    entries = []
    for i in range(1, len(z)):
        if z[i] > Z_ENTRY_THRESHOLD and z[i - 1] <= Z_ENTRY_THRESHOLD:
            entries.append((i, "above"))
        elif z[i] < -Z_ENTRY_THRESHOLD and z[i - 1] >= -Z_ENTRY_THRESHOLD:
            entries.append((i, "below"))

    reversion_rates = {}
    for horizon in REVERSION_HORIZONS:
        if not entries:
            reversion_rates[horizon] = 0.0
            continue
        reverted = sum(
            1 for i, _ in entries
            if any(abs(val) <= Z_REVERSION_THRESHOLD for val in z[i + 1:i + 1 + horizon])
        )
        reversion_rates[horizon] = reverted / len(entries) * 100

    return {
        "n_entries_above": sum(1 for _, side in entries if side == "above"),
        "n_entries_below": sum(1 for _, side in entries if side == "below"),
        "n_entries_total": len(entries),
        "reversion_rates_pct": reversion_rates,
    }


def print_section(title: str) -> None:
    print()
    print(f"=== {title} ===")


def main() -> None:
    # --- 1. Chargement + alignement ---
    print_section("1. Chargement des données (daily, 2 ans)")
    price_series = fetch_multiple([GOLD, SILVER], interval="1d", period="2y")
    gold_raw, silver_raw = price_series[GOLD], price_series[SILVER]
    print(f"{GOLD}: {len(gold_raw)} bougies brutes | {SILVER}: {len(silver_raw)} bougies brutes")

    gold_aligned, silver_aligned = align_by_date(gold_raw, silver_raw)
    print(f"Après alignement sur dates communes: {len(gold_aligned)} bougies pour chaque série")

    # --- 2. Split train/test verrouillé ---
    print_section("2. Split train/test")
    data_split = DataSplit()
    train_data, _ = data_split.split({GOLD: gold_aligned, SILVER: silver_aligned}, test_ratio=0.2)
    data_split.lock_test_set()
    gold_train, silver_train = train_data[GOLD], train_data[SILVER]
    print(f"Train: {len(gold_train)} bougies | Test: verrouillé, non consulté pour l'instant")

    gold_train_closes, silver_train_closes = closes(gold_train), closes(silver_train)

    # --- 3. Hedge ratio + spread (train) ---
    print_section("3. Hedge ratio et spread (TRAIN)")
    beta, alpha = fit_hedge_ratio(gold_train_closes, silver_train_closes)
    spread_train = build_spread(gold_train_closes, silver_train_closes, beta, alpha)
    stats_train = describe(spread_train)
    print(f"beta (hedge ratio) = {beta:.4f}")
    print(f"alpha              = {alpha:.4f}")
    print(
        f"spread train: mean={stats_train['mean']:.4f} std={stats_train['std']:.4f} "
        f"min={stats_train['min']:.4f} max={stats_train['max']:.4f} (n={stats_train['n']})"
    )

    # --- 4. Tests de cointégration (train) ---
    print_section("4. Tests de cointégration (TRAIN)")
    eg_stat, eg_pvalue, _ = coint(gold_train_closes, silver_train_closes)
    print(
        f"Engle-Granger:     statistique={eg_stat:.4f}  p-value={eg_pvalue:.4f}  -> "
        f"{'cointégration probable' if eg_pvalue < 0.05 else 'PAS de cointégration fiable'}"
    )

    adf_result = adfuller(spread_train)
    adf_stat, adf_pvalue = adf_result[0], adf_result[1]
    print(
        f"ADF sur le spread: statistique={adf_stat:.4f}  p-value={adf_pvalue:.4f}  -> "
        f"{'spread stationnaire (exploitable)' if adf_pvalue < 0.05 else 'spread NON stationnaire'}"
    )

    # --- 5. Z-score et retour à la moyenne (train) ---
    print_section("5. Analyse du z-score et retour à la moyenne (TRAIN)")
    zscore_stats = analyze_zscore(spread_train, stats_train["mean"], stats_train["std"])
    print(
        f"Dépassements |z|>{Z_ENTRY_THRESHOLD:.0f}: {zscore_stats['n_entries_total']} "
        f"(above +{Z_ENTRY_THRESHOLD:.0f}: {zscore_stats['n_entries_above']}, "
        f"below -{Z_ENTRY_THRESHOLD:.0f}: {zscore_stats['n_entries_below']})"
    )
    for horizon, rate in zscore_stats["reversion_rates_pct"].items():
        print(f"  Retour vers 0 (|z|<={Z_REVERSION_THRESHOLD}) dans les {horizon} jours suivants: {rate:.1f}%")

    hl = half_life(spread_train)
    print(
        f"Demi-vie du retour à la moyenne (AR(1)): "
        f"{f'{hl:.1f} jours' if hl is not None else 'non détectable (pas de retour à la moyenne)'}"
    )

    # --- 6. Vérification sur le test set (déverrouillage UNIQUE) ---
    print_section("6. Vérification de stabilité sur le TEST SET (accès unique)")
    test_data = data_split.get_test_set()   # loggé/tracé via DataSplit
    gold_test_closes, silver_test_closes = closes(test_data[GOLD]), closes(test_data[SILVER])
    print(f"Test: {len(gold_test_closes)} bougies")

    spread_test = build_spread(gold_test_closes, silver_test_closes, beta, alpha)
    adf_test_result = adfuller(spread_test)
    adf_test_stat, adf_test_pvalue = adf_test_result[0], adf_test_result[1]
    print(
        f"ADF sur le spread test (même beta/alpha que le train): "
        f"statistique={adf_test_stat:.4f}  p-value={adf_test_pvalue:.4f}  -> "
        f"{'tient hors échantillon' if adf_test_pvalue < 0.05 else 'NE tient PAS hors échantillon'}"
    )

    beta_test, alpha_test = fit_hedge_ratio(gold_test_closes, silver_test_closes)
    beta_drift_pct = abs(beta_test - beta) / abs(beta) * 100 if beta else float("inf")
    print(f"Beta recalculé sur test: {beta_test:.4f} (train: {beta:.4f}) -> dérive={beta_drift_pct:.1f}%")

    # --- 7. Verdict ---
    print_section("7. Verdict")
    train_cointegrated = eg_pvalue < 0.05 and adf_pvalue < 0.05
    test_holds = adf_test_pvalue < 0.05
    beta_stable = beta_drift_pct < MAX_BETA_DRIFT_PCT
    tradable_speed = (
        hl is not None and hl <= MAX_HALF_LIFE_DAYS
        and zscore_stats["reversion_rates_pct"][20] >= MIN_REVERSION_RATE_20D_PCT
    )

    print(
        f"Cointégrée sur train ?       {'OUI' if train_cointegrated else 'NON'} "
        f"(Engle-Granger p={eg_pvalue:.4f}, ADF spread p={adf_pvalue:.4f})"
    )
    print(f"Tient sur test ?             {'OUI' if test_holds else 'NON'} (ADF spread test p={adf_test_pvalue:.4f})")
    print(
        f"Beta stable train->test ?    {'OUI' if beta_stable else 'NON'} "
        f"(dérive={beta_drift_pct:.1f}%, seuil {MAX_BETA_DRIFT_PCT:.0f}%)"
    )
    print(
        f"Retour à la moyenne rapide ? {'OUI' if tradable_speed else 'NON'} "
        f"(demi-vie={f'{hl:.1f}j' if hl else 'N/A'}, "
        f"retour 20j={zscore_stats['reversion_rates_pct'][20]:.1f}%, seuil {MIN_REVERSION_RATE_20D_PCT:.0f}%)"
    )

    go = train_cointegrated and test_holds and beta_stable and tradable_speed
    print()
    print(
        "VERDICT: "
        + ("GO — ça vaut le coup de construire un moteur de trading de paires"
           if go else
           "NO-GO — cointégration absente ou instable, ne pas construire de stratégie dessus")
    )


if __name__ == "__main__":
    main()
