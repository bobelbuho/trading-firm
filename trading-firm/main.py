"""
main.py — point d'entrée de la firme de trading.

Assemble tous les agents ("employés"), les connecte au bus de messages
commun, et les lance en parallèle. Démarre en mode PAPER par défaut
avec le broker simulé — voir README.md pour brancher un vrai broker.
"""

import sys

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

import asyncio
import logging
import os

from dotenv import load_dotenv

from core.message_bus import MessageBus
from agents.macro_agent import MacroAgent
from agents.market_data_agent import MarketDataAgent
from agents.news_agent import NewsAgent
from agents.strategy_agent import StrategyAgent
from agents.risk_manager import RiskManager
from agents.execution_agent import ExecutionAgent
from agents.portfolio_manager import PortfolioManager
from agents.supervisor import Supervisor
from agents.validation_agent import ValidationAgent
from brokers.simulated import SimulatedMarketDataClient, SimulatedNewsClient, SimulatedBroker
from config.settings import FirmConfig

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s",
)


async def build_connectors(all_symbols: list[str]):
    """Retourne (market_client, news_client, broker) selon BROKER_MODE."""
    broker_mode = os.getenv("BROKER_MODE", "paper")

    if broker_mode == "avatrade":
        from brokers.avatrade_metaapi import AvaTradeMetaApiConnector

        required = ["METAAPI_TOKEN", "MT5_LOGIN", "MT5_PASSWORD", "MT5_SERVER"]
        missing = [v for v in required if not os.getenv(v)]
        if missing:
            raise RuntimeError(
                f"BROKER_MODE=avatrade mais variables manquantes dans .env: {missing}"
            )

        connector = AvaTradeMetaApiConnector(
            token=os.environ["METAAPI_TOKEN"],
            login=os.environ["MT5_LOGIN"],
            password=os.environ["MT5_PASSWORD"],
            server=os.environ["MT5_SERVER"],
        )
        await connector.connect()
        # Le même objet sert de market_client ET de broker (voir avatrade_metaapi.py)
        return connector, SimulatedNewsClient(), connector

    # Mode par défaut: tout simulé, aucune clé requise
    market_client = SimulatedMarketDataClient(base_prices={s: 100.0 for s in all_symbols})
    return market_client, SimulatedNewsClient(), SimulatedBroker()


async def main() -> None:
    config = FirmConfig.default()
    logging.info(f"Démarrage de la firme en mode: {config.mode.upper()}")

    all_symbols = [s for m in config.markets for s in m.symbols]
    bus = MessageBus()

    market_client, news_client, broker = await build_connectors(all_symbols)

    # --- L'équipe ---
    market_data_agent = MarketDataAgent(bus, market_client, all_symbols)
    news_agent = NewsAgent(
        bus, news_client,
        blackout_before=config.risk.news_blackout_minutes_before,
        blackout_after=config.risk.news_blackout_minutes_after,
    )
    strategy_agent = StrategyAgent(bus)
    risk_manager = RiskManager(bus, config.risk, config.starting_capital)
    execution_agent = ExecutionAgent(bus, broker, mode=config.mode)
    portfolio_manager = PortfolioManager(bus, config.starting_capital)
    supervisor = Supervisor(bus)
    validation_agent = ValidationAgent(bus, config.risk, config.starting_capital)
    macro_agent = MacroAgent(
        bus,
        blackout_before_min=config.risk.news_blackout_minutes_before,
        blackout_after_min=config.risk.news_blackout_minutes_after,
    )

    agents = [
        supervisor, portfolio_manager, risk_manager, validation_agent, macro_agent,
        strategy_agent, news_agent, execution_agent, market_data_agent,
    ]

    for agent in agents:
        await agent.start()

    # Les agents "producteurs" (market data, news, macro) tournent en continu
    await asyncio.gather(
        market_data_agent.run(),
        news_agent.run(),
        macro_agent.run(),
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Arrêt de la firme demandé par l'utilisateur.")
