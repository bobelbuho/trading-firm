"""
Moteur de backtesting — rejoue une stratégie sur un historique de prix,
en réutilisant EXACTEMENT la même logique d'indicateurs, de signal et de
risk management que le système live (core/indicators.py, core/strategy_logic.py,
core/risk_logic.py), pour que les résultats soient représentatifs.
"""

from dataclasses import dataclass
from datetime import datetime

from config.settings import RiskConfig
from core.indicators import compute_indicators
from core.risk_logic import compute_position_size, compute_stops
from core.strategy_logic import generate_signal

# Regroupement par corrélation, miroir des marchés définis dans FirmConfig
# (crypto / forex / actions) — utilisé pour plafonner l'exposition combinée
# sur des actifs qui bougent ensemble.
_CORRELATION_GROUPS = {
    "BTC/USDT": "crypto", "ETH/USDT": "crypto",
    "EUR/USD": "forex", "GBP/USD": "forex",
    "AAPL": "actions", "TSLA": "actions",
}


def _correlation_group(symbol: str) -> str:
    return _CORRELATION_GROUPS.get(symbol, symbol)


@dataclass
class BacktestTrade:
    symbol: str
    side: str
    entry_price: float
    exit_price: float
    size: float
    pnl: float
    entry_time: datetime
    exit_time: datetime
    exit_reason: str


@dataclass
class BacktestResult:
    trades: list[BacktestTrade]
    equity_curve: list[tuple[datetime, float]]
    starting_capital: float
    final_equity: float

    @property
    def total_return_pct(self) -> float:
        if not self.starting_capital:
            return 0.0
        return (self.final_equity - self.starting_capital) / self.starting_capital * 100

    @property
    def win_rate_pct(self) -> float:
        if not self.trades:
            return 0.0
        wins = sum(1 for t in self.trades if t.pnl > 0)
        return wins / len(self.trades) * 100

    @property
    def profit_factor(self) -> float:
        gross_profit = sum(t.pnl for t in self.trades if t.pnl > 0)
        gross_loss = -sum(t.pnl for t in self.trades if t.pnl < 0)
        if gross_loss == 0:
            return float("inf") if gross_profit > 0 else 0.0
        return gross_profit / gross_loss

    @property
    def max_drawdown_pct(self) -> float:
        if not self.equity_curve:
            return 0.0
        peak = self.equity_curve[0][1]
        max_dd = 0.0
        for _, equity in self.equity_curve:
            peak = max(peak, equity)
            if peak > 0:
                max_dd = max(max_dd, (peak - equity) / peak * 100)
        return max_dd

    def summary(self) -> str:
        pf = "inf" if self.profit_factor == float("inf") else f"{self.profit_factor:.2f}"
        return "\n".join([
            "=== Résultat du backtest ===",
            f"Capital initial   : {self.starting_capital:,.2f}",
            f"Equity finale     : {self.final_equity:,.2f}",
            f"Rendement total   : {self.total_return_pct:+.2f}%",
            f"Nombre de trades  : {len(self.trades)}",
            f"Taux de réussite  : {self.win_rate_pct:.1f}%",
            f"Profit factor     : {pf}",
            f"Max drawdown      : {self.max_drawdown_pct:.2f}%",
        ])


class BacktestEngine:
    def __init__(
        self, config: RiskConfig, starting_capital: float = 10_000.0, spread_cost_pct: float = 0.0002,
        rsi_oversold: float = 35, rsi_overbought: float = 65, adx_max: float = 25.0,
    ) -> None:
        self.config = config
        self.starting_capital = starting_capital
        self.spread_cost_pct = spread_cost_pct
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought
        self.adx_max = adx_max

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
            indicators = compute_indicators(bar_history[symbol])

            position = open_positions.get(symbol)
            if position is not None:
                side = position["side"]
                if side == "buy":
                    hit_sl = bar["low"] <= position["stop_loss"]
                    hit_tp = bar["high"] >= position["take_profit"]
                else:
                    hit_sl = bar["high"] >= position["stop_loss"]
                    hit_tp = bar["low"] <= position["take_profit"]

                if hit_sl or hit_tp:
                    # Le stop-loss prime en cas d'ambiguïté (les deux touchés dans la
                    # même bougie) — convention conservatrice standard en backtesting
                    # bar-based, où l'ordre exact des touches intra-bougie est inconnu.
                    reason = "stop_loss" if hit_sl else "take_profit"
                    level = position["stop_loss"] if hit_sl else position["take_profit"]
                    exit_price = self._gapped_fill_price(bar, side, reason, level)
                    cash += self._close_position(position, symbol, exit_price, timestamp, reason, trades)
                    del open_positions[symbol]
                    position = None

            if position is None and indicators:
                signal = generate_signal(price, indicators, self.rsi_oversold, self.rsi_overbought, self.adx_max)
                if signal is not None and self._can_open(symbol, open_positions):
                    size = compute_position_size(signal, self.starting_capital, self.config)
                    stop_loss, take_profit = compute_stops(signal, signal["side"], self.config)
                    entry_price = self._apply_spread(price, signal["side"], closing=False)
                    open_positions[symbol] = {
                        "side": signal["side"], "size": size, "entry_price": entry_price,
                        "stop_loss": stop_loss, "take_profit": take_profit, "entry_time": timestamp,
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

    def _can_open(self, symbol: str, open_positions: dict[str, dict]) -> bool:
        if symbol in open_positions:
            return False
        if len(open_positions) >= self.config.max_concurrent_positions:
            return False

        group = _correlation_group(symbol)
        group_notional = sum(
            p["size"] * p["entry_price"] for s, p in open_positions.items() if _correlation_group(s) == group
        )
        group_exposure_pct = (group_notional / self.starting_capital) * 100 if self.starting_capital else 0.0
        if group_exposure_pct >= self.config.max_correlated_exposure_pct:
            return False

        return True

    def _apply_spread(self, price: float, side: str, closing: bool) -> float:
        """Le spread joue toujours contre le trader: à l'entrée le fill est
        décalé dans le sens de la position, à la sortie dans le sens inverse."""
        direction = 1 if side == "buy" else -1
        if closing:
            direction = -direction
        return price * (1 + direction * self.spread_cost_pct)

    @staticmethod
    def _gapped_fill_price(bar: dict, side: str, reason: str, level: float) -> float:
        """Si la bougie a ouvert au-delà du niveau (gap), le fill se fait au
        prix réel d'ouverture — potentiellement bien pire (stop-loss) ou
        meilleur (take-profit) que le niveau théorique, qui n'aurait jamais
        été réellement disponible. Sinon, fill au niveau lui-même (touché
        en cours de bougie, prix supposé disponible)."""
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
