"""
example_hypothesis.py — démonstration complète du module research/: du
brouillon d'hypothèse jusqu'au verdict, en respectant chaque garde-fou.

NOTE HONNÊTETÉ: l'hypothèse ci-dessous est formulée comme un arbitrage de
paires cointégrées (BTC/ETH) — un edge de retour à la moyenne avec une
justification économique classique et solide. Mais le moteur de backtest
actuel (BacktestEngine) ne fait QUE du mean-reversion single-asset
(confluence Bollinger+RSI+ADX, voir core/strategy_logic.py) — pas de
trading de spread entre deux actifs. Pour démontrer le PROCESSUS de bout en
bout avec une infrastructure réelle plutôt qu'un mock, on applique donc
cette hypothèse à BTC/USDT seul, en la traitant comme un proxy pédagogique:
la logique de retour à la moyenne (et donc la discipline de validation —
splits, 5 stages, guards anti-surajustement) est structurellement identique
quelle que soit la stratégie sous-jacente. C'est précisément là qu'est la
valeur de ce module: la rigueur du PROCESSUS, indépendante du code de la
stratégie testée.

Usage: python research/example_hypothesis.py
"""

import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backtesting.data_loader import fetch_multiple
from config.settings import FirmConfig
from research.hypotheses.graveyard import Graveyard
from research.hypotheses.hypothesis import Hypothesis, Statut
from research.hypotheses.registry import HypothesisRegistry, IncompleteHypothesisError
from research.overfitting.guards import OverfittingGuard
from research.reports.research_log import ResearchLog
from research.validation.data_split import DataSplit
from research.validation.pipeline import ValidationPipeline


def main() -> None:
    log = ResearchLog()
    registry = HypothesisRegistry(research_log=log)
    graveyard = Graveyard(research_log=log)

    # --- 1. La garde principale: une hypothèse incomplète ne s'enregistre pas ---
    print("=== 1. Tentative d'enregistrement d'une hypothèse INCOMPLÈTE (pour montrer la garde) ===")
    hypothese_bacle = Hypothesis(
        id="BACLE-001",
        nom="Une idée qui a l'air prometteuse sur le graphique",
        raison="",                 # <- volontairement vide: pas de raison économique
        prediction="Ça va monter",
        criteres_echec={},        # <- volontairement vide: aucun seuil défini à l'avance
        donnees_test="",          # <- volontairement vide: pas de tranche réservée
    )
    try:
        registry.register(hypothese_bacle)
        print("ERREUR: n'aurait jamais dû s'enregistrer !")
    except IncompleteHypothesisError as e:
        print(f"Rejetée comme attendu: {e}")
    print()

    # --- 2. Avant de formuler une nouvelle idée, vérifier le cimetière ---
    print("=== 2. Vérification du cimetière avant de re-tester une idée similaire ===")
    similaires = graveyard.search_similar("mean reversion cointégration retour moyenne")
    print(f"{len(similaires)} hypothèse(s) similaire(s) déjà enterrée(s) trouvée(s).")
    print()

    # --- 3. Une hypothèse BIEN formée ---
    print("=== 3. Enregistrement de l'hypothèse bien formée ===")
    hypothese = Hypothesis(
        id="PAIRS-COINT-BTC-ETH-001",
        nom="Arbitrage de paires cointégrées BTC/ETH (retour à la moyenne du spread)",
        raison=(
            "BTC et ETH partagent un flux d'ordres et une base d'investisseurs largement "
            "commune (corrélation historique >0.85), ce qui les rend structurellement "
            "cointégrés à moyen terme: leur ratio de prix oscille autour d'un équilibre de "
            "long terme. Des chocs de liquidité asymétriques (liquidations en cascade sur un "
            "seul des deux actifs, rotation sectorielle, actualité spécifique à un projet) "
            "créent des écarts temporaires à cet équilibre, qui se résorbent mécaniquement une "
            "fois la pression de flux dissipée — car aucun changement fondamental durable ne "
            "justifie une désynchronisation permanente entre les deux plus grandes "
            "cryptomonnaies liquides. C'est un edge de retour à la moyenne, pas une prédiction "
            "directionnelle."
        ),
        prediction=(
            "Après un écart statistiquement significatif entre le prix et sa moyenne mobile "
            "(mesuré ici, en simplification pédagogique, via la confluence Bollinger+RSI+ADX "
            "sur BTC/USDT plutôt que sur le spread BTC/ETH), le prix devrait revenir vers sa "
            "moyenne dans un horizon de quelques heures à quelques jours, générant un profit "
            "factor > 1 net des coûts de transaction."
        ),
        criteres_echec={
            "profit_factor_min": 1.1,
            "win_rate_min": 38.0,
            "max_drawdown_max": 15.0,
            "coherence_min": 60.0,
            "max_degradation_pct": 50.0,
        },
        donnees_test="20% les plus récentes de 60 jours de bougies 5min BTC/USDT (split chronologique, aucun mélange)",
    )
    registry.register(hypothese)
    print(f"Hypothèse '{hypothese.id}' enregistrée (statut: {hypothese.statut.value}).")
    print()

    # --- 4. Données réelles + split train/test (chronologique, verrouillable) ---
    print("=== 4. Téléchargement des données et split train/test ===")
    price_series = fetch_multiple(["BTC/USDT"], interval="5m", period="60d")
    print(f"BTC/USDT: {len(price_series['BTC/USDT'])} bougies récupérées.")

    data_split = DataSplit()
    train_data, test_data = data_split.split(price_series, test_ratio=0.2)
    for symbol in price_series:
        print(f"  {symbol}: train={len(train_data[symbol])} bougies, test={len(test_data[symbol])} bougies (réservées)")
    print()

    # --- 5. Garde anti-p-hacking: budget d'essais + pénalité de complexité ---
    print("=== 5. Garde anti-surajustement (avant de lancer le pipeline) ===")
    guard = OverfittingGuard()
    param_variations = [
        {"rsi_oversold": 33, "rsi_overbought": 67},
        {"rsi_oversold": 37, "rsi_overbought": 63},
        {"adx_max": 20.0},
        {"adx_max": 30.0},
    ]
    for _ in param_variations:
        guard.record_trial(hypothese.id)
    within_budget = guard.check_trial_budget(hypothese.id, max_trials=20)
    print(f"Essais enregistrés: {guard.trials_count[hypothese.id]} (budget respecté: {within_budget})")
    print(f"Pénalité de complexité pour 2 paramètres (rsi_oversold/rsi_overbought): x{guard.complexity_penalty(2):.2f}")
    print(f"Pénalité de complexité pour 4 paramètres (si on ajoutait 2 réglages ADX): x{guard.complexity_penalty(4):.2f}")
    print()

    # --- 6. Le pipeline: 5 stages dans l'ordre, arrêt au premier échec ---
    print("=== 6. Exécution du pipeline de validation ===")
    config = FirmConfig.default()
    pipeline = ValidationPipeline(research_log=log)
    report = pipeline.validate(
        hypothesis=hypothese,
        data_split=data_split,
        risk_config=config.risk,
        starting_capital=config.starting_capital,
        spread_cost_pct=0.0002,
        param_variations=param_variations,
        window_days=15,
    )
    print(report.summary())
    print()

    # --- 7. Verdict: valider ou enterrer ---
    print("=== 7. Application du verdict ===")
    if report.passed:
        registry.update_statut(hypothese.id, Statut.VALIDEE)
        print(f"Hypothèse '{hypothese.id}' -> VALIDEE.")
    else:
        registry.update_statut(hypothese.id, Statut.REJETEE)
        metriques_finales = report.stages[-1].metrics
        graveyard.bury(hypothese, report.recommended_raison, metriques_finales)
        print(f"Hypothèse '{hypothese.id}' -> REJETEE et enterrée: {report.recommended_raison}")
    print()

    # --- 8. Résumé de toute l'activité de recherche ---
    print("=== 8. Résumé du research_log ===")
    print(log.summary())


if __name__ == "__main__":
    main()
