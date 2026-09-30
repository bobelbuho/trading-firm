"""
ValidationPipeline — exécute les 5 stages de recherche/validation DANS
L'ORDRE, en s'arrêtant à la première étape qui échoue. Pas la peine de
tester la robustesse paramétrique ou temporelle d'un signal qui n'existe
même pas en in-sample — chaque étape suivante suppose que les précédentes
sont vraies.

Réutilise entièrement un moteur de backtest (BacktestEngine par défaut, ou
tout autre moteur partageant la même convention de constructeur — voir
`engine_class`, ex. MomentumBacktestEngine) et le découpage en fenêtres déjà
écrit dans backtesting/validation.py — ce module n'ajoute AUCUNE logique de
signal ou de risque, seulement l'orchestration et la discipline de
découverte du edge (train uniquement jusqu'au stage 2, puis un seul regard
sur le test set).
"""

from dataclasses import dataclass

import backtesting.validation as walk_forward
from backtesting.engine import BacktestEngine, BacktestResult
from config.settings import RiskConfig
from research.hypotheses.hypothesis import Hypothesis, Statut
from research.reports.research_log import ResearchLog
from research.validation import stages
from research.validation.data_split import DataSplit


@dataclass
class StageOutcome:
    name: str
    passed: bool
    metrics: dict
    message: str


@dataclass
class ValidationReport:
    hypothesis_id: str
    passed: bool
    stopped_at: str | None          # nom du stage qui a échoué, None si tout est passé
    stages: list[StageOutcome]
    recommended_statut: Statut       # VALIDEE ou REJETEE
    recommended_raison: str | None   # raison de rejet proposée si REJETEE

    def summary(self) -> str:
        lines = [f"=== Pipeline de validation — hypothèse '{self.hypothesis_id}' ==="]
        for stage in self.stages:
            lines.append(f"[{'PASS' if stage.passed else 'FAIL'}] {stage.name}: {stage.message}")
        lines.append("")
        lines.append(f"Résultat: {'VALIDÉE' if self.passed else 'REJETÉE'}")
        if not self.passed:
            lines.append(f"Raison proposée: {self.recommended_raison}")
        return "\n".join(lines)


class ValidationPipeline:
    def __init__(self, research_log: ResearchLog | None = None) -> None:
        self.log = research_log or ResearchLog()

    def validate(
        self,
        hypothesis: Hypothesis,
        data_split: DataSplit,
        risk_config: RiskConfig,
        starting_capital: float = 10_000.0,
        spread_cost_pct: float = 0.0002,
        param_variations: list[dict] | None = None,
        window_days: int = 15,
        engine_class: type = BacktestEngine,
        strategy_params: dict | None = None,
    ) -> ValidationReport:
        if not hypothesis.is_complete():
            raise ValueError(f"Hypothèse '{hypothesis.id}' incomplète — impossible de la valider.")
        if data_split.train_data is None:
            raise ValueError("data_split.split(...) doit être appelé avant validate().")

        param_variations = param_variations or []
        strategy_params = strategy_params or {}
        self.log.log("VALIDATION_STARTED", hypothesis.id, {})
        outcomes: list[StageOutcome] = []

        def record(name: str, passed: bool, metrics: dict, message: str) -> None:
            outcomes.append(StageOutcome(name, passed, metrics, message))
            self.log.log("STAGE_PASSED" if passed else "STAGE_FAILED", hypothesis.id, {
                "stage": name, "metrics": metrics, "message": message,
            })

        def stopped(name: str, metrics: dict, message: str) -> ValidationReport:
            raison = self._raison_from_stage(name, metrics, message)
            return ValidationReport(hypothesis.id, False, name, outcomes, Statut.REJETEE, raison)

        # --- Stage 1: le signal existe-t-il en in-sample (train) ? ---
        engine = engine_class(risk_config, starting_capital, spread_cost_pct, **strategy_params)
        result_in_sample = engine.run(data_split.train_data)
        passed, metrics, message = stages.stage_in_sample(hypothesis, result_in_sample)
        record("in_sample", passed, metrics, message)
        if not passed:
            return stopped("in_sample", metrics, message)

        # --- Stage 2: marche-t-il sur le test set ? Le SEUL regard autorisé. ---
        data_split.lock_test_set()
        test_data = data_split.get_test_set()
        self.log.log("TEST_SET_ACCESSED", hypothesis.id, {"access_count": data_split.test_set_accessed})
        result_out_of_sample = engine.run(test_data)
        passed, metrics, message = stages.stage_out_of_sample(hypothesis, result_out_of_sample)
        record("out_of_sample", passed, metrics, message)
        if not passed:
            return stopped("out_of_sample", metrics, message)

        # --- Stage 3: robustesse aux paramètres voisins (train uniquement) ---
        passed, metrics, message = stages.stage_param_robustness(
            hypothesis, engine, data_split.train_data, param_variations,
        )
        record("param_robustness", passed, metrics, message)
        if not passed:
            return stopped("param_robustness", metrics, message)

        # --- Stage 4: cohérence multi-fenêtres (train uniquement) ---
        result_windows = self._run_windows(
            data_split.train_data, risk_config, starting_capital, spread_cost_pct, window_days,
            engine_class, strategy_params,
        )
        passed, metrics, message = stages.stage_temporal_robustness(hypothesis, result_windows)
        record("temporal_robustness", passed, metrics, message)
        if not passed:
            return stopped("temporal_robustness", metrics, message)

        # --- Stage 5: survie aux coûts de transaction (train, avec vs sans spread) ---
        result_zero_spread = engine_class(risk_config, starting_capital, 0.0, **strategy_params).run(data_split.train_data)
        passed, metrics, message = stages.stage_cost_survival(hypothesis, result_in_sample, result_zero_spread)
        record("cost_survival", passed, metrics, message)
        if not passed:
            return stopped("cost_survival", metrics, message)

        # --- Stage 6: résistance aux scénarios de stress (train uniquement) ---
        # Exécuté en dernier: pas la peine de stresser un signal qui n'a même
        # pas prouvé d'edge statistique aux 5 stages précédents.
        passed, metrics, message = stages.stage_stress_survival(hypothesis, engine, data_split.train_data, strategy_params)
        record("stress_survival", passed, metrics, message)
        if not passed:
            return stopped("stress_survival", metrics, message)

        self.log.log("HYPOTHESIS_VALIDATED", hypothesis.id, {})
        return ValidationReport(hypothesis.id, True, None, outcomes, Statut.VALIDEE, None)

    @staticmethod
    def _run_windows(
        price_series: dict[str, list[dict]], risk_config: RiskConfig,
        starting_capital: float, spread_cost_pct: float, window_days: int,
        engine_class: type = BacktestEngine, strategy_params: dict | None = None,
    ) -> list[BacktestResult]:
        engine = engine_class(risk_config, starting_capital, spread_cost_pct, **(strategy_params or {}))
        results = []
        for symbol, bars in price_series.items():
            for start, end in walk_forward._make_windows(bars, window_days):
                window_bars = walk_forward._slice_bars(bars, start, end)
                if window_bars:
                    results.append(engine.run({symbol: window_bars}))
        return results

    @staticmethod
    def _raison_from_stage(name: str, metrics: dict, message: str) -> str:
        if name == "cost_survival" and metrics.get("spread_only_failure"):
            return f"Edge mangé par les coûts de transaction (spread), pas d'absence d'edge — {message}"
        return f"Échec du stage '{name}': {message}"
