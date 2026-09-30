"""
MacroAgent — l'unité macro DÉFENSIVE de la firme.

Rôle: évaluer s'il est prudent de trader, jamais prédire la direction du
marché. Deux couches:
  1. Calendrier économique statique (config/economic_calendar.py) — détecte
     les fenêtres de blackout autour d'événements à fort impact.
  2. Régime de volatilité (core/market_regime.py) — mesure l'agitation du
     marché (persistante, contrairement à la direction) pour classer le
     risque ambiant en "calme"/"prudence"/"stress".

Cet agent NE TRADE JAMAIS et N'ÉMET JAMAIS de signal d'achat/vente. Il
publie un ÉTAT ("macro.state") que le RiskManager interprète de façon
strictement défensive (jamais pour devenir plus agressif). Il publie aussi
"news.blackout" (déjà écouté par RiskManager) quand un événement à fort
impact entre dans sa fenêtre de blackout.
"""

import asyncio
from datetime import datetime, timezone

from config.economic_calendar import get_upcoming_events, is_in_blackout
from core.base_agent import BaseAgent
from core.market_regime import classify_regime, realized_volatility, volatility_percentile
from core.message_bus import MessageBus, Message

MAX_PRICE_HISTORY = 500
MAX_VOL_HISTORY = 200

# Stablecoins adossés au dollar: un événement macro "USD" (FOMC, CPI, NFP...)
# affecte aussi le sentiment risque sur les paires libellées en USDT/USDC,
# pas seulement les paires FX/actions strictement en USD.
STABLECOIN_ALIASES = {"USDT": "USD", "USDC": "USD"}


def _normalize_currency(code: str) -> str:
    return STABLECOIN_ALIASES.get(code, code)


class MacroAgent(BaseAgent):
    def __init__(
        self, bus: MessageBus,
        blackout_before_min: int = 15, blackout_after_min: int = 15,
        vol_window: int = 20,
        calendar_check_interval_seconds: float = 30.0,
        macro_state_interval_seconds: float = 15.0,
        force_regime: str | None = None,   # override manuel pour tests ("calme"/"prudence"/"stress")
    ) -> None:
        super().__init__(name="MacroAgent", bus=bus)
        self.blackout_before_min = blackout_before_min
        self.blackout_after_min = blackout_after_min
        self.vol_window = vol_window
        self.calendar_check_interval_seconds = calendar_check_interval_seconds
        self.macro_state_interval_seconds = macro_state_interval_seconds
        self.force_regime = force_regime

        self._price_history: dict[str, list[float]] = {}
        self._historical_vols: dict[str, list[float]] = {}
        self._active_blackout_keys: set[str] = set()

    async def setup(self) -> None:
        self.bus.subscribe("market.tick", self._on_tick)

    async def run(self) -> None:
        await asyncio.gather(
            self._watch_calendar(),
            self._publish_macro_state_loop(),
        )

    async def _on_tick(self, msg: Message) -> None:
        symbol = msg.payload["symbol"]
        price = msg.payload["price"]
        hist = self._price_history.setdefault(symbol, [])
        hist.append(price)
        if len(hist) > MAX_PRICE_HISTORY:
            hist.pop(0)

    async def _watch_calendar(self) -> None:
        while True:
            now = datetime.now(timezone.utc)
            in_blackout, event = is_in_blackout(now, self.blackout_before_min, self.blackout_after_min)
            if in_blackout:
                await self._trigger_blackout(event)
            await asyncio.sleep(self.calendar_check_interval_seconds)

    async def _trigger_blackout(self, event: dict) -> None:
        for symbol in self._affected_symbols(event["devises"]):
            if symbol in self._active_blackout_keys:
                continue
            self._active_blackout_keys.add(symbol)
            await self.emit("news.blackout", {
                "key": symbol,
                "event_title": event["nom"],
                "reason": f"Événement macro à fort impact: {event['nom']}",
            })

    def _affected_symbols(self, devises: list[str]) -> list[str]:
        """Associe les devises d'un événement aux symboles réellement
        suivis (appris dynamiquement via market.tick). Les stablecoins
        (USDT/USDC) sont normalisés vers USD avant comparaison — un
        événement macro USD affecte aussi le sentiment risque sur les
        paires crypto libellées en USDT/USDC. Les actions US (sans '/')
        sont traitées comme exposées USD par convention."""
        normalized_devises = {_normalize_currency(d) for d in devises}
        affected = []
        for symbol in self._price_history:
            parts = {_normalize_currency(p) for p in symbol.split("/")}
            if normalized_devises & parts:
                affected.append(symbol)
            elif "/" not in symbol and "USD" in normalized_devises:
                affected.append(symbol)
        return affected

    async def _publish_macro_state_loop(self) -> None:
        while True:
            await self._publish_macro_state()
            await asyncio.sleep(self.macro_state_interval_seconds)

    async def _publish_macro_state(self) -> None:
        now = datetime.now(timezone.utc)
        in_blackout, _ = is_in_blackout(now, self.blackout_before_min, self.blackout_after_min)
        upcoming = get_upcoming_events(now, lookahead_hours=24 * 30)   # 30 jours, pour un état informatif

        regime, vol_percentile = self._current_regime()

        await self.emit("macro.state", {
            "regime": regime,
            "vol_percentile": vol_percentile,
            "blackout_actif": in_blackout,
            "prochain_evenement": upcoming[0] if upcoming else None,
        })

    def _current_regime(self) -> tuple[str, float | None]:
        """Régime agrégé sur tous les symboles suivis: on retient le PLUS
        prudent des régimes individuels (principe défensif — un seul
        symbole en stress suffit à considérer l'ensemble du marché comme
        agité)."""
        if self.force_regime is not None:
            return self.force_regime, None

        order = {"calme": 0, "prudence": 1, "stress": 2}
        results: list[tuple[str, float]] = []

        for symbol, prices in self._price_history.items():
            if len(prices) < self.vol_window + 1:
                continue

            current_vol = realized_volatility(prices, self.vol_window)
            hist = self._historical_vols.setdefault(symbol, [])

            if hist:
                percentile = volatility_percentile(current_vol, hist)
                results.append((classify_regime(percentile), percentile))

            hist.append(current_vol)
            if len(hist) > MAX_VOL_HISTORY:
                hist.pop(0)

        if not results:
            return "calme", None
        return max(results, key=lambda r: order[r[0]])
