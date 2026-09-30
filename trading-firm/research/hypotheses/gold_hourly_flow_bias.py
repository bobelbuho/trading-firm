"""
gold_hourly_flow_bias.py — enregistre l'hypothèse d'un biais directionnel
horaire sur l'or, provoqué par des flux institutionnels forcés à heures
quasi fixes (London fix 10h30/15h, ouverture de Londres): ces acteurs
tradent par obligation contractuelle sans optimiser le prix, ce qui peut
créer une pression directionnelle récurrente sur une fenêtre horaire
précise.

Ce script ne fait qu'ENREGISTRER l'hypothèse — voir
research/explore_gold_hourly.py pour l'analyse exploratoire (train
uniquement, aucune décision de trading à ce stade).

Usage: python research/hypotheses/gold_hourly_flow_bias.py
"""

import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from research.hypotheses.hypothesis import Hypothesis
from research.hypotheses.registry import HypothesisRegistry
from research.reports.research_log import ResearchLog

HYPOTHESIS_ID = "gold_hourly_flow_bias"


def build_hypothesis() -> Hypothesis:
    return Hypothesis(
        id=HYPOTHESIS_ID,
        nom="Biais directionnel horaire sur l'or (flux forcés fix + ouverture Londres)",
        raison=(
            "L'or subit des flux institutionnels forcés à heures quasi fixes "
            "(London fix 10h30/15h, ouverture de Londres). Ces acteurs tradent par "
            "obligation contractuelle sans optimiser le prix, ce qui peut créer une "
            "pression directionnelle récurrente sur une fenêtre horaire précise."
        ),
        prediction=(
            "Au moins une tranche horaire présente un rendement directionnel "
            "statistiquement non-aléatoire, stable entre fenêtres, persistant sur "
            "test set."
        ),
        criteres_echec={
            "profit_factor_min": 1.2,
            "coherence_min": 60.0,
            "doit_persister_sur_test_set": True,
        },
        donnees_test="20% les plus récents de l'historique GC=F, verrouillés",
    )


def main() -> None:
    log = ResearchLog()
    registry = HypothesisRegistry(research_log=log)
    hypothesis = build_hypothesis()
    registry.register(hypothesis)
    print(f"Hypothèse '{hypothesis.id}' enregistrée (statut: {hypothesis.statut.value}).")


if __name__ == "__main__":
    main()
