"""
run_validation.py — lance le protocole de validation walk-forward GO/NO-GO
directement en script, sans passer par le bus (pratique pour du debug rapide
ou une vérification manuelle avant de brancher ValidationAgent en live).

Usage: python backtesting/run_validation.py [--symbols BTC/USDT,TSLA,XAU/USD]
       [--interval 5m] [--total-period-days 60] [--window-days 15] [--spread 0.0002]
"""

import argparse
import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backtesting.validation import DEFAULT_SYMBOLS, run_validation
from config.settings import FirmConfig


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", default=None, help="Symboles séparés par des virgules (défaut: BTC/USDT,TSLA,XAU/USD)")
    parser.add_argument("--interval", default="5m", help="Granularité des bougies yfinance")
    parser.add_argument("--total-period-days", type=int, default=60, help="Fenêtre historique totale en jours")
    parser.add_argument("--window-days", type=int, default=15, help="Taille de chaque fenêtre walk-forward en jours")
    parser.add_argument("--spread", type=float, default=0.0002, help="Coût de spread réaliste (comparé à 0 en interne)")
    args = parser.parse_args()

    symbols = args.symbols.split(",") if args.symbols else DEFAULT_SYMBOLS
    config = FirmConfig.default()

    print(f"Validation walk-forward: {', '.join(symbols)} | {args.interval}/{args.total_period_days}j, fenêtres de {args.window_days}j")
    report = run_validation(
        symbols=symbols,
        interval=args.interval,
        total_period_days=args.total_period_days,
        window_days=args.window_days,
        risk_config=config.risk,
        starting_capital=config.starting_capital,
        spread_cost_pct=args.spread,
    )

    print()
    print(report.summary())


if __name__ == "__main__":
    main()
