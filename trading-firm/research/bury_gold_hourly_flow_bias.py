"""
bury_gold_hourly_flow_bias.py — enterre l'hypothèse 'gold_hourly_flow_bias'
après l'analyse exploratoire (research/explore_gold_hourly.py): le signal
le plus fort ne correspond pas au mécanisme économique invoqué (London fix
/ ouverture de Londres), et le nombre de faux positifs observés est
cohérent avec du pur bruit statistique sur 24 tests simultanés.

Usage: python research/bury_gold_hourly_flow_bias.py
"""

import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from research.hypotheses.graveyard import Graveyard
from research.hypotheses.hypothesis import Statut
from research.hypotheses.registry import HypothesisRegistry
from research.reports.research_log import ResearchLog

HYPOTHESIS_ID = "gold_hourly_flow_bias"

RAISON_REJET = (
    "Signal absent là où la théorie le prédit. Les deux seules heures dépassant "
    "|t|>2 (2h UTC t=2.85, 22h UTC t=-2.62) ne correspondent ni au London fix ni "
    "à l'ouverture de Londres, mécanismes invoqués par l'hypothèse. Nombre de "
    "faux positifs (2 sur 24 tests) cohérent avec le pur hasard à 5%. Aucune "
    "heure ne survit à une correction de Bonferroni (seuil |t|~3.3 pour 24 "
    "tests). Budget anti-p-hacking dépassé (24 essais > 20). Conclusion: bruit "
    "statistique, pas d'edge horaire exploitable sur l'or."
)

METRIQUES_FINALES = {
    "meilleur_t_stat": 2.85,
    "heure_meilleur": 2,
    "seuil_bonferroni": 3.3,
    "n_tests": 24,
    "faux_positifs_attendus": 1.2,
    "faux_positifs_observes": 2,
}


def main() -> None:
    log = ResearchLog()
    registry = HypothesisRegistry(research_log=log)
    graveyard = Graveyard(research_log=log)

    hypothesis = registry.get(HYPOTHESIS_ID)
    if hypothesis is None:
        raise KeyError(f"Hypothèse '{HYPOTHESIS_ID}' introuvable dans le registre.")

    registry.update_statut(HYPOTHESIS_ID, Statut.REJETEE)
    graveyard.bury(hypothesis, RAISON_REJET, METRIQUES_FINALES)   # bury() logge HYPOTHESIS_BURIED

    print(f"Hypothèse '{HYPOTHESIS_ID}' -> statut {registry.get(HYPOTHESIS_ID).statut.value}, enterrée.")
    print()

    print("=== État du registre ===")
    for h in registry.list_all():
        print(f"  {h.id:24s} statut={h.statut.value}")

    print()
    print("=== État du cimetière ===")
    for entry in graveyard.list_buried():
        print(f"  {entry['hypothesis']['id']:24s} enterrée le {entry['date_enterrement']}")
        print(f"    raison: {entry['raison_rejet']}")
        print(f"    métriques: {entry['metriques_finales']}")


if __name__ == "__main__":
    main()
