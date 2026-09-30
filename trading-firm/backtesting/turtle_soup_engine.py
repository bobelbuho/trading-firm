"""
turtle_soup_engine.py — moteur de backtest pour la stratégie Turtle Soup
(core/turtle_soup_logic.py). Particularité par rapport aux moteurs
existants: l'ENTRÉE ne se fait PAS à la clôture de la bougie de signal, mais
à l'OUVERTURE de la bougie SUIVANTE — le faux breakout n'est confirmé qu'à
la clôture, donc on ne peut agir qu'au prochain prix réellement disponible.
Le stop-loss et le take-profit sont des niveaux FIXES calculés par le signal
lui-même (pas estimés via la volatilité comme dans core/risk_logic.py),
puisque cette stratégie a des règles de stop/RR objectives et exactes.

Réutilise BacktestTrade/BacktestResult (backtesting/engine.py) — le fix
intra-bougie (high/low + remplissage conscient des gaps) est repris à
l'identique, CRUCIAL ici puisque toute la logique d'entrée dépend des
high/low des bougies, pas seulement des clôtures.
"""

from datetime import datetime

from backtesting.engine import BacktestResult, BacktestTrade
from config.settings import RiskConfig
from core.turtle_soup_logic import generate_turtle_soup_signal


class TurtleSoupBacktestEngine:
    def __init__(
        self, config: RiskConfig, starting_capital: float = 10_000.0, spread_cost_pct: float = 0.0002,
        lookback: int = 20, rr: float = 2.0,
    ) -> None:
        self.config = config
        self.starting_capital = starting_capital
        self.spread_cost_pct = spread_cost_pct
        self.lookback = lookback
        self.rr = rr

    def run(self, price_series: dict[str, list[dict]]) -> BacktestResult:
        timeline = sorted(
            ((bar["timestamp"], symbol, bar) for symbol, bars in price_series.items() for bar in bars),
            key=lambda event: event[0],
        )

        bar_history: dict[str, list[dict]] = {symbol: [] for symbol in price_series}
        last_price: dict[str, float] = {}
        open_positions: dict[str, dict] = {}
        pending_entries: dict[str, dict] = {}   # entrée détectée, exécutée à l'ouverture du bar suivant
        cash = self.starting_capital
        trades: list[BacktestTrade] = []
        equity_curve: list[tuple[datetime, float]] = []

        for timestamp, symbol, bar in timeline:
            bar_history[symbol].append(bar)
            last_price[symbol] = bar["close"]

            position = open_positions.get(symbol)

            # --- Exécution d'une entrée en attente, à l'OUVERTURE de cette bougie ---
            pending = pending_entries.pop(symbol, None)
            if pending is not None and position is None:
                side = pending["side"]
                entry_price = self._apply_spread(bar["open"], side, closing=False)
                size = self._position_size(entry_price, pending["stop_loss"])
                open_positions[symbol] = {
                    "side": side, "size": size, "entry_price": entry_price,
                    "stop_loss": pending["stop_loss"], "take_profit": pending["take_profit"],
                    "entry_time": timestamp,
                }
                position = open_positions[symbol]

            # --- Stop-loss / take-profit (intra-bougie, high/low, gap-aware) ---
            if position is not None:
                side = position["side"]
                if side == "buy":
                    hit_sl = bar["low"] <= position["stop_loss"]
                    hit_tp = bar["high"] >= position["take_profit"]
                else:
                    hit_sl = bar["high"] >= position["stop_loss"]
                    hit_tp = bar["low"] <= position["take_profit"]

                if hit_sl or hit_tp:
                    reason = "stop_loss" if hit_sl else "take_profit"
                    level = position["stop_loss"] if hit_sl else position["take_profit"]
                    exit_price = self._gapped_fill_price(bar, side, reason, level)
                    cash += self._close_position(position, symbol, exit_price, timestamp, reason, trades)
                    del open_positions[symbol]
                    position = None

            # --- Détection d'un nouveau signal: place une entrée en attente pour le PROCHAIN bar ---
            if position is None and symbol not in pending_entries and len(bar_history[symbol]) >= self.lookback + 1:
                signal = generate_turtle_soup_signal(bar_history[symbol], self.lookback, self.rr)
                if signal is not None:
                    pending_entries[symbol] = {
                        "side": signal["side"],
                        "stop_loss": signal["stop_loss"],
                        "take_profit": signal["take_profit"],
                    }

            equity = cash + sum(
                self._unrealized_pnl(p, last_price[s]) for s, p in open_positions.items()
            )
            equity_curve.append((timestamp, equity))

        final_timestamp = timeline[-1][0] if timeline else None
        for symbol, position in list(open_positions.items()):
            cash += self._close_position(
                position, symbol, last_price[symbol], final_timestamp, "fin_backtest", trades,
            )
        open_positions.clear()
        if final_timestamp is not None:
            equity_curve.append((final_timestamp, cash))

        final_equity = equity_curve[-1][1] if equity_curve else self.starting_capital
        return BacktestResult(
            trades=trades, equity_curve=equity_curve,
            starting_capital=self.starting_capital, final_equity=final_equity,
        )

    def _position_size(self, entry_price: float, stop_loss: float) -> float:
        """Turtle Soup a un stop-loss EXACT (le high/low de la bougie de
        faux breakout), pas estimé via la volatilité — le sizing se fait
        donc directement à partir de la vraie distance de stop plutôt que
        via core/risk_logic.compute_position_size, qui clampe une distance
        ESTIMÉE entre 0.1% et 2% (un cadre pensé pour un stop approximatif,
        pas pour un niveau exact connu à l'avance)."""
        risk_amount = self.starting_capital * (self.config.max_risk_per_trade_pct / 100)
        stop_distance = abs(entry_price - stop_loss)
        size = risk_amount / stop_distance if stop_distance > 0 else 0.0

        max_notional = self.starting_capital * (self.config.max_exposure_per_symbol_pct / 100)
        if entry_price > 0:
            size = min(size, max_notional / entry_price)
        return round(size, 6)

    def _apply_spread(self, price: float, side: str, closing: bool) -> float:
        direction = 1 if side == "buy" else -1
        if closing:
            direction = -direction
        return price * (1 + direction * self.spread_cost_pct)

    @staticmethod
    def _gapped_fill_price(bar: dict, side: str, reason: str, level: float) -> float:
        open_price = bar["open"]
        if reason == "stop_loss":
            return min(open_price, level) if side == "buy" else max(open_price, level)
        return max(open_price, level) if side == "buy" else min(open_price, level)

    @staticmethod
    def _unrealized_pnl(position: dict, current_price: float) -> float:
        direction = 1 if position["side"] == "buy" else -1
        return direction * (current_price - position["entry_price"]) * position["size"]

    def _close_position(self, position: dict, symbol: str, exit_price_raw: float, timestamp: datetime,
                         reason: str, trades: list[BacktestTrade]) -> float:
        exit_price = self._apply_spread(exit_price_raw, position["side"], closing=True)
        pnl = self._unrealized_pnl(position, exit_price)
        trades.append(BacktestTrade(
            symbol=symbol, side=position["side"], entry_price=position["entry_price"],
            exit_price=exit_price, size=position["size"], pnl=pnl,
            entry_time=position["entry_time"], exit_time=timestamp, exit_reason=reason,
        ))
        return pnl
