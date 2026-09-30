"""
bury_gold_silver_cointegration.py — enregistre puis enterre l'hypothèse de
cointégration or/argent, après l'exploration statistique
(research/explore_gold_silver_cointegration.py): Engle-Granger et ADF
rejettent tous deux la cointégration sur le train (p=0.356 et p=0.213, très
au-dessus de 0.05), et la relation ne tient pas non plus hors échantillon
(ADF test p=0.394). Corrélation forte entre or et argent, mais pas de
relation de long terme stationnaire — l'écart de prix dérive sans borne.

Usage: python research/bury_gold_silver_cointegration.py
"""

import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from research.hypotheses.graveyard import Graveyard
from research.hypotheses.hypothesis import Hypothesis, Statut
from research.hypotheses.registry import HypothesisRegistry
from research.reports.research_log import ResearchLog

HYPOTHESIS_ID = "gold_silver_cointegration"

RAISON_REJET = (
    "Pas de cointégration. Engle-Granger p=0.356 et ADF sur spread p=0.213 sur "
    "le train — sept fois au-dessus du seuil 0.05, pas un échec marginal "
    "rattrapable par un changement de méthode. Ne tient pas non plus hors "
    "échantillon (ADF test p=0.394). Le β est stable (dérive 8.6%) mais sans "
    "objet puisque la relation n'est pas stationnaire. Seulement 4 "
    "dépassements |z|>2 en 401 jours: inexploitable même si la cointégration "
    "avait tenu. Corrélation forte mais cointégration absente — l'écart de "
    "prix or/argent dérive sans borne. Variante log-prix non testée "
    "délibérément: l'ampleur de l'échec (p=0.36) rend le p-hacking le seul "
    "résultat probable d'essais répétés."
)

METRIQUES_FINALES = {
    "eg_pvalue_train": 0.356,
    "adf_pvalue_train": 0.213,
    "adf_pvalue_test": 0.394,
    "beta_train": 38.73,
    "beta_test": 35.41,
    "beta_drift_pct": 8.6,
    "franchissements_z2": 4,
    "demi_vie_jours": 24,
}


def build_hypothesis() -> Hypothesis:
    return Hypothesis(
        id=HYPOTHESIS_ID,
        nom="Cointégration or/argent (arbitrage de paires XAU/USD-XAG/USD)",
        raison=(
            "L'or et l'argent partagent une base d'investisseurs et des moteurs "
            "macro largement communs (couverture inflation, valeur refuge, ratio "
            "or/argent suivi historiquement par les traders de métaux précieux), "
            "ce qui pourrait maintenir leur écart de prix ajusté (spread) autour "
            "d'un équilibre de long terme stationnaire, exploitable par un "
            "arbitrage de paires si l'écart s'élargit temporairement."
        ),
        prediction=(
            "Le spread or/argent (ajusté par un hedge ratio estimé par OLS) est "
            "stationnaire — cointégration confirmée par Engle-Granger ET ADF sur "
            "le train (p<0.05) — avec un retour à la moyenne assez rapide pour "
            "être tradable, et cette relation persiste hors échantillon."
        ),
        criteres_echec={
            "eg_pvalue_max": 0.05,
            "adf_pvalue_max": 0.05,
            "max_beta_drift_pct": 30.0,
            "max_half_life_days": 30.0,
            "min_reversion_rate_20d_pct": 50.0,
        },
        donnees_test=(
            "20% les plus récents de 2 ans de bougies journalières XAU/USD et "
            "XAG/USD, alignées sur dates communes, verrouillées après split"
        ),
    )


def main() -> None:
    log = ResearchLog()
    registry = HypothesisRegistry(research_log=log)
    graveyard = Graveyard(research_log=log)

    hypothesis = build_hypothesis()
    registry.register(hypothesis)
    registry.update_statut(HYPOTHESIS_ID, Statut.REJETEE)
    graveyard.bury(hypothesis, RAISON_REJET, METRIQUES_FINALES)   # bury() logge HYPOTHESIS_BURIED

    print(f"Hypothèse '{HYPOTHESIS_ID}' -> statut {registry.get(HYPOTHESIS_ID).statut.value}, enterrée.")

    print()
    print("=== État du registre ===")
    for h in registry.list_all():
        print(f"  {h.id:28s} statut={h.statut.value}")

    print()
    print("=== État du cimetière ===")
    for entry in graveyard.list_buried():
        print(f"  {entry['hypothesis']['id']:28s} enterrée le {entry['date_enterrement']}")
        print(f"    raison: {entry['raison_rejet']}")
        print(f"    métriques: {entry['metriques_finales']}")

    print()
    print("=== research_log complet depuis le début ===")
    for entry in log.read_all():
        print(f"  [{entry['timestamp']}] {entry['event_type']:24s} {entry['hypothesis_id']}")

    print()
    print(log.summary())


if __name__ == "__main__":
    main()
