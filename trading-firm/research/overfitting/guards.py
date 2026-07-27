"""
OverfittingGuard — garde-fous contre le p-hacking et le surajustement par
accumulation d'essais.

Logique documentée:

- check_trial_budget: chaque variante de paramètres testée sur une même
  hypothèse est un "essai". Plus on en fait, plus la probabilité de trouver
  une combinaison qui a l'air bonne PAR HASARD augmente — c'est un biais
  statistique mécanique (p-hacking), pas une question d'intention malhonnête.
  Passé un budget d'essais raisonnable (défaut 20), le guard avertit: au-delà
  de ce budget, toute "amélioration" trouvée doit être regardée avec une
  méfiance ACCRUE, pas moins — c'est le signe qu'on cherche du bruit, pas
  un edge.

- complexity_penalty: une stratégie à N paramètres a N degrés de liberté
  pour épouser le bruit de l'historique testé. Plus N est grand, plus le
  seuil de validation (profit factor minimum exigé) doit être relevé pour
  compenser ce risque — sinon on valide plus facilement des stratégies
  complexes qui n'ont fait que mémoriser le passé plutôt que capturer un
  edge réel et généralisable.
"""

import logging

logger = logging.getLogger("research.overfitting")

DEFAULT_MAX_TRIALS = 20
PENALTY_PER_PARAMETER = 0.05   # +5% de profit_factor minimum exigé par paramètre au-delà de 2
BASELINE_PARAMETER_COUNT = 2   # ex: rsi_oversold/rsi_overbought — la base "simple" sans pénalité


class OverfittingGuard:
    def __init__(self) -> None:
        self.trials_count: dict[str, int] = {}

    def record_trial(self, hypothesis_id: str) -> int:
        """À appeler à chaque variante de paramètres testée sur une hypothèse.
        Retourne le nombre total d'essais effectués jusqu'ici."""
        self.trials_count[hypothesis_id] = self.trials_count.get(hypothesis_id, 0) + 1
        return self.trials_count[hypothesis_id]

    def check_trial_budget(self, hypothesis_id: str, max_trials: int = DEFAULT_MAX_TRIALS) -> bool:
        count = self.trials_count.get(hypothesis_id, 0)
        within_budget = count <= max_trials
        if not within_budget:
            logger.warning(
                f"Hypothèse '{hypothesis_id}': {count} essais effectués (budget: {max_trials}). "
                "Risque de p-hacking élevé — toute amélioration trouvée au-delà de ce budget "
                "est statistiquement suspecte, pas encourageante."
            )
        return within_budget

    @staticmethod
    def complexity_penalty(n_parameters: int) -> float:
        """Facteur multiplicatif à appliquer au profit_factor minimum exigé
        pour valider une hypothèse. complexity_penalty(2) == 1.0 (aucune
        pénalité pour une stratégie à 2 paramètres, ex seuils RSI haut/bas).
        Chaque paramètre supplémentaire augmente l'exigence de 5%."""
        extra_params = max(n_parameters - BASELINE_PARAMETER_COUNT, 0)
        return 1.0 + extra_params * PENALTY_PER_PARAMETER
