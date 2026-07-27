"""
PortfolioManager — la vue d'ensemble. Suit toutes les positions, le P&L,
et surveille les positions ouvertes pour détecter TP/SL touchés.

Rôle: maintenir l'état complet du portefeuille en temps réel, publier
des snapshots réguliers pour le dashboard, et fermer les positions
quand un prix touche son stop-loss ou take-profit.
"""

from core.base_agent import BaseAgent
from core.message_bus import MessageBus, Message


class PortfolioManager(BaseAgent):
    def __init__(self, bus: MessageBus, starting_capital: float) -> None:
        super().__init__(name="PortfolioManager", bus=bus)
        self.starting_capital = starting_capital
        self.cash = starting_capital
        self.positions: dict[str, dict] = {}
        self.closed_trades: list[dict] = []
        self._last_prices: dict[str, float] = {}

    async def setup(self) -> None:
        self.bus.subscribe("trade.filled", self._on_trade_filled)
        self.bus.subscribe("market.tick", self._on_tick)

    async def _on_trade_filled(self, msg: Message) -> None:
        p = msg.payload
        self.positions[p["symbol"]] = {
            "side": p["side"],
            "size": p["size"],
            "entry_price": p["fill_price"],
            "stop_loss": p["stop_loss"],
            "take_profit": p["take_profit"],
        }
        await self._publish_snapshot()

    async def _on_tick(self, msg: Message) -> None:
        symbol = msg.payload["symbol"]
        price = msg.payload["price"]
        self._last_prices[symbol] = price
        position = self.positions.get(symbol)
        if not position:
            return

        hit_sl = (position["side"] == "buy" and price <= position["stop_loss"]) or \
                 (position["side"] == "sell" and price >= position["stop_loss"])
        hit_tp = (position["side"] == "buy" and price >= position["take_profit"]) or \
                 (position["side"] == "sell" and price <= position["take_profit"])

        if hit_sl or hit_tp:
            await self._close_position(symbol, price, reason="take_profit" if hit_tp else "stop_loss")

    async def _close_position(self, symbol: str, exit_price: float, reason: str) -> None:
        position = self.positions.pop(symbol, None)
        if not position:
            return

        direction = 1 if position["side"] == "buy" else -1
        pnl = direction * (exit_price - position["entry_price"]) * position["size"]
        self.cash += pnl

        trade_record = {
            "symbol": symbol, "side": position["side"], "size": position["size"],
            "entry_price": position["entry_price"], "exit_price": exit_price,
            "pnl": pnl, "reason": reason,
        }
        self.closed_trades.append(trade_record)

        await self.emit("trade.closed", trade_record)
        await self._publish_snapshot()

    async def _publish_snapshot(self) -> None:
        unrealized = 0.0
        for symbol, p in self.positions.items():
            current_price = self._last_prices.get(symbol, p["entry_price"])
            direction = 1 if p["side"] == "buy" else -1
            unrealized += direction * (current_price - p["entry_price"]) * p["size"]
        await self.emit("portfolio.snapshot", {
            "cash": self.cash,
            "equity": self.cash + unrealized,
            "open_positions": len(self.positions),
            "positions": dict(self.positions),
            "total_closed_trades": len(self.closed_trades),
            "realized_pnl": self.cash - self.starting_capital,
        })
