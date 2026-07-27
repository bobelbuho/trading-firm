"""
HypothesisRegistry — le registre central des hypothèses. Sa seule vraie
responsabilité de garde-fou: refuser d'enregistrer une hypothèse incomplète.

Une hypothèse sans raison économique ni critère d'échec pré-défini n'est
rien d'autre qu'un backtest qui cherche sa justification a posteriori —
exactement ce que ce module existe pour empêcher.
"""

import json
from pathlib import Path

from research.hypotheses.hypothesis import Hypothesis, Statut
from research.reports.research_log import ResearchLog

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "hypotheses.json"


class IncompleteHypothesisError(ValueError):
    pass


class HypothesisRegistry:
    def __init__(self, path: Path | str = DEFAULT_PATH, research_log: ResearchLog | None = None) -> None:
        self.path = Path(path)
        self.research_log = research_log
        self._hypotheses: dict[str, Hypothesis] = {}
        self._load()

    def register(self, hypothesis: Hypothesis) -> None:
        if not hypothesis.is_complete():
            missing = self._missing_fields(hypothesis)
            raise IncompleteHypothesisError(
                f"Hypothèse '{hypothesis.id}' incomplète — champ(s) manquant(s): {', '.join(missing)}. "
                "Une hypothèse sans raison économique, prédiction, critères d'échec ET données de "
                "test réservées ne peut pas être enregistrée (garde anti-p-hacking)."
            )

        self._hypotheses[hypothesis.id] = hypothesis
        self._save()
        if self.research_log:
            self.research_log.log("HYPOTHESIS_REGISTERED", hypothesis.id, {"nom": hypothesis.nom})

    @staticmethod
    def _missing_fields(hypothesis: Hypothesis) -> list[str]:
        fields = {
            "raison": hypothesis.raison,
            "prediction": hypothesis.prediction,
            "criteres_echec": hypothesis.criteres_echec,
            "donnees_test": hypothesis.donnees_test,
        }
        return [name for name, value in fields.items() if not value]

    def get(self, id: str) -> Hypothesis | None:
        return self._hypotheses.get(id)

    def list_all(self) -> list[Hypothesis]:
        return list(self._hypotheses.values())

    def list_by_statut(self, statut: Statut) -> list[Hypothesis]:
        return [h for h in self._hypotheses.values() if h.statut == statut]

    def update_statut(self, id: str, nouveau_statut: Statut) -> None:
        hypothesis = self._hypotheses.get(id)
        if hypothesis is None:
            raise KeyError(f"Hypothèse inconnue: '{id}'")
        hypothesis.statut = nouveau_statut
        self._save()

    def _load(self) -> None:
        if not self.path.exists():
            return
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self._hypotheses = {item["id"]: Hypothesis.from_dict(item) for item in data}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps([h.to_dict() for h in self._hypotheses.values()], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
