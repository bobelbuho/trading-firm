"""
MarketDataAgent — l'analyste qui surveille les prix en continu.

Rôle: se connecter aux exchanges/brokers, récupérer les ticks/bougies en
temps réel, calculer les indicateurs techniques de base, et publier
chaque mise à jour sur le bus pour que les stratégies puissent réagir.

Les ticks bruts sont agrégés en bougies OHLC (1 minute) avant tout calcul
d'indicateur — l'ADX a besoin de high/low, pas juste d'un prix de clôture.

NOTE: Le client broker réel (ccxt, MT5, alpaca-py...) est injecté depuis
l'extérieur (voir brokers/) pour que cet agent reste testable sans
connexion réseau.
"""

import asyncio
from datetime import datetime, timezone
from typing import Protocol

from core.bar_aggregator import TickBarAggregator
from core.base_agent import BaseAgent
from core.indicators import compute_indicators
from core.message_bus import MessageBus


class MarketDataClient(Protocol):
    """Interface que doit respecter n'importe quel connecteur broker."""

    async def stream_prices(self, symbol: str):
        """Doit yield des dicts {symbol, price, volume, timestamp, bid, ask}."""
        ...


class MarketDataAgent(BaseAgent):
    def __init__(self, bus: MessageBus, client: MarketDataClient, symbols: list[str]) -> None:
        super().__init__(name="MarketDataAgent", bus=bus)
        self.client = client
        self.symbols = symbols
        self._aggregators = {s: TickBarAggregator(timeframe_seconds=60) for s in symbols}
        self._bar_history: dict[str, list[dict]] = {s: [] for s in symbols}
        self._history_maxlen = 200

    async def setup(self) -> None:
        # Cet agent n'écoute rien, il produit — pas d'abonnement nécessaire.
        pass

    async def run(self) -> None:
        """Lance un flux par symbole en parallèle."""
        await asyncio.gather(*(self._stream_symbol(s) for s in self.symbols))

    async def _stream_symbol(self, symbol: str) -> None:
        aggregator = self._aggregators[symbol]
        last_meta = {"bid": None, "ask": None, "volume": None}

        async for tick in self.client.stream_prices(symbol):
            timestamp = tick.get("timestamp") or datetime.now(timezone.utc)
            finished_bar = aggregator.add_tick(tick["price"], timestamp)

            if finished_bar is not None:
                self._update_history(symbol, finished_bar)
                indicators = compute_indicators(self._bar_history[symbol])
                bid, ask = last_meta["bid"], last_meta["ask"]

                await self.emit("market.tick", {
                    "symbol": symbol,
                    "price": finished_bar["close"],
                    "bid": bid,
                    "ask": ask,
                    "volume": last_meta["volume"],
                    "spread": (ask - bid) if ask is not None and bid is not None else None,
                    "indicators": indicators,
                })

            last_meta = {"bid": tick.get("bid"), "ask": tick.get("ask"), "volume": tick.get("volume")}

    def _update_history(self, symbol: str, bar: dict) -> None:
        hist = self._bar_history[symbol]
        hist.append(bar)
        if len(hist) > self._history_maxlen:
            hist.pop(0)
