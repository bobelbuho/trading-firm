"""
validate_eurgbp_daily.py — soumet l'hypothèse "mean reversion EUR/GBP daily"
(observée à PF 1.16 avec spread en backtest simple, hors processus de
validation) au pipeline de validation COMPLET (6 stages), pour déterminer si
c'est un edge réel ou du bruit/cherry-picking.

Usage: python research/validate_eurgbp_daily.py
"""

import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backtesting.data_loader import fetch_multiple
from config.settings import FirmConfig
from research.hypotheses.graveyard import Graveyard
from research.hypotheses.hypothesis import Hypothesis, Statut
from research.hypotheses.registry import HypothesisRegistry
from research.reports.research_log import ResearchLog
from research.validation.data_split import DataSplit
from research.validation.pipeline import ValidationPipeline

SYMBOL = "EUR/GBP"
HYPOTHESIS_ID = "eurgbp_daily_meanrev"

# Paramètres voisins pour le stage de robustesse paramétrique (stage 3):
# RSI 33/67 et 37/63 (au lieu de 35/65), ADX max 22 et 28 (au lieu de 25).
PARAM_VARIATIONS = [
    {"rsi_oversold": 33, "rsi_overbought": 67},
    {"rsi_oversold": 37, "rsi_overbought": 63},
    {"adx_max": 22.0},
    {"adx_max": 28.0},
]

# ~28 ans d'historique daily sur EUR/GBP -> des fenêtres de 365 jours donnent
# ~22 sous-fenêtres sur le train (80%), un nombre raisonnable pour juger la
# stabilité temporelle sans les rendre trop petites pour être significatives.
WINDOW_DAYS = 365


def build_hypothesis() -> Hypothesis:
    return Hypothesis(
        id=HYPOTHESIS_ID,
        nom="Mean reversion Bollinger+RSI+ADX sur EUR/GBP daily",
        raison=(
            "EUR/GBP est une paire à faible tendance (économies UK/zone euro "
            "très liées) où le prix oscille en range, terrain théoriquement "
            "favorable au mean reversion. Observé PF 1.16 avec spread en "
            "backtest simple."
        ),
        prediction=(
            "Si l'edge est réel, il doit persister sur données out-of-sample "
            "jamais regardées, et être cohérent sur la majorité des "
            "sous-périodes."
        ),
        criteres_echec={
            "profit_factor_min": 1.2,
            "coherence_min": 60.0,
            "doit_persister_sur_test_set": True,
        },
        donnees_test="20% les plus récents d'EUR/GBP daily, verrouillés",
    )


def main() -> None:
    log = ResearchLog()
    registry = HypothesisRegistry(research_log=log)
    graveyard = Graveyard(research_log=log)

    # --- 1. Enregistrement ---
    hypothesis = build_hypothesis()
    registry.register(hypothesis)
    print(f"Hypothèse '{hypothesis.id}' enregistrée (statut: {hypothesis.statut.value}).")

    # --- 2. Données + split verrouillé immédiatement ---
    print()
    print("=== Chargement des données EUR/GBP (daily, période max) ===")
    price_series = fetch_multiple([SYMBOL], interval="1d", period="max")
    print(f"{SYMBOL}: {len(price_series[SYMBOL])} bougies récupérées.")

    data_split = DataSplit()
    train_data, test_data = data_split.split(price_series, test_ratio=0.2)
    data_split.lock_test_set()   # verrouillé immédiatement, avant toute exécution du pipeline
    print(f"Train: {len(train_data[SYMBOL])} bougies | Test: {len(test_data[SYMBOL])} bougies (verrouillées)")

    config = FirmConfig.default()

    # --- 3. Pipeline de validation complet (6 stages) ---
    print()
    print("=== Exécution du pipeline de validation (6 stages, arrêt au premier échec) ===")
    pipeline = ValidationPipeline(research_log=log)
    report = pipeline.validate(
        hypothesis=hypothesis,
        data_split=data_split,
        risk_config=config.risk,
        starting_capital=config.starting_capital,
        spread_cost_pct=0.0002,
        param_variations=PARAM_VARIATIONS,
        window_days=WINDOW_DAYS,
    )

    # --- 4. Rapport complet + verdict ---
    print()
    print(report.summary())

    print()
    print("=== Application du verdict ===")
    if report.passed:
        registry.update_statut(HYPOTHESIS_ID, Statut.VALIDEE)
        print(f"Hypothèse '{HYPOTHESIS_ID}' -> VALIDEE.")
    else:
        registry.update_statut(HYPOTHESIS_ID, Statut.REJETEE)
        metriques_finales = report.stages[-1].metrics
        graveyard.bury(hypothesis, report.recommended_raison, metriques_finales)
        print(f"Hypothèse '{HYPOTHESIS_ID}' -> REJETEE et enterrée.")
        print(f"Raison: {report.recommended_raison}")


if __name__ == "__main__":
    main()
