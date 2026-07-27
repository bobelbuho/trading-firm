"""
ValidationAgent — le contrôleur qualité de la firme. Répond à une demande de
validation ("validation.request") en lançant un backtest walk-forward
(avec et sans spread_cost_pct, sur plusieurs symboles et fenêtres glissantes)
et publie un verdict GO/NO-GO objectif ("validation.result").

Toute la logique de découpage/agrégation/seuils vit dans
backtesting/validation.py (testable indépendamment du bus) — cet agent n'est
qu'une fine couche async qui relie ce module au bus de messages.

NOTE: run_validation() fait des I/O réseau bloquants (yfinance) et des
boucles CPU-bound sur des dizaines de milliers de bougies — ça peut prendre
plusieurs minutes. Exécuté directement dans le handler, ça gèlerait toute la
boucle d'événements (MarketDataAgent, RiskManager, etc. seraient bloqués
pendant la validation). D'où asyncio.to_thread: la validation tourne dans un
thread séparé, le reste de la firme continue à fonctionner normalement.
"""

import asyncio
import uuid

from backtesting.validation import (
    DEFAULT_INTERVAL,
    DEFAULT_SPREAD_COST_PCT,
    DEFAULT_TOTAL_PERIOD_DAYS,
    DEFAULT_WINDOW_DAYS,
    run_validation,
)
from config.settings import RiskConfig
from core.base_agent import BaseAgent
from core.message_bus import MessageBus, Message


class ValidationAgent(BaseAgent):
    def __init__(self, bus: MessageBus, risk_config: RiskConfig, starting_capital: float) -> None:
        super().__init__(name="ValidationAgent", bus=bus)
        self.risk_config = risk_config
        self.starting_capital = starting_capital

    async def setup(self) -> None:
        self.bus.subscribe("validation.request", self._on_request)

    async def _on_request(self, msg: Message) -> None:
        p = msg.payload
        request_id = p.get("request_id") or str(uuid.uuid4())
        self.logger.info(f"Validation demandée (request_id={request_id}): symbols={p.get('symbols')}")

        try:
            report = await asyncio.to_thread(
                run_validation,
                symbols=p.get("symbols"),
                interval=p.get("interval", DEFAULT_INTERVAL),
                total_period_days=p.get("total_period_days", DEFAULT_TOTAL_PERIOD_DAYS),
                window_days=p.get("window_days", DEFAULT_WINDOW_DAYS),
                risk_config=self.risk_config,
                starting_capital=self.starting_capital,
                spread_cost_pct=p.get("spread_cost_pct", DEFAULT_SPREAD_COST_PCT),
            )
        except Exception as e:
            self.logger.error(f"Validation échouée (request_id={request_id}): {e}")
            await self.emit("validation.result", {"request_id": request_id, "verdict": "ERROR", "error": str(e)})
            return

        self.logger.info(f"Validation terminée (request_id={request_id}): verdict={report.verdict}")
        await self.emit("validation.result", {"request_id": request_id, **report.to_dict()})
