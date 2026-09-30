"""
5 stages de validation, exécutés DANS L'ORDRE par ValidationPipeline. Chaque
stage suppose que les précédents sont vrais — pas la peine de tester la
robustesse paramétrique ou temporelle d'un signal qui n'existe même pas en
in-sample.

Toutes les fonctions retournent (passed: bool, metrics: dict, message: str)
et ne réimplémentent RIEN: elles consomment des BacktestResult déjà produits
par un moteur de backtest (BacktestEngine pour le mean reversion,
MomentumBacktestEngine pour le suivi de tendance...) — stage_param_robustness
et stage_stress_survival utilisent type(engine) pour rester agnostiques au
moteur exact, à condition qu'il partage la même convention de constructeur
(config, starting_capital, spread_cost_pct, **params_stratégie).
"""

from backtesting.engine import BacktestEngine, BacktestResult
from research.hypotheses.hypothesis import Hypothesis
from research.validation.stress_tester import DEFAULT_MAX_DRAWDOWN_THRESHOLD_PCT, StressTester

MIN_PROFIT_FACTOR_ROBUSTNESS = 1.0
MAX_PARAM_DEGRADATION_PCT = 50.0
MAX_COST_DEPENDENCY_PCT = 80.0


def stage_in_sample(hypothesis: Hypothesis, result: BacktestResult) -> tuple[bool, dict, str]:
    """Le signal existe-t-il seulement ? Rien de plus exigeant à ce stade —
    si même l'échantillon d'entraînement ne montre aucun edge, inutile
    d'aller plus loin."""
    passed = result.profit_factor > 1.0
    metrics = {
        "profit_factor": round(result.profit_factor, 3),
        "return_pct": round(result.total_return_pct, 2),
        "trades": len(result.trades),
    }
    message = (
        f"Signal détectable en in-sample: profit_factor={result.profit_factor:.2f} sur {len(result.trades)} trades."
        if passed else
        f"Aucun signal en in-sample (profit_factor={result.profit_factor:.2f} <= 1.0) — "
        "inutile de continuer, il n'y a rien à valider."
    )
    return passed, metrics, message


def stage_out_of_sample(hypothesis: Hypothesis, result_test: BacktestResult) -> tuple[bool, dict, str]:
    """Le signal marche-t-il sur des données jamais vues ? Applique les
    criteres_echec définis À L'AVANCE dans l'hypothèse — pas de nouveau
    seuil inventé après avoir vu le résultat."""
    criteres = hypothesis.criteres_echec
    metrics = {
        "profit_factor": round(result_test.profit_factor, 3),
        "win_rate_pct": round(result_test.win_rate_pct, 2),
        "return_pct": round(result_test.total_return_pct, 2),
        "max_drawdown_pct": round(result_test.max_drawdown_pct, 2),
        "trades": len(result_test.trades),
    }

    comparisons = {
        "profit_factor_min": (result_test.profit_factor, ">="),
        "win_rate_min": (result_test.win_rate_pct, ">="),
        "max_drawdown_max": (result_test.max_drawdown_pct, "<="),
        "return_pct_min": (result_test.total_return_pct, ">="),
    }
    failed_criteria = []
    evaluated_any = False
    for key, (actual, op) in comparisons.items():
        if key not in criteres:
            continue
        evaluated_any = True
        threshold = criteres[key]
        ok = actual >= threshold if op == ">=" else actual <= threshold
        if not ok:
            failed_criteria.append(f"{key} (obtenu={actual:.2f}, requis {op} {threshold})")

    passed = (not failed_criteria) if evaluated_any else (result_test.profit_factor > 1.0)
    message = (
        "Hors-échantillon: tous les critères d'échec pré-définis de l'hypothèse sont respectés."
        if passed else
        f"Hors-échantillon: critère(s) violé(s) — {'; '.join(failed_criteria) or 'profit_factor <= 1.0'}."
    )
    return passed, metrics, message


def stage_param_robustness(
    hypothesis: Hypothesis, engine: BacktestEngine, price_series: dict[str, list[dict]],
    param_variations: list[dict],
) -> tuple[bool, dict, str]:
    """Teste des paramètres voisins (ex RSI 33/67, 37/63, ADX max 20/30) et
    vérifie que la perf ne s'effondre pas. Un edge réel n'est pas fragile
    aux réglages — s'il ne survit qu'avec exactement les paramètres qui ont
    servi à le découvrir, c'est le symptôme classique du surajustement."""
    baseline_pf = engine.run(price_series).profit_factor

    # type(engine) plutôt que BacktestEngine en dur: permet de réutiliser ce
    # stage tel quel pour n'importe quel moteur partageant la même convention
    # de constructeur (ex. MomentumBacktestEngine avec fast_period/slow_period).
    variation_pfs = [
        type(engine)(engine.config, engine.starting_capital, engine.spread_cost_pct, **params)
        .run(price_series).profit_factor
        for params in param_variations
    ]

    min_variation_pf = min(variation_pfs) if variation_pfs else baseline_pf
    degradation_pct = ((baseline_pf - min_variation_pf) / baseline_pf * 100) if baseline_pf > 0 else 100.0
    max_degradation_pct = hypothesis.criteres_echec.get("max_degradation_pct", MAX_PARAM_DEGRADATION_PCT)

    passed = min_variation_pf > MIN_PROFIT_FACTOR_ROBUSTNESS and degradation_pct <= max_degradation_pct
    metrics = {
        "baseline_profit_factor": round(baseline_pf, 3),
        "variation_profit_factors": [round(pf, 3) for pf in variation_pfs],
        "min_variation_profit_factor": round(min_variation_pf, 3),
        "degradation_pct": round(degradation_pct, 1),
    }
    message = (
        f"PF de base={baseline_pf:.2f}, PF des {len(variation_pfs)} variations={metrics['variation_profit_factors']} "
        f"— dégradation max={degradation_pct:.0f}% (seuil {max_degradation_pct:.0f}%)."
    )
    return passed, metrics, message


def stage_temporal_robustness(hypothesis: Hypothesis, result_windows: list[BacktestResult]) -> tuple[bool, dict, str]:
    """Cohérence multi-fenêtres: réutilise le même seuil et la même logique
    (% de fenêtres avec profit_factor > 1) que le walk-forward de
    backtesting/validation.py — un edge concentré sur une seule fenêtre
    chanceuse n'est pas un edge fiable."""
    from backtesting.validation import MIN_WINDOW_STABILITY_PCT

    if not result_windows:
        return (
            False, {"window_stability_pct": 0.0, "windows": 0},
            "Aucune fenêtre disponible pour évaluer la stabilité temporelle.",
        )

    profitable = sum(1 for r in result_windows if r.profit_factor > 1.0)
    stability_pct = profitable / len(result_windows) * 100
    threshold = hypothesis.criteres_echec.get("coherence_min", MIN_WINDOW_STABILITY_PCT)

    passed = stability_pct >= threshold
    metrics = {"window_stability_pct": round(stability_pct, 1), "windows": len(result_windows), "threshold_pct": threshold}
    message = f"Stabilité temporelle: {stability_pct:.1f}% des {len(result_windows)} fenêtres profitables (seuil {threshold:.0f}%)."
    return passed, metrics, message


def stage_cost_survival(
    hypothesis: Hypothesis, result_with_spread: BacktestResult, result_no_spread: BacktestResult,
) -> tuple[bool, dict, str]:
    """Le profit factor après coûts reste-t-il exploitable, ET l'edge ne
    vient-il pas MAJORITAIREMENT de l'hypothèse spread=0 ? Distingue
    explicitement (via `spread_only_failure`) le cas "edge réel mais mangé
    par le spread" du cas "pas d'edge du tout" — la nuance qu'on a dû
    reconstruire manuellement sur BTC/USDT/GC=F avant ce module."""
    pf_spread = result_with_spread.profit_factor
    pf_zero = result_no_spread.profit_factor
    min_pf = hypothesis.criteres_echec.get("profit_factor_min", MIN_PROFIT_FACTOR_ROBUSTNESS)

    survives_costs = pf_spread >= min_pf
    edge_zero = max(pf_zero - 1.0, 0.0)
    edge_spread = max(pf_spread - 1.0, 0.0)
    cost_dependency_pct = ((edge_zero - edge_spread) / edge_zero * 100) if edge_zero > 0 else 0.0
    not_cost_dependent = cost_dependency_pct <= MAX_COST_DEPENDENCY_PCT
    spread_only_failure = (not survives_costs) and (pf_zero >= min_pf)

    passed = survives_costs and not_cost_dependent
    metrics = {
        "profit_factor_with_spread": round(pf_spread, 3),
        "profit_factor_zero_spread": round(pf_zero, 3),
        "cost_dependency_pct": round(cost_dependency_pct, 1),
        "spread_only_failure": spread_only_failure,
    }
    message = (
        f"PF avec spread={pf_spread:.2f} (seuil {min_pf}), PF sans spread={pf_zero:.2f}, "
        f"dépendance aux coûts={cost_dependency_pct:.0f}% (seuil {MAX_COST_DEPENDENCY_PCT:.0f}%)."
        + (" ATTENTION: edge probablement mangé par le spread." if spread_only_failure else "")
    )
    return passed, metrics, message


def stage_stress_survival(
    hypothesis: Hypothesis, engine: BacktestEngine, price_series: dict[str, list[dict]],
    strategy_params: dict | None = None,
) -> tuple[bool, dict, str]:
    """6e stage, exécuté APRÈS les 5 précédents: la stratégie a déjà prouvé
    qu'elle a un edge statistique — reste à vérifier qu'elle SURVIT à des
    scénarios de choc plausibles (flash crash, gap, spread qui explose,
    changement de régime de volatilité, drawdown prolongé). Philosophie
    Aladdin (BlackRock): juger une stratégie sur sa survie dans le pire cas
    plausible, pas sur son rendement moyen. Pas la peine de stress-tester un
    signal qui n'a même pas d'edge — d'où sa place en dernier."""
    threshold = hypothesis.criteres_echec.get("max_stress_drawdown_pct", DEFAULT_MAX_DRAWDOWN_THRESHOLD_PCT)
    tester = StressTester(max_drawdown_threshold_pct=threshold, engine_class=type(engine), strategy_params=strategy_params)
    report = tester.run_all_scenarios(price_series, engine.config, engine.starting_capital, engine.spread_cost_pct)

    passed = report.survived()
    metrics = {
        "max_drawdown_threshold_pct": threshold,
        "scenarios": {
            s.name: {
                "return_pct": round(s.result.total_return_pct, 2),
                "max_drawdown_pct": round(s.result.max_drawdown_pct, 2),
                "profit_factor": s.result.profit_factor,
                "worst_case_loss_pct": round(s.worst_case_loss_pct, 2),
            }
            for s in report.scenarios
        },
    }
    failing = [
        s.name for s in report.scenarios
        if s.result.max_drawdown_pct > threshold or s.worst_case_loss_pct >= 100.0
    ]
    message = (
        f"Stress test: survit aux 5 scénarios (seuil max_dd {threshold:.0f}%)."
        if passed else
        f"Stress test: échec sur {', '.join(failing)} (seuil max_dd {threshold:.0f}%)."
    )
    return passed, metrics, message
