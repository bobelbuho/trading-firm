"""
StrategyAgent — le trader qui génère des signaux d'entrée/sortie.

Rôle: écouter les mises à jour de marché et produire des propositions
de trade. Stratégie: mean reversion par confluence Bollinger + RSI —
un signal n'est émis que si le prix sort des bandes de Bollinger ET
que le RSI confirme l'excès (survente/surachat). La cible de sortie
proposée est le retour à la moyenne (bb_middle).

Ce module NE décide PAS d'exécuter — il propose seulement un signal.
C'est le RiskManager qui a le dernier mot.
"""

from core.base_agent import BaseAgent
from core.message_bus import MessageBus, Message
from core.strategy_logic import generate_signal


class StrategyAgent(BaseAgent):
    def __init__(self, bus: MessageBus, rsi_oversold: float = 35, rsi_overbought: float = 65) -> None:
        super().__init__(name="StrategyAgent", bus=bus)
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought
        self._blacked_out: set[str] = set()

    async def setup(self) -> None:
        self.bus.subscribe("market.tick", self._on_tick)
        self.bus.subscribe("news.blackout", self._on_blackout)

    async def _on_blackout(self, msg: Message) -> None:
        self._blacked_out.add(msg.payload["key"])
        self.logger.warning(f"Trading suspendu sur {msg.payload['key']}: {msg.payload['reason']}")

    async def _on_tick(self, msg: Message) -> None:
        payload = msg.payload
        symbol = payload["symbol"]
        indicators = payload.get("indicators", {})

        if not indicators or symbol in self._blacked_out:
            return

        signal = generate_signal(payload["price"], indicators, self.rsi_oversold, self.rsi_overbought)
        if signal is None:
            return

        await self.emit("signal.new", {"symbol": symbol, **signal})
