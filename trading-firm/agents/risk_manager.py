"""
RiskManager — le gardien de la firme. AUCUN trade ne passe sans son accord.

Rôle: recevoir les signaux du StrategyAgent, les confronter aux règles
de risque (taille de position, exposition, drawdown journalier,
kill-switch), et soit approuver (avec un sizing calculé), soit rejeter.

C'est délibérément l'agent le plus "paranoïaque" du système. En scalping,
la vitesse de génération des trades veut dire que les erreurs de risk
management composent très vite.
"""

from datetime import datetime, timezone

from core.base_agent import BaseAgent
from core.message_bus import MessageBus, Message
from core.risk_logic import compute_position_size, compute_stops
from config.settings import RiskConfig


class RiskManager(BaseAgent):
    def __init__(self, bus: MessageBus, config: RiskConfig, starting_capital: float) -> None:
        super().__init__(name="RiskManager", bus=bus)
        self.config = config
        self.capital = starting_capital
        self.equity = starting_capital

        self._open_positions: dict[str, dict] = {}   # symbol -> {side, size, entry_price}
        self._daily_pnl = 0.0
        self._daily_pnl_reset_date = datetime.now(timezone.utc).date()
        self._blacked_out: set[str] = set()
        self._kill_switch_active = False

    async def setup(self) -> None:
        self.bus.subscribe("signal.new", self._on_signal)
        self.bus.subscribe("trade.filled", self._on_trade_filled)
        self.bus.subscribe("trade.failed", self._on_trade_failed)
        self.bus.subscribe("trade.closed", self._on_trade_closed)
        self.bus.subscribe("news.blackout", self._on_blackout)

    async def _on_blackout(self, msg: Message) -> None:
        self._blacked_out.add(msg.payload["key"])

    async def _on_signal(self, msg: Message) -> None:
        self._maybe_reset_daily_pnl()

        if self._kill_switch_active:
            await self._reject(msg.payload, "Kill-switch actif: perte journalière max atteinte")
            return

        symbol = msg.payload["symbol"]
        side = msg.payload["side"]

        rejection_reason = self._validate(symbol, side)
        if rejection_reason:
            await self._reject(msg.payload, rejection_reason)
            return

        size = compute_position_size(msg.payload, self.capital, self.config)
        stop_loss, take_profit = compute_stops(msg.payload, side, self.config)

        self._open_positions[symbol] = {
            "side": side, "size": size, "entry_price": msg.payload["price"],
        }

        await self.emit("order.approved", {
            **msg.payload,
            "size": size,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "risk_amount": self.capital * (self.config.max_risk_per_trade_pct / 100),
        })

    def _validate(self, symbol: str, side: str) -> str | None:
        if symbol in self._blacked_out:
            return f"Symbole {symbol} en blackout news"

        if len(self._open_positions) >= self.config.max_concurrent_positions:
            return "Nombre max de positions concurrentes atteint"

        if symbol in self._open_positions:
            return f"Position déjà ouverte sur {symbol}"

        exposure_pct = self._current_exposure_pct(symbol)
        if exposure_pct >= self.config.max_exposure_per_symbol_pct:
            return f"Exposition max sur {symbol} déjà atteinte ({exposure_pct:.1f}%)"

        return None

    def _current_exposure_pct(self, symbol: str) -> float:
        total = sum(p["size"] * p["entry_price"] for p in self._open_positions.values())
        return (total / self.capital) * 100 if self.capital else 0.0

    async def _on_trade_filled(self, msg: Message) -> None:
        p = msg.payload
        self._open_positions[p["symbol"]] = {
            "side": p["side"], "size": p["size"], "entry_price": p["fill_price"],
        }

    async def _on_trade_failed(self, msg: Message) -> None:
        self._open_positions.pop(msg.payload["symbol"], None)

    async def _on_trade_closed(self, msg: Message) -> None:
        p = msg.payload
        symbol = p["symbol"]
        pnl = p.get("pnl", 0.0)
        self._daily_pnl += pnl
        self.equity += pnl
        self._open_positions.pop(symbol, None)

        daily_loss_pct = -(self._daily_pnl / self.capital) * 100 if self._daily_pnl < 0 else 0
        if daily_loss_pct >= self.config.max_daily_loss_pct:
            self._kill_switch_active = True
            await self.emit("firm.kill_switch", {
                "reason": f"Perte journalière de {daily_loss_pct:.1f}% atteinte (limite: {self.config.max_daily_loss_pct}%)",
                "daily_pnl": self._daily_pnl,
            })

    def _maybe_reset_daily_pnl(self) -> None:
        today = datetime.now(timezone.utc).date()
        if today != self._daily_pnl_reset_date:
            self._daily_pnl = 0.0
            self._daily_pnl_reset_date = today
            self._kill_switch_active = False
            self.logger.info("Reset du PnL journalier et du kill-switch.")

    async def _reject(self, signal: dict, reason: str) -> None:
        self.logger.info(f"Signal rejeté ({signal['symbol']} {signal['side']}): {reason}")
        await self.emit("order.rejected", {**signal, "reason": reason})
