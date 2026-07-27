"""
Agrège un flux de ticks en bougies OHLC à intervalle de temps fixe.

Nécessaire pour calculer des indicateurs qui ont besoin de high/low (ADX),
pas seulement d'un prix de clôture.
"""

from datetime import datetime, timezone


class TickBarAggregator:
    def __init__(self, timeframe_seconds: int = 60) -> None:
        self.timeframe_seconds = timeframe_seconds
        self._current_bucket: int | None = None
        self._bar: dict | None = None

    def add_tick(self, price: float, timestamp: datetime) -> dict | None:
        bucket = self._bucket_for(timestamp)

        if self._current_bucket is None:
            self._start_bar(bucket, price)
            return None

        if bucket == self._current_bucket:
            self._bar["high"] = max(self._bar["high"], price)
            self._bar["low"] = min(self._bar["low"], price)
            self._bar["close"] = price
            return None

        finished_bar = self._bar
        self._start_bar(bucket, price)
        return finished_bar

    def _start_bar(self, bucket: int, price: float) -> None:
        self._current_bucket = bucket
        self._bar = {
            "timestamp": datetime.fromtimestamp(bucket, tz=timezone.utc),
            "open": price, "high": price, "low": price, "close": price,
        }

    def _bucket_for(self, timestamp: datetime) -> int:
        return int(timestamp.timestamp() // self.timeframe_seconds) * self.timeframe_seconds
