"""
ResearchLog — journal d'activité de la recherche d'edge, en JSON-lines (une
entrée horodatée par ligne). Trace tout: enregistrement d'hypothèses, étapes
de validation passées/échouées, hypothèses validées ou enterrées, et accès
au test set — pour reconstituer après coup l'historique complet d'une
hypothèse sans avoir à faire confiance à la mémoire de qui l'a testée.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "research_log.jsonl"

EVENT_TYPES = (
    "HYPOTHESIS_REGISTERED",
    "VALIDATION_STARTED",
    "STAGE_PASSED",
    "STAGE_FAILED",
    "HYPOTHESIS_VALIDATED",
    "HYPOTHESIS_BURIED",
    "TEST_SET_ACCESSED",
)


class ResearchLog:
    def __init__(self, path: Path | str = DEFAULT_PATH) -> None:
        self.path = Path(path)

    def log(self, event_type: str, hypothesis_id: str, details: dict) -> None:
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            "hypothesis_id": hypothesis_id,
            "details": details,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def read_all(self) -> list[dict]:
        if not self.path.exists():
            return []
        with self.path.open(encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    def summary(self) -> str:
        entries = self.read_all()
        if not entries:
            return "Aucune activité de recherche enregistrée."

        by_type: dict[str, int] = {}
        by_hypothesis: dict[str, list[str]] = {}
        for entry in entries:
            by_type[entry["event_type"]] = by_type.get(entry["event_type"], 0) + 1
            by_hypothesis.setdefault(entry["hypothesis_id"], []).append(entry["event_type"])

        lines = [
            "=== Résumé de l'activité de recherche ===",
            f"Total d'événements: {len(entries)}",
            "",
            "Par type d'événement:",
        ]
        for event_type, count in sorted(by_type.items()):
            lines.append(f"  {event_type:24s} {count}")

        lines.append("")
        lines.append("Par hypothèse:")
        for hyp_id, events in by_hypothesis.items():
            lines.append(f"  {hyp_id:28s} {len(events)} événement(s) — dernier: {events[-1]}")

        return "\n".join(lines)
