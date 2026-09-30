"""
Chargement de données historiques via yfinance, pour le backtesting.

Traduit les symboles internes de la firme (format "BASE/QUOTE" ou ticker
actions) vers les tickers Yahoo Finance correspondants.
"""

import yfinance as yf

YFINANCE_TICKERS = {
    "EUR/USD": "EURUSD=X",
    "GBP/USD": "GBPUSD=X",
    "BTC/USDT": "BTC-USD",
    "ETH/USDT": "ETH-USD",
    "AAPL": "AAPL",
    "TSLA": "TSLA",
    "XAU/USD": "GC=F",
    "XAG/USD": "SI=F",
    "EUR/CHF": "EURCHF=X",
    "EUR/GBP": "EURGBP=X",
    "AUD/NZD": "AUDNZD=X",
}


def fetch_history(symbol: str, interval: str = "5m", period: str = "60d") -> list[dict]:
    """Retourne l'historique de bougies OHLC pour un symbole, trié du plus
    ancien au plus récent: [{"timestamp", "open", "high", "low", "close"}, ...]."""
    ticker = YFINANCE_TICKERS.get(symbol, symbol)
    df = yf.Ticker(ticker).history(interval=interval, period=period)

    history = [
        {
            "timestamp": timestamp.to_pydatetime() if hasattr(timestamp, "to_pydatetime") else timestamp,
            "open": float(row["Open"]),
            "high": float(row["High"]),
            "low": float(row["Low"]),
            "close": float(row["Close"]),
        }
        for timestamp, row in df.iterrows()
    ]
    history.sort(key=lambda bar: bar["timestamp"])
    return history


def fetch_multiple(symbols: list[str], interval: str = "5m", period: str = "60d") -> dict[str, list[dict]]:
    return {symbol: fetch_history(symbol, interval, period) for symbol in symbols}
