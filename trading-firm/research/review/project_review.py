"""
project_review.py — unité de SYNTHÈSE/BILAN, pas de prédiction.

Compile l'activité de recherche interne (hypotheses.json, graveyard.json,
research_log.jsonl) et le contexte macro statique (config/economic_calendar.py)
en un bilan factuel: où en est la recherche, ce qu'on a appris des échecs, et
une recommandation sur la MARCHE À SUIVRE DU PROJET.

GARDE-FOU EXPLICITE: ce module ne prédit JAMAIS de direction de marché et ne
génère aucun signal de trading. Toutes ses "recommandations" portent
exclusivement sur la conduite du projet de recherche (continuer, arrêter,
passer en paper trading...), jamais sur quoi acheter ou vendre. Voir
_disclaimer().

Usage: python research/review/project_review.py
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from config.economic_calendar import get_upcoming_events, is_in_blackout


class ProjectReview:
    DISCLAIMER = (
        "Ce bilan synthétise l'activité de recherche interne. Il ne prédit AUCUNE "
        "direction de marché et ne constitue pas un conseil d'achat ou de vente. "
        "Les recommandations portent uniquement sur la conduite du projet de recherche."
    )

    # Pistes non explorées — liste STATIQUE maintenue à la main. Mets à jour
    # ce module quand une piste est formulée en hypothèse testable (voir
    # research/hypotheses/) ou quand une nouvelle idée mérite d'être notée ici.
    OPEN_LEADS = [
        {"nom": "Momentum inter-marchés (cross-asset)", "statut": "non testée"},
        {"nom": "Régimes de volatilité comme signal (au-delà du filtre défensif actuel)", "statut": "non testée"},
        {"nom": "Autres classes d'actifs (indices, taux, matières premières hors métaux)", "statut": "non testée"},
    ]

    # Règles de recommandation — seuils explicites, pas une boîte noire.
    MIN_TESTED_BEFORE_TIME_CHECK = 5

    def __init__(self, project_root: Path | None = None) -> None:
        self.project_root = project_root or Path(__file__).resolve().parent.parent.parent
        self.research_log_path = self.project_root / "research" / "data" / "research_log.jsonl"
        self.graveyard_path = self.project_root / "research" / "data" / "graveyard.json"
        self.hypotheses_path = self.project_root / "research" / "data" / "hypotheses.json"
        self.backtests_dir = self.project_root / "research" / "data" / "backtests"

    # --- Chargement des sources ---

    def _load_json(self, path: Path, default):
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))

    def _load_jsonl(self, path: Path) -> list[dict]:
        if not path.exists():
            return []
        with path.open(encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    def _load_hypotheses(self) -> list[dict]:
        return self._load_json(self.hypotheses_path, [])

    def _load_graveyard(self) -> list[dict]:
        return self._load_json(self.graveyard_path, [])

    def _load_research_log(self) -> list[dict]:
        return self._load_jsonl(self.research_log_path)

    def _load_backtest_results(self) -> list[Path]:
        if not self.backtests_dir.exists():
            return []
        return sorted(self.backtests_dir.glob("*.json"))

    # --- Garde-fou ---

    def _disclaimer(self) -> str:
        return self.DISCLAIMER

    # --- Section 1: état de la recherche ---

    def _section_research_state(self, hypotheses: list[dict]) -> str:
        total = len(hypotheses)
        by_statut: dict[str, int] = {}
        for h in hypotheses:
            by_statut[h["statut"]] = by_statut.get(h["statut"], 0) + 1

        validees = by_statut.get("VALIDEE", 0)
        rejetees = by_statut.get("REJETEE", 0)
        en_test = by_statut.get("EN_TEST", 0)
        proposees = by_statut.get("PROPOSEE", 0)
        testees = validees + rejetees + en_test

        taux_validation_pct = (validees / total * 100) if total else 0.0

        backtests = self._load_backtest_results()
        backtest_note = (
            f"{len(backtests)} résultat(s) de backtest persisté(s) trouvé(s)."
            if backtests else
            "Aucun résultat de backtest persisté trouvé (les runs de cette session "
            "ont été affichés en console, pas sauvegardés sur disque)."
        )

        lines = [
            "## 1. État de la recherche",
            "",
            f"Hypothèses formulées : {total}",
            f"  - Validées          : {validees}",
            f"  - Rejetées          : {rejetees}",
            f"  - En test           : {en_test}",
            f"  - Proposées (non testées) : {proposees}",
            f"Taux de validation   : {validees}/{total} ({taux_validation_pct:.0f}%)",
            "",
            backtest_note,
        ]
        return "\n".join(lines)

    # --- Section 2: ce qu'on a appris ---

    @staticmethod
    def _one_line_reason(raison_rejet: str, max_len: int = 160) -> str:
        first_sentence = raison_rejet.split(". ")[0].rstrip(".") + "."
        if len(first_sentence) <= max_len:
            return first_sentence
        return raison_rejet[:max_len].rsplit(" ", 1)[0] + "..."

    @staticmethod
    def _categorize_failure(raison_rejet: str) -> str:
        text = raison_rejet.lower()
        if "cointégration" in text or "cointegration" in text:
            return "corrélation ≠ cointégration"
        if "p-hacking" in text or "bruit statistique" in text or "faux positifs" in text:
            return "bruit statistique / tests multiples"
        if "mangé" in text and "spread" in text:
            return "edge mangé par les coûts de transaction"
        if "in_sample" in text.replace(" ", "_") or "profit_factor" in text:
            return "pas d'edge détectable sur indicateurs de prix"
        return "autre"

    def _section_lessons_learned(self, graveyard: list[dict]) -> str:
        lines = ["## 2. Ce qu'on a appris (hypothèses enterrées)", ""]
        if not graveyard:
            lines.append("Aucune hypothèse enterrée pour l'instant.")
            return "\n".join(lines)

        for entry in graveyard:
            hyp_id = entry["hypothesis"]["id"]
            raison = entry["raison_rejet"]
            category = self._categorize_failure(raison)
            headline = self._one_line_reason(raison)
            lines.append(f"- [{hyp_id}] ({category})")
            lines.append(f"    {headline}")

        # Patterns d'échec récurrents, si plusieurs hypothèses partagent une catégorie
        categories = [self._categorize_failure(e["raison_rejet"]) for e in graveyard]
        repeated = {c: categories.count(c) for c in set(categories) if categories.count(c) > 1}
        if repeated:
            lines.append("")
            lines.append("Pattern(s) récurrent(s):")
            for category, count in repeated.items():
                lines.append(f"  - '{category}': {count} hypothèses")

        return "\n".join(lines)

    # --- Section 3: contexte macro actuel ---

    def _section_macro_context(self) -> str:
        now = datetime.now(timezone.utc)
        in_blackout, active_event = is_in_blackout(now, before_min=15, after_min=15)
        upcoming = get_upcoming_events(now, lookahead_hours=24 * 30)

        lines = ["## 3. Contexte macro actuel", ""]
        lines.append(
            "Régime de volatilité: non disponible (MacroAgent ne persiste pas encore "
            "son état sur disque — nécessite une exécution live pour ce chiffre)."
        )
        lines.append("")
        blackout_line = f"Blackout actif maintenant : {'OUI' if in_blackout else 'NON'}"
        if active_event:
            blackout_line += f" ({active_event['nom']})"
        lines.append(blackout_line)

        if upcoming:
            lines.append("Prochains événements à fort impact (30 jours) :")
            for event in upcoming[:5]:
                lines.append(f"  - {event['date']} {event['heure_utc']} UTC — {event['nom']} ({', '.join(event['devises'])})")
        else:
            lines.append(
                "Aucun événement à fort impact dans les 30 prochains jours "
                "(calendrier statique — vérifier qu'il est à jour)."
            )
        return "\n".join(lines)

    # --- Section 4: pistes non explorées ---

    def _section_open_leads(self) -> str:
        lines = ["## 4. Hypothèses restantes / pistes non explorées", ""]
        for lead in self.OPEN_LEADS:
            lines.append(f"  - {lead['nom']} [{lead['statut']}]")
        return "\n".join(lines)

    # --- Section 5: recommandation de marche à suivre (règles explicites) ---

    def _recommendation(self, validees: int, testees: int) -> str:
        if validees >= 1:
            return (
                "Passer à l'implémentation + paper trading pour l'hypothèse validée. "
                "NE PAS trader en réel avant que le paper trading confirme les résultats du backtest."
            )
        if testees < self.MIN_TESTED_BEFORE_TIME_CHECK:
            return (
                f"Continuer la recherche — {testees} hypothèse(s) testée(s) sur "
                f"{self.MIN_TESTED_BEFORE_TIME_CHECK} avant un point d'étape formel, il reste des pistes non explorées."
            )
        return (
            f"Faire un point sur l'investissement en temps : {testees} hypothèses testées, 0 validée. "
            "Le taux d'échec suggère que les edges simples testés jusqu'ici sont épuisés — décider "
            "collectivement si l'on continue la recherche ou si l'on change d'approche/de classe d'actifs."
        )

    def _section_recommendation(self, hypotheses: list[dict]) -> str:
        by_statut: dict[str, int] = {}
        for h in hypotheses:
            by_statut[h["statut"]] = by_statut.get(h["statut"], 0) + 1
        validees = by_statut.get("VALIDEE", 0)
        testees = validees + by_statut.get("REJETEE", 0) + by_statut.get("EN_TEST", 0)

        lines = [
            "## 5. Recommandation de marche à suivre",
            "",
            "Règles explicites (pas une boîte noire) :",
            "  - >=1 hypothèse VALIDEE                      -> implémentation + paper trading",
            f"  - 0 validée ET < {self.MIN_TESTED_BEFORE_TIME_CHECK} testées                   -> continuer la recherche",
            f"  - 0 validée ET >= {self.MIN_TESTED_BEFORE_TIME_CHECK} testées                  -> point d'étape sur l'investissement en temps",
            "",
            f"-> {self._recommendation(validees, testees)}",
        ]
        return "\n".join(lines)

    # --- Assemblage du rapport ---

    def generate_report(self) -> str:
        hypotheses = self._load_hypotheses()
        graveyard = self._load_graveyard()

        sections = [
            self._disclaimer(),
            "",
            "=" * 70,
            f"BILAN DE RECHERCHE — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
            "=" * 70,
            "",
            self._section_research_state(hypotheses),
            "",
            self._section_lessons_learned(graveyard),
            "",
            self._section_macro_context(),
            "",
            self._section_open_leads(),
            "",
            self._section_recommendation(hypotheses),
        ]
        return "\n".join(sections)

    def export_markdown(self, report: str | None = None) -> Path:
        report = report if report is not None else self.generate_report()
        reviews_dir = self.project_root / "research" / "data" / "reviews"
        reviews_dir.mkdir(parents=True, exist_ok=True)
        filename = f"review_{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.md"
        path = reviews_dir / filename
        path.write_text(report, encoding="utf-8")
        return path


def main() -> None:
    review = ProjectReview()
    report = review.generate_report()
    print(report)

    saved_path = review.export_markdown(report)
    print()
    print(f"Rapport sauvegardé: {saved_path}")


if __name__ == "__main__":
    main()
