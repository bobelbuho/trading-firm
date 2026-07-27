"""
NewsAgent — l'analyste qui surveille l'actualité et le calendrier macro.

Rôle: détecter les événements à fort impact (NFP, décisions de taux,
CPI, earnings...) et prévenir toute la firme AVANT que ça arrive, pour
que le Risk Manager puisse mettre en pause le trading pendant les
fenêtres dangereuses. En scalping, trader pendant une annonce macro
majeure est l'une des façons les plus rapides de se faire liquider.

NOTE: Le fournisseur de données news (client) est injecté, ex: une API
type Finnhub, Trading Economics, ou un flux RSS/Twitter filtré.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Protocol

from core.base_agent import BaseAgent
from core.message_bus import MessageBus


class NewsClient(Protocol):
    async def get_upcoming_events(self, lookahead_minutes: int) -> list[dict]:
        """Doit retourner une liste de {title, impact, currency/symbol, time}."""
        ...

    async def stream_headlines(self):
        """Doit yield des dicts {title, sentiment, symbols, timestamp}."""
        ...


class NewsAgent(BaseAgent):
    HIGH_IMPACT = "high"

    def __init__(self, bus: MessageBus, client: NewsClient, blackout_before: int, blackout_after: int) -> None:
        super().__init__(name="NewsAgent", bus=bus)
        self.client = client
        self.blackout_before = blackout_before
        self.blackout_after = blackout_after
        self._active_blackouts: dict[str, datetime] = {}  # symbol/currency -> fin du blackout

    async def setup(self) -> None:
        pass

    async def run(self) -> None:
        await asyncio.gather(
            self._watch_calendar(),
            self._watch_headlines(),
        )

    async def _watch_calendar(self) -> None:
        while True:
            events = await self.client.get_upcoming_events(lookahead_minutes=self.blackout_before + 5)
            for event in events:
                if event["impact"] == self.HIGH_IMPACT:
                    await self._trigger_blackout(event)
            await asyncio.sleep(30)  # check toutes les 30s

    async def _watch_headlines(self) -> None:
        async for headline in self.client.stream_headlines():
            await self.emit("news.headline", {
                "title": headline["title"],
                "sentiment": headline.get("sentiment"),  # -1 à 1
                "symbols": headline.get("symbols", []),
                "timestamp": headline["timestamp"],
            })

    async def _trigger_blackout(self, event: dict) -> None:
        key = event.get("currency") or event.get("symbol")
        blackout_end = datetime.now(timezone.utc) + timedelta(minutes=self.blackout_after)

        if key in self._active_blackouts:
            return  # déjà notifié

        self._active_blackouts[key] = blackout_end
        await self.emit("news.blackout", {
            "key": key,
            "event_title": event["title"],
            "starts_in_minutes": self.blackout_before,
            "duration_minutes": self.blackout_before + self.blackout_after,
            "reason": f"Événement à fort impact: {event['title']}",
        })
