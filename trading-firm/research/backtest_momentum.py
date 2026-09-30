"""
backtest_momentum.py — backtest exploratoire de la stratégie momentum
(croisement de moyennes mobiles, core/momentum_logic.py +
backtesting/momentum_engine.py) sur des actifs qui TENDENT (or, BTC), en
comparaison avec une paire range (EUR/GBP) où le momentum devrait au
contraire mal fonctionner.

Mesure exploratoire — ne construit AUCUNE hypothèse formelle, n'enterre
rien. Juste un premier signal pour savoir si ça vaut le coup d'aller plus
loin.

Usage: python research/backtest_momentum.py
"""

import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backtesting.data_loader import fetch_multiple
from backtesting.momentum_engine import MomentumBacktestEngine
from config.settings import FirmConfig

# XAU/USD (GC=F) et BTC/USDT (BTC-USD): actifs qui tendent, terrain visé par
# le momentum. EUR/GBP: paire range, terrain défavorable au momentum -
# incluse pour comparaison (on s'attend à ce qu'elle performe moins bien ici).
SYMBOLS = ["XAU/USD", "BTC/USDT", "EUR/GBP"]


def _win_loss_stats(result) -> tuple[float, float]:
    wins = [t.pnl for t in result.trades if t.pnl > 0]
    losses = [t.pnl for t in result.trades if t.pnl <= 0]
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0
    return avg_win, avg_loss


def _print_result(label: str, result) -> None:
    avg_win, avg_loss = _win_loss_stats(result)
    pf = "inf" if result.profit_factor == float("inf") else f"{result.profit_factor:.2f}"
    print(
        f"  {label:12s} trades={len(result.trades):4d}  win_rate={result.win_rate_pct:5.1f}%  "
        f"PF={pf:>5s}  rendement={result.total_return_pct:+7.2f}%  "
        f"gain_moy={avg_win:+9.2f}  perte_moy={avg_loss:+9.2f}"
    )


def main() -> None:
    config = FirmConfig.default()

    for symbol in SYMBOLS:
        print(f"\n=== {symbol} (daily, période max) — momentum MM20/MM50 ===")
        price_series = fetch_multiple([symbol], interval="1d", period="max")
        print(f"  {len(price_series[symbol])} bougies récupérées")

        engine_spread = MomentumBacktestEngine(config.risk, config.starting_capital, spread_cost_pct=0.0002)
        engine_zero = MomentumBacktestEngine(config.risk, config.starting_capital, spread_cost_pct=0.0)

        result_spread = engine_spread.run(price_series)
        result_zero = engine_zero.run(price_series)

        _print_result("avec spread", result_spread)
        _print_result("sans spread", result_zero)


if __name__ == "__main__":
    main()
