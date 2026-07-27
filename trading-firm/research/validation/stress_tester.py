"""
StressTester — philosophie Aladdin (BlackRock): ne pas juger une stratégie
sur son rendement moyen, mais sur sa SURVIE dans les pires scénarios
plausibles. Un edge statistiquement valide qui explose au premier choc de
liquidité n'est pas déployable.

Génère des versions "stressées" d'une price_series réelle en y injectant
des scénarios adverses définis à l'avance, puis rejoue le backtest sur
chacune via le BacktestEngine existant — aucune logique de signal/risque
n'est dupliquée ici, seulement la transformation des données et
l'orchestration des runs.
"""

import random
from dataclasses import dataclass
from datetime import timedelta

from backtesting.engine import BacktestEngine, BacktestResult
from config.settings import RiskConfig

DEFAULT_MAX_DRAWDOWN_THRESHOLD_PCT = 25.0


@dataclass
class ScenarioResult:
    name: str
    result: BacktestResult
    worst_case_loss_pct: float   # perte max atteinte à tout moment, par rapport au capital initial


@dataclass
class StressTestReport:
    baseline: ScenarioResult
    scenarios: list[ScenarioResult]
    max_drawdown_threshold_pct: float = DEFAULT_MAX_DRAWDOWN_THRESHOLD_PCT

    def survived(self) -> bool:
        """True seulement si, dans TOUS les scénarios, le max drawdown reste
        sous le seuil ET la perte worst-case ne dépasse pas le capital
        (ruine). Une stratégie qui passe les tests statistiques mais échoue
        le stress test n'est PAS considérée comme validée."""
        for scenario in self.scenarios:
            if scenario.result.max_drawdown_pct > self.max_drawdown_threshold_pct:
                return False
            if scenario.worst_case_loss_pct >= 100.0:
                return False
        return True

    def summary(self) -> str:
        lines = [
            "=== Rapport de stress test ===",
            f"Seuil de survie (max drawdown): {self.max_drawdown_threshold_pct:.0f}%",
            "",
            self._format_row("référence (sans stress)", self.baseline),
        ]
        for scenario in self.scenarios:
            lines.append(self._format_row(scenario.name, scenario))
        lines.append("")
        lines.append(f"Verdict: {'SURVIT' if self.survived() else 'NE SURVIT PAS'} aux scénarios de stress.")
        return "\n".join(lines)

    @staticmethod
    def _format_row(name: str, scenario: ScenarioResult) -> str:
        r = scenario.result
        pf = "inf" if r.profit_factor == float("inf") else f"{r.profit_factor:.2f}"
        return (
            f"  {name:26s} rendement={r.total_return_pct:+7.2f}%  max_dd={r.max_drawdown_pct:6.2f}%  "
            f"PF={pf:>5s}  worst_case_loss={scenario.worst_case_loss_pct:6.2f}%  trades={len(r.trades)}"
        )


class StressTester:
    def __init__(self, max_drawdown_threshold_pct: float = DEFAULT_MAX_DRAWDOWN_THRESHOLD_PCT) -> None:
        self.max_drawdown_threshold_pct = max_drawdown_threshold_pct

    # --- Scénarios: chacun transforme une price_series en une version stressée ---

    @staticmethod
    def flash_crash(
        price_series: dict[str, list[dict]], drop_pct: float = 0.15, recovery_bars: int = 20,
    ) -> dict[str, list[dict]]:
        """Chute brutale de drop_pct sur 2-3 bougies à un point aléatoire de
        la série, suivie d'une récupération partielle (50% du terrain
        perdu) sur recovery_bars bougies. Teste si les stops tiennent et si
        le sizing ne mène pas à une liquidation lors d'un choc soudain."""
        crash_span = 3
        stressed = {}
        for symbol, bars in price_series.items():
            bars = [dict(bar) for bar in bars]
            if len(bars) < crash_span + recovery_bars + 10:
                stressed[symbol] = bars
                continue

            start = random.randint(len(bars) // 4, len(bars) - crash_span - recovery_bars - 5)
            anchor = bars[start]["close"]
            crash_target = anchor * (1 - drop_pct)

            for offset in range(crash_span):
                i = start + offset
                progress = (offset + 1) / crash_span
                new_close = anchor - (anchor - crash_target) * progress
                bars[i]["open"] = bars[i - 1]["close"] if i > start else bars[i]["open"]
                bars[i]["close"] = new_close
                bars[i]["low"] = min(bars[i]["low"], new_close, bars[i]["open"])
                bars[i]["high"] = max(bars[i]["high"], bars[i]["open"])

            recovery_target = crash_target + (anchor - crash_target) * 0.5
            recovery_start = start + crash_span
            for offset in range(recovery_bars):
                i = recovery_start + offset
                if i >= len(bars):
                    break
                progress = (offset + 1) / recovery_bars
                new_close = crash_target + (recovery_target - crash_target) * progress
                bars[i]["open"] = bars[i - 1]["close"]
                bars[i]["close"] = new_close
                bars[i]["high"] = max(bars[i]["high"], bars[i]["open"], new_close)
                bars[i]["low"] = min(bars[i]["low"], bars[i]["open"], new_close)

            stressed[symbol] = bars
        return stressed

    @staticmethod
    def gap_open(price_series: dict[str, list[dict]], gap_pct: float = 0.08) -> dict[str, list[dict]]:
        """Insère un saut de prix brutal entre deux bougies consécutives,
        sans prix intermédiaire — simule un gap d'ouverture week-end ou un
        événement overnight. Teste ce qui arrive quand le prix saute
        PAR-DESSUS un stop-loss (le fill se fait au prix réel disponible,
        pas au niveau théorique du stop — voir BacktestEngine._gapped_fill_price)."""
        stressed = {}
        for symbol, bars in price_series.items():
            bars = [dict(bar) for bar in bars]
            if len(bars) < 10:
                stressed[symbol] = bars
                continue

            gap_index = random.randint(len(bars) // 4, len(bars) - 5)
            direction = random.choice([-1, 1])
            pre_gap_close = bars[gap_index - 1]["close"]
            gapped_open = pre_gap_close * (1 + direction * gap_pct)
            shift = gapped_open - bars[gap_index]["open"]

            for i in range(gap_index, len(bars)):
                bars[i]["open"] += shift
                bars[i]["high"] += shift
                bars[i]["low"] += shift
                bars[i]["close"] += shift

            stressed[symbol] = bars
        return stressed

    @staticmethod
    def volatility_regime_change(
        price_series: dict[str, list[dict]], vol_multiplier: float = 3.0,
    ) -> dict[str, list[dict]]:
        """Amplifie la volatilité de la seconde moitié de la série en
        multipliant l'écart de chaque bougie à une moyenne mobile locale —
        simule un changement de régime où le marché devient soudainement
        beaucoup plus agité (ex: passage d'un range calme à une période
        d'incertitude macro)."""
        window = 10
        stressed = {}
        for symbol, bars in price_series.items():
            bars = [dict(bar) for bar in bars]
            half = len(bars) // 2

            for i in range(half, len(bars)):
                lookback = bars[max(0, i - window):i] or [bars[i]]
                local_mean = sum(b["close"] for b in lookback) / len(lookback)

                for key in ("open", "high", "low", "close"):
                    bars[i][key] = local_mean + (bars[i][key] - local_mean) * vol_multiplier

                bars[i]["high"] = max(bars[i]["high"], bars[i]["open"], bars[i]["close"])
                bars[i]["low"] = min(bars[i]["low"], bars[i]["open"], bars[i]["close"])

            stressed[symbol] = bars
        return stressed

    @staticmethod
    def prolonged_drawdown(price_series: dict[str, list[dict]]) -> dict[str, list[dict]]:
        """Trouve la pire fenêtre baissière historique de la série (du plus
        haut au plus bas, en clôture) et la répète (mise à l'échelle pour
        rester cohérente) pour allonger artificiellement la période
        défavorable — le scénario qui teste la résistance à un drawdown
        prolongé plutôt qu'à un choc ponctuel."""
        stressed = {}
        for symbol, bars in price_series.items():
            if len(bars) < 20:
                stressed[symbol] = [dict(b) for b in bars]
                continue

            peak_idx = 0
            worst_start, worst_end, worst_drop = 0, 0, 0.0
            for i, bar in enumerate(bars):
                if bar["close"] > bars[peak_idx]["close"]:
                    peak_idx = i
                peak_close = bars[peak_idx]["close"]
                drop = (peak_close - bar["close"]) / peak_close if peak_close else 0.0
                if drop > worst_drop:
                    worst_drop, worst_start, worst_end = drop, peak_idx, i

            worst_window = bars[worst_start:worst_end + 1]
            if len(worst_window) < 2:
                stressed[symbol] = [dict(b) for b in bars]
                continue

            avg_delta = (bars[-1]["timestamp"] - bars[0]["timestamp"]) / (len(bars) - 1)
            extended = [dict(b) for b in bars[:worst_end + 1]]
            last_close = extended[-1]["close"]
            last_timestamp = extended[-1]["timestamp"]

            for _ in range(2):   # répète la pire fenêtre 2 fois de plus
                base_close = worst_window[0]["close"]
                ratio = (last_close / base_close) if base_close else 1.0
                for bar in worst_window[1:]:
                    last_timestamp = last_timestamp + avg_delta
                    extended.append({
                        **{key: bar[key] * ratio for key in ("open", "high", "low", "close")},
                        "timestamp": last_timestamp,
                    })
                last_close = extended[-1]["close"]

            time_shift = extended[-1]["timestamp"] - bars[worst_end]["timestamp"]
            for bar in bars[worst_end + 1:]:
                extended.append({**dict(bar), "timestamp": bar["timestamp"] + time_shift})

            stressed[symbol] = extended
        return stressed

    def spread_widening(
        self, price_series: dict[str, list[dict]], risk_config: RiskConfig,
        starting_capital: float, spread_cost_pct: float, multiplier: float = 5.0,
    ) -> BacktestResult:
        """Ne transforme pas les prix: rejoue le backtest avec un
        spread_cost_pct multiplié — simule un moment de faible liquidité où
        les spreads explosent (typique des news ou des ouvertures de
        session)."""
        engine = BacktestEngine(risk_config, starting_capital, spread_cost_pct * multiplier)
        return engine.run(price_series)

    # --- Orchestration ---

    def run_all_scenarios(
        self, base_price_series: dict[str, list[dict]], risk_config: RiskConfig,
        starting_capital: float = 10_000.0, spread_cost_pct: float = 0.0002,
    ) -> StressTestReport:
        engine = BacktestEngine(risk_config, starting_capital, spread_cost_pct)
        baseline = self._to_scenario_result("baseline", engine.run(base_price_series), starting_capital)

        scenarios = [
            self._to_scenario_result(
                "flash_crash", engine.run(self.flash_crash(base_price_series)), starting_capital,
            ),
            self._to_scenario_result(
                "spread_widening",
                self.spread_widening(base_price_series, risk_config, starting_capital, spread_cost_pct),
                starting_capital,
            ),
            self._to_scenario_result(
                "gap_open", engine.run(self.gap_open(base_price_series)), starting_capital,
            ),
            self._to_scenario_result(
                "volatility_regime_change",
                engine.run(self.volatility_regime_change(base_price_series)), starting_capital,
            ),
            self._to_scenario_result(
                "prolonged_drawdown", engine.run(self.prolonged_drawdown(base_price_series)), starting_capital,
            ),
        ]

        return StressTestReport(baseline=baseline, scenarios=scenarios, max_drawdown_threshold_pct=self.max_drawdown_threshold_pct)

    @staticmethod
    def _to_scenario_result(name: str, result: BacktestResult, starting_capital: float) -> ScenarioResult:
        min_equity = min((equity for _, equity in result.equity_curve), default=starting_capital)
        worst_case_loss_pct = max(0.0, (starting_capital - min_equity) / starting_capital * 100) if starting_capital else 0.0
        return ScenarioResult(name=name, result=result, worst_case_loss_pct=worst_case_loss_pct)
