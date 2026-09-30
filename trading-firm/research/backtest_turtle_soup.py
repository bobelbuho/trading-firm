"""
backtest_turtle_soup.py — backtest exploratoire de la stratégie Turtle Soup
(core/turtle_soup_logic.py + backtesting/turtle_soup_engine.py) sur plusieurs
actifs, deux ratios risque/récompense (RR 1:1 et 1:2), en daily et horaire.

Mesure exploratoire — ne construit AUCUNE hypothèse formelle, n'enterre
rien. Sert uniquement à décider quels actifs méritent d'être passés au
pipeline de validation complet (PF > 1 avec spread).

Usage: python research/backtest_turtle_soup.py
"""

import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backtesting.data_loader import fetch_multiple
from backtesting.turtle_soup_engine import TurtleSoupBacktestEngine
from config.settings import FirmConfig

SYMBOLS = ["XAU/USD", "BTC/USDT", "EUR/USD", "EUR/GBP"]
TIMEFRAMES = [("1d", "max"), ("1h", "730d")]
RR_VALUES = [1.0, 2.0]


def _win_loss_stats(result) -> tuple[float, float, float]:
    wins = [t.pnl for t in result.trades if t.pnl > 0]
    losses = [t.pnl for t in result.trades if t.pnl <= 0]
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0
    ratio = abs(avg_win / avg_loss) if avg_loss else float("inf")
    return avg_win, avg_loss, ratio


def _print_row(label: str, result) -> None:
    avg_win, avg_loss, ratio = _win_loss_stats(result)
    pf = "inf" if result.profit_factor == float("inf") else f"{result.profit_factor:.2f}"
    print(
        f"    {label:14s} trades={len(result.trades):4d}  win_rate={result.win_rate_pct:5.1f}%  "
        f"PF={pf:>5s}  rendement={result.total_return_pct:+7.2f}%  "
        f"gain_moy={avg_win:+9.2f}  perte_moy={avg_loss:+9.2f}  ratio_g/p={ratio:5.2f}"
    )


def main() -> None:
    config = FirmConfig.default()

    for symbol in SYMBOLS:
        for interval, period in TIMEFRAMES:
            print(f"\n=== {symbol} ({interval}/{period}) — Turtle Soup ===")
            price_series = fetch_multiple([symbol], interval=interval, period=period)
            print(f"  {len(price_series[symbol])} bougies récupérées")

            for rr in RR_VALUES:
                print(f"  -- RR 1:{rr:.0f} --")
                engine_spread = TurtleSoupBacktestEngine(
                    config.risk, config.starting_capital, spread_cost_pct=0.0002, rr=rr,
                )
                engine_zero = TurtleSoupBacktestEngine(
                    config.risk, config.starting_capital, spread_cost_pct=0.0, rr=rr,
                )

                _print_row("avec spread", engine_spread.run(price_series))
                _print_row("sans spread", engine_zero.run(price_series))


if __name__ == "__main__":
    main()
