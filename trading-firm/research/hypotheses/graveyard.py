"""
Graveyard — le cimetière des hypothèses rejetées.

Aussi précieux que les succès: une idée déjà testée et enterrée avec sa
raison précise et ses métriques finales évite de re-brûler du temps (et du
risque de p-hacking) à la re-tester sous une forme légèrement différente en
ayant oublié qu'elle avait déjà échoué.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from research.hypotheses.hypothesis import Hypothesis
from research.reports.research_log import ResearchLog

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "graveyard.json"


class Graveyard:
    def __init__(self, path: Path | str = DEFAULT_PATH, research_log: ResearchLog | None = None) -> None:
        self.path = Path(path)
        self.research_log = research_log
        self._entries: list[dict] = []
        self._load()

    def bury(self, hypothesis: Hypothesis, raison_rejet: str, metriques_finales: dict) -> None:
        self._entries.append({
            "hypothesis": hypothesis.to_dict(),
            "raison_rejet": raison_rejet,
            "metriques_finales": metriques_finales,
            "date_enterrement": datetime.now(timezone.utc).isoformat(),
        })
        self._save()
        if self.research_log:
            self.research_log.log("HYPOTHESIS_BURIED", hypothesis.id, {
                "raison_rejet": raison_rejet, "metriques_finales": metriques_finales,
            })

    def list_buried(self) -> list[dict]:
        return list(self._entries)

    def search_similar(self, raison: str) -> list[dict]:
        """Recherche naïve par recoupement de vocabulaire (pas de NLP) entre
        `raison` et le texte des hypothèses déjà enterrées — suffisant pour
        repérer un doublon évident avant de re-tester une idée."""
        keywords = {word.lower() for word in raison.split() if len(word) > 3}
        matches = []
        for entry in self._entries:
            text = f"{entry['raison_rejet']} {entry['hypothesis']['raison']} {entry['hypothesis']['nom']}".lower()
            if any(keyword in text for keyword in keywords):
                matches.append(entry)
        return matches

    def _load(self) -> None:
        if not self.path.exists():
            return
        self._entries = json.loads(self.path.read_text(encoding="utf-8"))

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._entries, indent=2, ensure_ascii=False), encoding="utf-8")
