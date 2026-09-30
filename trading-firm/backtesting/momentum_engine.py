"""
momentum_engine.py — moteur de backtest pour la stratégie de suivi de
tendance (core/momentum_logic.py), structurellement différent du moteur
mean reversion (backtesting/engine.py): la sortie se fait au CROISEMENT
INVERSE des moyennes mobiles (on reste dans le trade tant que la tendance
dure), pas à un stop-loss/take-profit fixe basé sur la distance d'entrée.

Un stop de sécurité basé sur la volatilité récente (même formule que
core/risk_logic.compute_stop_distance_pct) limite quand même les pertes
catastrophiques si la tendance se retourne violemment avant le prochain
croisement — il est vérifié intra-bougie (high/low) comme dans le moteur
principal, avec le même remplissage conscient des gaps.

Réutilise BacktestTrade/BacktestResult (backtesting/engine.py) et
core/risk_logic.py (sizing, distance de stop) — seule la logique
d'entrée/sortie change, aucune logique de risque n'est dupliquée.
"""

from datetime import datetime

from backtesting.engine import BacktestResult, BacktestTrade
from config.settings import RiskConfig
from core.indicators import volatility as compute_volatility
from core.momentum_logic import generate_momentum_signal
from core.risk_logic import compute_position_size, compute_stop_distance_pct


class MomentumBacktestEngine:
    def __init__(
        self, config: RiskConfig, starting_capital: float = 10_000.0, spread_cost_pct: float = 0.0002,
        fast_period: int = 20, slow_period: int = 50,
    ) -> None:
        self.config = config
        self.starting_capital = starting_capital
        self.spread_cost_pct = spread_cost_pct
        self.fast_period = fast_period
        self.slow_period = slow_period

    def run(self, price_series: dict[str, list[dict]]) -> BacktestResult:
        timeline = sorted(
            ((bar["timestamp"], symbol, bar) for symbol, bars in price_series.items() for bar in bars),
            key=lambda event: event[0],
        )

        bar_history: dict[str, list[dict]] = {symbol: [] for symbol in price_series}
        last_price: dict[str, float] = {}
        open_positions: dict[str, dict] = {}
        cash = self.starting_capital
        trades: list[BacktestTrade] = []
        equity_curve: list[tuple[datetime, float]] = []

        for timestamp, symbol, bar in timeline:
            bar_history[symbol].append(bar)
            price = bar["close"]
            last_price[symbol] = price
            bars = bar_history[symbol]

            position = open_positions.get(symbol)

            # --- Stop de sécurité (intra-bougie, high/low) ---
            if position is not None:
                side = position["side"]
                hit_stop = (
                    bar["low"] <= position["stop_loss"] if side == "buy"
                    else bar["high"] >= position["stop_loss"]
                )
                if hit_stop:
                    exit_price = self._gapped_fill_price(bar, side, position["stop_loss"])
                    cash += self._close_position(position, symbol, exit_price, timestamp, "stop_loss", trades)
                    del open_positions[symbol]
                    position = None

            # --- Signal momentum: sortie au croisement inverse, entrée au croisement ---
            if len(bars) >= self.slow_period + 1:
                signal = generate_momentum_signal(bars, self.fast_period, self.slow_period)
                if signal is not None:
                    if position is not None and position["side"] != signal["side"]:
                        cash += self._close_position(position, symbol, price, timestamp, "signal_inverse", trades)
                        del open_positions[symbol]
                        position = None

                    if position is None:
                        vol = compute_volatility(bars, 20)
                        signal["indicators"]["volatility"] = vol
                        size = compute_position_size(signal, self.starting_capital, self.config)
                        stop_distance = price * compute_stop_distance_pct(price, vol)
                        stop_loss = price - stop_distance if signal["side"] == "buy" else price + stop_distance
                        entry_price = self._apply_spread(price, signal["side"], closing=False)
                        open_positions[symbol] = {
                            "side": signal["side"], "size": size, "entry_price": entry_price,
                            "stop_loss": stop_loss, "entry_time": timestamp,
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

    def _apply_spread(self, price: float, side: str, closing: bool) -> float:
        direction = 1 if side == "buy" else -1
        if closing:
            direction = -direction
        return price * (1 + direction * self.spread_cost_pct)

    @staticmethod
    def _gapped_fill_price(bar: dict, side: str, level: float) -> float:
        """Même logique que BacktestEngine._gapped_fill_price: si la bougie a
        ouvert au-delà du stop (gap), le fill se fait au prix réel
        d'ouverture (pire que le niveau théorique)."""
        open_price = bar["open"]
        return min(open_price, level) if side == "buy" else max(open_price, level)

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
