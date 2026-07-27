"""
Connecteur AvaTrade (MT5) via MetaApi.cloud.

AvaTrade n'a pas d'API REST propriétaire — le seul chemin pour connecter
un système externe est via MetaTrader 5. MetaApi.cloud fait le pont entre
ton compte MT5 et une API websocket/REST utilisable depuis Python sur
Linux (le package officiel `MetaTrader5` de MetaQuotes ne fonctionne
que sur Windows avec le terminal installé localement).

PRÉREQUIS avant utilisation:
  1. Un compte sur https://metaapi.cloud (le tier gratuit couvre 1 compte MT)
  2. Un token API généré sur https://app.metaapi.cloud/token
  3. Les identifiants de ton compte MT5 AvaTrade: login, password, server
     (le nom exact du serveur est visible dans ton terminal MT5, écran de
     connexion — ex: "AvaTrade-Demo" ou "AvaTrade-Real", à vérifier)

IMPORTANT SÉCURITÉ:
  - Utilise le mot de passe "investisseur" (read-only) de ton compte MT5
    tant que tu ne fais que du monitoring/tests. Ce mot de passe ne
    permet PAS de passer d'ordres, seulement de lire les données —
    c'est le choix le plus sûr pour valider la connexion.
  - Ne mets JAMAIS ces valeurs en dur dans le code. Utilise le fichier
    .env (voir .env.example à la racine du projet).
  - Ce fichier n'a pas pu être testé en conditions réelles dans cet
    environnement (pas d'accès réseau pour installer le SDK). Teste-le
    d'abord avec des montants et un compte démo avant toute utilisation
    sérieuse.

Installation requise:
    pip install metaapi-cloud-sdk --break-system-packages
"""

import asyncio
import logging
import os

logger = logging.getLogger("avatrade_metaapi")


class AvaTradeMetaApiConnector:
    """
    Implémente à la fois MarketDataClient et OrderBroker (voir les
    Protocols définis dans agents/market_data_agent.py et
    agents/execution_agent.py) pour un compte AvaTrade via MetaApi.

    Usage dans main.py:
        connector = AvaTradeMetaApiConnector(
            token=os.environ["METAAPI_TOKEN"],
            login=os.environ["MT5_LOGIN"],
            password=os.environ["MT5_PASSWORD"],
            server=os.environ["MT5_SERVER"],
        )
        await connector.connect()
        # connector peut ensuite être passé comme market_client ET comme broker
    """

    def __init__(self, token: str, login: str, password: str, server: str,
                 account_name: str = "AvaTrade Firm Account") -> None:
        self.token = token
        self.login = login
        self.password = password
        self.server = server
        self.account_name = account_name

        self._api = None
        self._account = None
        self._connection = None
        self._connected = False

    async def connect(self) -> None:
        """À appeler une fois au démarrage, avant d'utiliser le connecteur."""
        try:
            from metaapi_cloud_sdk import MetaApi
        except ImportError as e:
            raise RuntimeError(
                "Le package metaapi-cloud-sdk n'est pas installé. "
                "Lance: pip install metaapi-cloud-sdk --break-system-packages"
            ) from e

        self._api = MetaApi(token=self.token)

        # Cherche un compte existant correspondant, sinon le crée sur MetaApi.
        accounts = await self._api.metatrader_account_api.get_accounts_with_infinite_scroll_pagination(
            {"query": self.login}
        )
        existing = next((a for a in accounts if a.login == self.login), None)

        if existing:
            self._account = existing
            logger.info(f"Compte MetaApi existant trouvé pour login {self.login}")
        else:
            self._account = await self._api.metatrader_account_api.create_account({
                "name": self.account_name,
                "type": "cloud",
                "login": self.login,
                "password": self.password,
                "server": self.server,
                "platform": "mt5",
                "magic": 123456,
            })
            logger.info(f"Nouveau compte MetaApi créé pour login {self.login}")

        logger.info("Déploiement du compte (peut prendre jusqu'à ~1 minute)...")
        await self._account.deploy()
        await self._account.wait_connected()

        self._connection = self._account.get_streaming_connection()
        await self._connection.connect()
        await self._connection.wait_synchronized()

        self._connected = True
        logger.info("Connexion AvaTrade/MetaApi établie et synchronisée.")

    async def disconnect(self) -> None:
        if self._connection:
            await self._connection.close()
        self._connected = False

    def _ensure_connected(self) -> None:
        if not self._connected:
            raise RuntimeError(
                "AvaTradeMetaApiConnector.connect() doit être appelé et terminé "
                "avant d'utiliser le connecteur."
            )

    # ---- Implémentation MarketDataClient ----

    async def stream_prices(self, symbol: str):
        """Yield des mises à jour de prix pour un symbole, via polling léger
        du terminal state (l'API MetaApi met à jour terminal_state en
        temps réel via le websocket en arrière-plan)."""
        self._ensure_connected()

        terminal_state = self._connection.terminal_state
        await self._connection.subscribe_to_market_data(symbol)

        last_time = None
        while True:
            await asyncio.sleep(0.5)
            price = terminal_state.price(symbol)
            if not price:
                continue
            if price.get("time") == last_time:
                continue
            last_time = price.get("time")

            yield {
                "symbol": symbol,
                "price": (price["bid"] + price["ask"]) / 2,
                "bid": price["bid"],
                "ask": price["ask"],
                "volume": None,  # non fourni par le flux de prix MT5 standard
            }

    # ---- Implémentation OrderBroker ----

    async def place_order(self, symbol: str, side: str, size: float,
                           stop_loss: float, take_profit: float,
                           reference_price: float | None = None) -> dict:
        self._ensure_connected()

        # ATTENTION: si tu es connecté avec le mot de passe investisseur
        # (read-only), cet appel échouera — c'est le comportement voulu
        # tant que tu es en phase de test.
        if side == "buy":
            result = await self._connection.create_market_buy_order(
                symbol=symbol, volume=size,
                stop_loss=stop_loss, take_profit=take_profit,
            )
        else:
            result = await self._connection.create_market_sell_order(
                symbol=symbol, volume=size,
                stop_loss=stop_loss, take_profit=take_profit,
            )

        return {
            "order_id": str(result.get("orderId") or result.get("positionId")),
            "fill_price": result.get("price", reference_price),
            "status": "filled" if result.get("numericCode") == 0 else "rejected",
        }
