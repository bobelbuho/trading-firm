"""
run_backtest.py — lance un backtest de la stratégie confluence Bollinger+RSI
sur l'historique réel (via yfinance) de tous les symboles configurés dans
FirmConfig.

Usage: python backtesting/run_backtest.py [--interval 5m] [--period 60d] [--spread 0.0002] [--symbols BTC/USDT,XAU/USD]
"""

import argparse
import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backtesting.data_loader import fetch_multiple
from backtesting.engine import BacktestEngine
from config.settings import FirmConfig


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--interval", default="5m", help="Granularité des bougies yfinance (ex: 5m, 15m, 1h)")
    parser.add_argument("--period", default="60d", help="Fenêtre historique yfinance (ex: 60d, 180d, 730d)")
    parser.add_argument("--spread", type=float, default=0.0002, help="Coût de spread appliqué à l'entrée et à la sortie (défaut 0.0002)")
    parser.add_argument("--symbols", default=None, help="Liste de symboles séparés par des virgules (défaut: tous ceux de FirmConfig), ex: XAU/USD")
    args = parser.parse_args()

    config = FirmConfig.default()
    all_symbols = args.symbols.split(",") if args.symbols else [s for m in config.markets for s in m.symbols]

    print(f"Téléchargement de l'historique ({args.interval}/{args.period}) pour: {', '.join(all_symbols)}")
    price_series = fetch_multiple(all_symbols, interval=args.interval, period=args.period)
    for symbol, bars in price_series.items():
        print(f"  {symbol}: {len(bars)} bougies")

    engine = BacktestEngine(config.risk, starting_capital=config.starting_capital, spread_cost_pct=args.spread)
    result = engine.run(price_series)

    print()
    print(result.summary())

    print()
    print("=== Détail par symbole ===")
    for symbol in all_symbols:
        symbol_trades = [t for t in result.trades if t.symbol == symbol]
        wins = sum(1 for t in symbol_trades if t.pnl > 0)
        total_pnl = sum(t.pnl for t in symbol_trades)
        print(f"  {symbol:10s} trades={len(symbol_trades):3d} gagnants={wins:3d} pnl_total={total_pnl:+.2f}")

    print()
    print("=== Répartition par exit_reason ===")
    for reason in ("stop_loss", "take_profit", "fin_backtest"):
        reason_trades = [t for t in result.trades if t.exit_reason == reason]
        total_pnl = sum(t.pnl for t in reason_trades)
        print(f"  {reason:15s} trades={len(reason_trades):3d} pnl_total={total_pnl:+.2f}")

    print()
    print("=== Tendance par symbole (période complète) ===")
    for symbol in all_symbols:
        bars = price_series.get(symbol, [])
        if not bars:
            continue
        first_price, last_price = bars[0]["close"], bars[-1]["close"]
        trend_pct = (last_price - first_price) / first_price * 100
        print(f"  {symbol:10s} {first_price:10.4f} -> {last_price:10.4f}  tendance={trend_pct:+.2f}%")


if __name__ == "__main__":
    main()
