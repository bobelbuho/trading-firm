"""
validate_turtle_soup.py — soumet les deux candidats Turtle Soup retenus par
l'exploration (research/backtest_turtle_soup.py) au pipeline de validation
COMPLET (6 stages):
  - EUR/USD daily RR 1:1 (candidat principal, PF=1.25 en exploration)
  - XAU/USD daily RR 1:2 (candidat secondaire, PF=1.09 en exploration)

Le stage 3 (robustesse paramétrique) teste des lookback voisins (15/25/30,
au lieu de 20) ET des RR voisins spécifiques à chaque hypothèse — un edge
réel ne doit pas s'effondrer pour un réglage légèrement différent.

Usage: python research/validate_turtle_soup.py
"""

import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backtesting.data_loader import fetch_multiple
from backtesting.turtle_soup_engine import TurtleSoupBacktestEngine
from config.settings import FirmConfig
from research.hypotheses.graveyard import Graveyard
from research.hypotheses.hypothesis import Hypothesis, Statut
from research.hypotheses.registry import HypothesisRegistry
from research.reports.research_log import ResearchLog
from research.validation.data_split import DataSplit
from research.validation.pipeline import ValidationPipeline

WINDOW_DAYS = 365   # bougies daily sur de longs historiques -> fenêtres de 1 an

RAISON = (
    "Les faux breakouts au-dessus/dessous de plus hauts/bas évidents "
    "correspondent à des chasses aux stops par les gros acteurs (poches de "
    "liquidité). Après le balayage des stops, le prix revient — mécanisme de "
    "microstructure réel."
)
PREDICTION = (
    "Si l'edge est réel, il persiste out-of-sample et reste positif sur des "
    "paramètres voisins (lookback et RR proches)."
)
CRITERES_ECHEC = {
    "profit_factor_min": 1.2,
    "coherence_min": 60.0,
    "doit_persister_sur_test_set": True,
}

HYPOTHESES = [
    {
        "id": "eurusd_turtle_soup_rr1",
        "symbol": "EUR/USD",
        "nom": "Turtle Soup (faux breakout) EUR/USD daily, RR 1:1",
        "donnees_test": "20% les plus récents d'EUR/USD daily, verrouillés",
        "strategy_params": {"rr": 1.0},
        # lookback voisins (15/25/30) + RR voisins autour de 1.0
        "param_variations": [
            {"lookback": 15}, {"lookback": 25}, {"lookback": 30},
            {"rr": 0.8}, {"rr": 1.5},
        ],
    },
    {
        "id": "xauusd_turtle_soup_rr2",
        "symbol": "XAU/USD",
        "nom": "Turtle Soup (faux breakout) or daily, RR 1:2",
        "donnees_test": "20% les plus récents de GC=F daily, verrouillés",
        "strategy_params": {"rr": 2.0},
        # lookback voisins (15/25/30) + RR voisins autour de 2.0
        "param_variations": [
            {"lookback": 15}, {"lookback": 25}, {"lookback": 30},
            {"rr": 1.5}, {"rr": 2.5},
        ],
    },
]


def build_hypothesis(spec: dict) -> Hypothesis:
    return Hypothesis(
        id=spec["id"], nom=spec["nom"], raison=RAISON, prediction=PREDICTION,
        criteres_echec=CRITERES_ECHEC, donnees_test=spec["donnees_test"],
    )


def run_one(spec: dict, log: ResearchLog, registry: HypothesisRegistry, graveyard: Graveyard, config):
    hypothesis = build_hypothesis(spec)
    registry.register(hypothesis)
    print(f"\nHypothèse '{hypothesis.id}' enregistrée (statut: {hypothesis.statut.value}).")

    symbol = spec["symbol"]
    price_series = fetch_multiple([symbol], interval="1d", period="max")
    print(f"{symbol}: {len(price_series[symbol])} bougies récupérées.")

    data_split = DataSplit()
    train_data, _ = data_split.split(price_series, test_ratio=0.2)
    data_split.lock_test_set()
    print(
        f"Train: {len(train_data[symbol])} bougies | "
        f"Test: {len(price_series[symbol]) - len(train_data[symbol])} bougies (verrouillées)"
    )

    pipeline = ValidationPipeline(research_log=log)
    report = pipeline.validate(
        hypothesis=hypothesis,
        data_split=data_split,
        risk_config=config.risk,
        starting_capital=config.starting_capital,
        spread_cost_pct=0.0002,
        param_variations=spec["param_variations"],
        window_days=WINDOW_DAYS,
        engine_class=TurtleSoupBacktestEngine,
        strategy_params=spec["strategy_params"],
    )

    if report.passed:
        registry.update_statut(hypothesis.id, Statut.VALIDEE)
    else:
        registry.update_statut(hypothesis.id, Statut.REJETEE)
        graveyard.bury(hypothesis, report.recommended_raison, report.stages[-1].metrics)

    return hypothesis, report


def main() -> None:
    log = ResearchLog()
    registry = HypothesisRegistry(research_log=log)
    graveyard = Graveyard(research_log=log)
    config = FirmConfig.default()

    results = [run_one(spec, log, registry, graveyard, config) for spec in HYPOTHESES]

    print("\n" + "=" * 78)
    print("RAPPORTS CÔTE À CÔTE")
    print("=" * 78)
    for hypothesis, report in results:
        print()
        print(report.summary())

    print()
    print("=" * 78)
    print("VERDICTS FINAUX")
    print("=" * 78)
    for hypothesis, report in results:
        print(
            f"  {hypothesis.id:24s} -> {'VALIDEE' if report.passed else 'REJETEE'}"
            + ("" if report.passed else f" ({report.stopped_at})")
        )


if __name__ == "__main__":
    main()
