"""
Hypothesis — l'unité atomique de la recherche d'edge.

Une hypothèse mal formée (sans raison économique, sans prédiction précise,
sans critère d'échec défini À L'AVANCE, sans donnée de test réservée) ne
doit jamais pouvoir entrer dans le pipeline de validation — c'est la
première ligne de défense contre le p-hacking ("je regarde les résultats,
puis j'invente une histoire pour les justifier après coup").
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class Statut(Enum):
    PROPOSEE = "PROPOSEE"
    EN_TEST = "EN_TEST"
    VALIDEE = "VALIDEE"
    REJETEE = "REJETEE"


@dataclass
class Hypothesis:
    id: str
    nom: str
    raison: str                # pourquoi l'edge existe économiquement/comportementalement
    prediction: str            # ce qu'on devrait observer si l'hypothèse est vraie
    criteres_echec: dict       # seuils définis à l'avance, ex {"profit_factor_min": 1.2}
    donnees_test: str          # description de la tranche réservée (jamais regardée avant la fin)
    date_creation: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    statut: Statut = Statut.PROPOSEE

    def is_complete(self) -> bool:
        return bool(self.raison) and bool(self.prediction) and bool(self.criteres_echec) and bool(self.donnees_test)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "nom": self.nom,
            "raison": self.raison,
            "prediction": self.prediction,
            "criteres_echec": self.criteres_echec,
            "donnees_test": self.donnees_test,
            "date_creation": self.date_creation.isoformat(),
            "statut": self.statut.value,
        }

    @staticmethod
    def from_dict(data: dict) -> "Hypothesis":
        return Hypothesis(
            id=data["id"],
            nom=data["nom"],
            raison=data["raison"],
            prediction=data["prediction"],
            criteres_echec=data["criteres_echec"],
            donnees_test=data["donnees_test"],
            date_creation=datetime.fromisoformat(data["date_creation"]),
            statut=Statut(data["statut"]),
        )
