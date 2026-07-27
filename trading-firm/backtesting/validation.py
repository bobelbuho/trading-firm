"""
Validation walk-forward — orchestre des backtests successifs (avec et sans
spread_cost_pct) sur des fenêtres temporelles glissantes, pour produire un
verdict GO/NO-GO objectif avant tout passage en live.

Ce module ne réimplémente RIEN de la logique de signal/risque: il pilote
BacktestEngine (backtesting/engine.py), qui réutilise déjà core/indicators.py,
core/strategy_logic.py et core/risk_logic.py. Il se contente de découper les
données en fenêtres, lancer les backtests, agréger les résultats et appliquer
les seuils GO/NO-GO ci-dessous.

Limite connue (V1): chaque fenêtre est tranchée indépendamment par date, donc
les ~28-50 premières bougies de chaque fenêtre ont un warm-up d'indicateurs
incomplet (pas d'historique reporté entre fenêtres). Effet de bord mineur
accepté, pas de re-fetch de lookback supplémentaire par fenêtre.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from backtesting.data_loader import fetch_multiple
from backtesting.engine import BacktestEngine, BacktestResult, BacktestTrade
from config.settings import RiskConfig

# --- Seuils GO/NO-GO (documentés, configurables) ---
MIN_PROFIT_FACTOR = 1.0            # minimum absolu pour ne pas être NO-GO
HEALTHY_PROFIT_FACTOR = 1.2        # "sain" — indicatif dans le rapport, pas bloquant
MIN_WIN_RATE_PCT = 40.0
MAX_DRAWDOWN_PCT = 20.0
MIN_SYMBOL_COHERENCE_PCT = 60.0     # % de symboles qui doivent passer individuellement
MIN_WINDOW_STABILITY_PCT = 70.0    # % de fenêtres walk-forward avec profit_factor > 1

# --- Défauts du protocole ---
DEFAULT_SYMBOLS = ["BTC/USDT", "TSLA", "XAU/USD"]
DEFAULT_INTERVAL = "5m"
DEFAULT_TOTAL_PERIOD_DAYS = 60
DEFAULT_WINDOW_DAYS = 15
DEFAULT_SPREAD_COST_PCT = 0.0002

VERDICT_PASSED = "PASSED"
VERDICT_FAILED = "FAILED"
VERDICT_FAILED_SPREAD_ONLY = "FAILED_SPREAD_ONLY"


@dataclass
class SymbolValidation:
    symbol: str
    verdict: str
    window_stability_pct: float
    with_spread: BacktestResult
    zero_spread: BacktestResult
    windows: list[dict]

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "window_stability_pct": round(self.window_stability_pct, 1),
            "with_spread": _result_metrics(self.with_spread),
            "zero_spread": _result_metrics(self.zero_spread),
            "windows": [
                {
                    "window_index": w["window_index"],
                    "start": w["start"].isoformat(),
                    "end": w["end"].isoformat(),
                    "with_spread": w["with_spread"],
                    "zero_spread": w["zero_spread"],
                }
                for w in self.windows
            ],
        }


@dataclass
class ValidationReport:
    verdict: str
    generated_at: datetime
    symbol_coherence_pct: float
    symbols: dict[str, SymbolValidation]
    config: dict

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "generated_at": self.generated_at.isoformat(),
            "symbol_coherence_pct": round(self.symbol_coherence_pct, 1),
            "symbols": {symbol: sv.to_dict() for symbol, sv in self.symbols.items()},
            "config": self.config,
            "summary": self.summary(),
        }

    def summary(self) -> str:
        lines = [
            "=== Rapport de validation (walk-forward GO/NO-GO) ===",
            f"Verdict global      : {self.verdict}",
            f"Cohérence symboles  : {self.symbol_coherence_pct:.1f}% (seuil: {MIN_SYMBOL_COHERENCE_PCT:.0f}%)",
            "",
        ]
        for symbol, sv in self.symbols.items():
            lines.append(f"--- {symbol} : {sv.verdict} (stabilité fenêtres: {sv.window_stability_pct:.1f}%) ---")
            lines.append(f"  avec spread : {_format_metrics(sv.with_spread)}")
            lines.append(f"  sans spread : {_format_metrics(sv.zero_spread)}")
            lines.append(f"  fenêtres testées: {len(sv.windows)}")
            lines.append("")
        return "\n".join(lines)


def _format_metrics(result: BacktestResult) -> str:
    pf = "inf" if result.profit_factor == float("inf") else f"{result.profit_factor:.2f}"
    return (
        f"rendement={result.total_return_pct:+.2f}% PF={pf} "
        f"win_rate={result.win_rate_pct:.1f}% max_dd={result.max_drawdown_pct:.2f}% "
        f"trades={len(result.trades)}"
    )


def _result_metrics(result: BacktestResult) -> dict:
    return {
        "return_pct": round(result.total_return_pct, 4),
        "profit_factor": result.profit_factor,
        "win_rate_pct": round(result.win_rate_pct, 2),
        "max_drawdown_pct": round(result.max_drawdown_pct, 2),
        "trades": len(result.trades),
    }


def _make_windows(bars: list[dict], window_days: int) -> list[tuple[datetime, datetime]]:
    if not bars:
        return []

    first_ts, last_ts = bars[0]["timestamp"], bars[-1]["timestamp"]
    window = timedelta(days=window_days)

    windows = []
    start = first_ts
    while start < last_ts:
        end = start + window
        windows.append((start, end))
        start = end
    return windows


def _slice_bars(bars: list[dict], start: datetime, end: datetime) -> list[dict]:
    return [bar for bar in bars if start <= bar["timestamp"] < end]


def _combine_window_results(results: list[BacktestResult], starting_capital: float) -> BacktestResult:
    """Recompose une courbe d'équity continue à travers des fenêtres qui,
    individuellement, repartent chacune de starting_capital — sinon les
    stats agrégées (rendement, drawdown) seraient fausses."""
    trades: list[BacktestTrade] = []
    equity_curve: list[tuple[datetime, float]] = []
    running_base = starting_capital

    for result in results:
        trades.extend(result.trades)
        for ts, equity in result.equity_curve:
            equity_curve.append((ts, running_base + (equity - result.starting_capital)))
        running_base += (result.final_equity - result.starting_capital)

    return BacktestResult(
        trades=trades, equity_curve=equity_curve,
        starting_capital=starting_capital, final_equity=running_base,
    )


def _passes_thresholds(result: BacktestResult, window_stability_pct: float) -> bool:
    return (
        result.profit_factor > MIN_PROFIT_FACTOR
        and result.win_rate_pct >= MIN_WIN_RATE_PCT
        and result.max_drawdown_pct <= MAX_DRAWDOWN_PCT
        and window_stability_pct >= MIN_WINDOW_STABILITY_PCT
    )


def _symbol_verdict(with_spread: BacktestResult, zero_spread: BacktestResult, window_stability_pct: float) -> str:
    if _passes_thresholds(with_spread, window_stability_pct):
        return VERDICT_PASSED
    if _passes_thresholds(zero_spread, window_stability_pct):
        return VERDICT_FAILED_SPREAD_ONLY
    return VERDICT_FAILED


def _evaluate_symbol(
    symbol: str, bars: list[dict], risk_config: RiskConfig,
    starting_capital: float, spread_cost_pct: float, window_days: int,
) -> SymbolValidation:
    windows = _make_windows(bars, window_days)
    engine_spread = BacktestEngine(risk_config, starting_capital, spread_cost_pct)
    engine_zero = BacktestEngine(risk_config, starting_capital, 0.0)

    window_details: list[dict] = []
    spread_results: list[BacktestResult] = []
    zero_results: list[BacktestResult] = []
    profitable_windows = 0

    for index, (start, end) in enumerate(windows):
        window_bars = _slice_bars(bars, start, end)
        if not window_bars:
            continue

        result_spread = engine_spread.run({symbol: window_bars})
        result_zero = engine_zero.run({symbol: window_bars})

        if result_spread.profit_factor > 1.0:
            profitable_windows += 1

        spread_results.append(result_spread)
        zero_results.append(result_zero)
        window_details.append({
            "window_index": index, "start": start, "end": end,
            "with_spread": _result_metrics(result_spread),
            "zero_spread": _result_metrics(result_zero),
        })

    window_stability_pct = (profitable_windows / len(window_details) * 100) if window_details else 0.0

    aggregate_spread = _combine_window_results(spread_results, starting_capital)
    aggregate_zero = _combine_window_results(zero_results, starting_capital)
    verdict = _symbol_verdict(aggregate_spread, aggregate_zero, window_stability_pct)

    return SymbolValidation(
        symbol=symbol, verdict=verdict, window_stability_pct=window_stability_pct,
        with_spread=aggregate_spread, zero_spread=aggregate_zero, windows=window_details,
    )


def run_validation(
    symbols: list[str] | None = None,
    interval: str = DEFAULT_INTERVAL,
    total_period_days: int = DEFAULT_TOTAL_PERIOD_DAYS,
    window_days: int = DEFAULT_WINDOW_DAYS,
    risk_config: RiskConfig | None = None,
    starting_capital: float = 10_000.0,
    spread_cost_pct: float = DEFAULT_SPREAD_COST_PCT,
) -> ValidationReport:
    symbols = symbols or DEFAULT_SYMBOLS
    risk_config = risk_config or RiskConfig()

    price_series = fetch_multiple(symbols, interval=interval, period=f"{total_period_days}d")

    symbol_validations = {
        symbol: _evaluate_symbol(
            symbol, price_series.get(symbol, []), risk_config,
            starting_capital, spread_cost_pct, window_days,
        )
        for symbol in symbols
    }

    total = len(symbol_validations) or 1
    passed = sum(1 for sv in symbol_validations.values() if sv.verdict == VERDICT_PASSED)
    passed_or_spread_only = sum(
        1 for sv in symbol_validations.values() if sv.verdict in (VERDICT_PASSED, VERDICT_FAILED_SPREAD_ONLY)
    )
    symbol_coherence_pct = passed / total * 100

    if symbol_coherence_pct >= MIN_SYMBOL_COHERENCE_PCT:
        verdict = VERDICT_PASSED
    elif (passed_or_spread_only / total * 100) >= MIN_SYMBOL_COHERENCE_PCT:
        verdict = VERDICT_FAILED_SPREAD_ONLY
    else:
        verdict = VERDICT_FAILED

    return ValidationReport(
        verdict=verdict,
        generated_at=datetime.now(timezone.utc),
        symbol_coherence_pct=symbol_coherence_pct,
        symbols=symbol_validations,
        config={
            "symbols": symbols, "interval": interval, "total_period_days": total_period_days,
            "window_days": window_days, "spread_cost_pct": spread_cost_pct,
            "thresholds": {
                "min_profit_factor": MIN_PROFIT_FACTOR, "healthy_profit_factor": HEALTHY_PROFIT_FACTOR,
                "min_win_rate_pct": MIN_WIN_RATE_PCT, "max_drawdown_pct": MAX_DRAWDOWN_PCT,
                "min_symbol_coherence_pct": MIN_SYMBOL_COHERENCE_PCT,
                "min_window_stability_pct": MIN_WINDOW_STABILITY_PCT,
            },
        },
    )
