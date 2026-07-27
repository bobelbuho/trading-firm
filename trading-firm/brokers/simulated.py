"""
Brokers simulés (paper trading) — permettent de tester TOUT le pipeline
(analyse -> signal -> risk -> exécution -> portefeuille) sans connexion
réseau ni argent réel.

Une fois que tu es satisfait des résultats, tu remplaces ces classes par
de vrais connecteurs (ccxt.binance, oandapyV20, alpaca-py...) qui
respectent les mêmes interfaces (MarketDataClient / OrderBroker) — le
reste du système n'a AUCUN changement à faire.
"""

import asyncio
import random
import uuid


class SimulatedMarketDataClient:
    """Génère un flux de prix simulé façon marche aléatoire, pour tester
    les agents sans dépendre d'une vraie exchange."""

    def __init__(self, base_prices: dict[str, float], tick_interval: float = 1.0) -> None:
        self.prices = dict(base_prices)
        self.tick_interval = tick_interval

    async def stream_prices(self, symbol: str):
        price = self.prices.get(symbol, 100.0)
        while True:
            await asyncio.sleep(self.tick_interval)
            change_pct = random.gauss(0, 0.0015)  # petite variation aléatoire
            price = max(0.01, price * (1 + change_pct))
            spread = price * 0.0005
            yield {
                "symbol": symbol,
                "price": price,
                "bid": price - spread / 2,
                "ask": price + spread / 2,
                "volume": random.uniform(10, 1000),
            }


class SimulatedNewsClient:
    """Ne déclenche aucun événement par défaut — utile comme point de
    départ neutre. Tu peux y brancher une vraie API plus tard."""

    async def get_upcoming_events(self, lookahead_minutes: int) -> list[dict]:
        return []

    async def stream_headlines(self):
        while True:
            await asyncio.sleep(3600)
            yield {"title": "placeholder", "sentiment": 0, "symbols": [], "timestamp": None}


class SimulatedBroker:
    """Simule l'exécution d'ordres avec un léger slippage aléatoire."""

    async def place_order(self, symbol: str, side: str, size: float,
                           stop_loss: float, take_profit: float,
                           reference_price: float | None = None) -> dict:
        await asyncio.sleep(0.05)  # latence simulée
        ref = reference_price if reference_price is not None else (stop_loss + take_profit) / 2
        slippage = ref * random.uniform(-0.0003, 0.0003)
        return {
            "order_id": str(uuid.uuid4()),
            "fill_price": ref + slippage,
            "status": "filled",
        }
