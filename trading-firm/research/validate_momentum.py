"""
validate_momentum.py — soumet la stratégie momentum (croisement MM 20/50,
sortie au croisement inverse, backtesting/momentum_engine.py) au pipeline de
validation COMPLET (6 stages) sur deux actifs :
  - l'or (GC=F): candidat crédible (persistance de tendance par lenteur
    d'ajustement des gros acteurs).
  - BTC-USD: candidat suspect d'artefact (bull run séculaire massif sur la
    période — le pipeline doit déterminer si l'edge survit aux sous-périodes
    sans tendance forte, ou s'il n'est qu'un sous-produit de la hausse).

Usage: python research/validate_momentum.py
"""

import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backtesting.data_loader import fetch_multiple
from backtesting.momentum_engine import MomentumBacktestEngine
from config.settings import FirmConfig
from research.hypotheses.graveyard import Graveyard
from research.hypotheses.hypothesis import Hypothesis, Statut
from research.hypotheses.registry import HypothesisRegistry
from research.reports.research_log import ResearchLog
from research.validation.data_split import DataSplit
from research.validation.pipeline import ValidationPipeline

# Paramètres voisins pour le stage de robustesse paramétrique (MM 15/40, 25/60
# au lieu de 20/50).
PARAM_VARIATIONS = [
    {"fast_period": 15, "slow_period": 40},
    {"fast_period": 25, "slow_period": 60},
]

WINDOW_DAYS = 365   # bougies daily sur de longs historiques -> fenêtres de 1 an

HYPOTHESES = [
    {
        "id": "gold_momentum_ma_cross",
        "symbol": "XAU/USD",
        "nom": "Momentum croisement MM 20/50 sur l'or daily",
        "raison": (
            "Les tendances de l'or persistent car les gros acteurs ajustent leurs "
            "positions lentement (pour ne pas impacter le prix) et les acteurs "
            "réagissent avec retard aux nouvelles macro (biais comportemental). "
            "Cette lenteur d'ajustement crée une persistance des tendances qu'un "
            "suivi de tendance peut capturer."
        ),
        "prediction": (
            "Si l'edge est réel, le momentum reste profitable sur données "
            "out-of-sample jamais vues, et sur la majorité des sous-périodes "
            "(pas seulement grâce à une grande tendance unique)."
        ),
        "donnees_test": "20% les plus récents de GC=F daily, verrouillés",
    },
    {
        "id": "btc_momentum_ma_cross",
        "symbol": "BTC/USDT",
        "nom": "Momentum croisement MM 20/50 sur BTC daily",
        "raison": (
            "Même logique de persistance des tendances. ATTENTION: BTC a connu "
            "une tendance haussière séculaire massive sur la période — le test "
            "doit déterminer si l'edge survit sur les sous-périodes "
            "baissières/latérales, ou s'il n'est qu'un artefact du bull run."
        ),
        "prediction": (
            "Si c'est un vrai edge et pas un artefact, le momentum doit être "
            "profitable même sur les sous-périodes SANS tendance haussière forte."
        ),
        "donnees_test": "20% les plus récents de BTC-USD daily, verrouillés",
    },
]

CRITERES_ECHEC = {
    "profit_factor_min": 1.2,
    "coherence_min": 60.0,
    "doit_persister_sur_test_set": True,
}


def build_hypothesis(spec: dict) -> Hypothesis:
    return Hypothesis(
        id=spec["id"], nom=spec["nom"], raison=spec["raison"], prediction=spec["prediction"],
        criteres_echec=CRITERES_ECHEC, donnees_test=spec["donnees_test"],
    )


def run_one(spec: dict, log: ResearchLog, registry: HypothesisRegistry, graveyard: Graveyard, config) -> tuple[Hypothesis, object]:
    hypothesis = build_hypothesis(spec)
    registry.register(hypothesis)
    print(f"\nHypothèse '{hypothesis.id}' enregistrée (statut: {hypothesis.statut.value}).")

    symbol = spec["symbol"]
    price_series = fetch_multiple([symbol], interval="1d", period="max")
    print(f"{symbol}: {len(price_series[symbol])} bougies récupérées.")

    data_split = DataSplit()
    train_data, _ = data_split.split(price_series, test_ratio=0.2)
    data_split.lock_test_set()
    print(f"Train: {len(train_data[symbol])} bougies | Test: {len(price_series[symbol]) - len(train_data[symbol])} bougies (verrouillées)")

    pipeline = ValidationPipeline(research_log=log)
    report = pipeline.validate(
        hypothesis=hypothesis,
        data_split=data_split,
        risk_config=config.risk,
        starting_capital=config.starting_capital,
        spread_cost_pct=0.0002,
        param_variations=PARAM_VARIATIONS,
        window_days=WINDOW_DAYS,
        engine_class=MomentumBacktestEngine,
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
        print(f"  {hypothesis.id:24s} -> {'VALIDEE' if report.passed else 'REJETEE'}"
              + ("" if report.passed else f" ({report.stopped_at})"))


if __name__ == "__main__":
    main()
