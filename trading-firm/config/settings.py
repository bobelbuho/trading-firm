"""
Configuration centrale de la firme.

IMPORTANT: ne jamais mettre de vraies clés API en dur ici.
Utiliser un fichier .env (voir .env.example) chargé via python-dotenv.
"""

import os
from dataclasses import dataclass, field


@dataclass
class RiskConfig:
    """Les règles du Risk Manager. C'est le module le plus important de toute la firme."""

    max_risk_per_trade_pct: float = 0.5       # % du capital risqué max par trade
    max_daily_loss_pct: float = 3.0            # kill-switch si atteint dans la journée
    max_concurrent_positions: int = 5
    max_exposure_per_symbol_pct: float = 15.0   # % du capital max sur un seul actif
    max_correlated_exposure_pct: float = 25.0   # exposition max sur des actifs corrélés
    min_risk_reward_ratio: float = 1.5
    trading_halt_on_high_impact_news: bool = True
    news_blackout_minutes_before: int = 15
    news_blackout_minutes_after: int = 15

    # --- Couche macro défensive (agents/macro_agent.py) ---
    # Principe: le régime macro ne rend JAMAIS le RiskManager plus agressif,
    # seulement plus prudent (ou neutre en régime "calme"). Ces réglages ne
    # servent qu'à réduire ou bloquer, jamais à augmenter le risque pris.
    halt_on_stress_regime: bool = True          # bloque toute nouvelle position en régime "stress"
    stress_regime_size_factor: float = 0.5      # sinon (halt désactivé), facteur appliqué à la taille en "stress"
    prudence_regime_size_factor: float = 0.75   # facteur appliqué à la taille en régime "prudence"


@dataclass
class MarketConfig:
    name: str                      # ex: "crypto", "forex", "actions"
    enabled: bool = True
    symbols: list[str] = field(default_factory=list)
    broker: str = ""                # ex: "binance", "oanda", "alpaca"
    paper_mode: bool = True         # IMPORTANT: reste True tant que non validé


@dataclass
class FirmConfig:
    mode: str = "paper"             # "paper" ou "live" — flag global, priorité absolue
    starting_capital: float = 10_000.0
    risk: RiskConfig = field(default_factory=RiskConfig)
    markets: list[MarketConfig] = field(default_factory=list)

    @staticmethod
    def default() -> "FirmConfig":
        return FirmConfig(
            mode=os.getenv("FIRM_MODE", "paper"),
            markets=[
                MarketConfig(name="crypto", symbols=["BTC/USDT", "ETH/USDT"], broker="binance"),
                MarketConfig(name="forex", symbols=["EUR/USD", "GBP/USD"], broker="oanda"),
                MarketConfig(name="actions", symbols=["AAPL", "TSLA"], broker="alpaca"),
            ],
        )
