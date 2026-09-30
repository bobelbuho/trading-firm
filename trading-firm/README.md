# Trading Firm — architecture multi-agents pour le scalping

Une "firme" de trading où chaque fonction (analyse marché, news, stratégie,
risque, exécution, portefeuille) est un agent indépendant qui communique
via un bus de messages — comme une équipe où chaque spécialiste fait
son travail et transmet l'info au suivante.

## Architecture

```
market_data_agent ──┐
                     ├──> strategy_agent ──> risk_manager ──> execution_agent ──> portfolio_manager
news_agent ──────────┘                           ▲                                      │
                                                   └──────────── supervisor ◄─────────────┘
```

- **MarketDataAgent** : flux de prix + indicateurs techniques
- **NewsAgent** : calendrier macro, blackout automatique avant/après news à fort impact
- **StrategyAgent** : génère des signaux (stratégie exemple RSI fournie — À REMPLACER par la tienne)
- **RiskManager** : seul agent qui peut approuver un trade. Calcule le sizing, applique les limites d'exposition, gère le kill-switch de perte journalière
- **ExecutionAgent** : envoie l'ordre au broker (paper ou live selon `FIRM_MODE`)
- **PortfolioManager** : suit les positions, détecte TP/SL touchés, calcule le P&L
- **Supervisor** : surveille la santé globale, déclenche l'arrêt d'urgence si trop d'échecs consécutifs

## Démarrer (mode paper, aucune clé API requise)

```bash
pip install -r requirements.txt
python main.py
```

Tourne immédiatement avec des prix simulés — utile pour valider la logique
de bout en bout avant de brancher un vrai broker.

## Brancher un vrai broker

Chaque connecteur (`brokers/simulated.py`) respecte une interface (`Protocol`)
définie dans l'agent correspondant :
- `MarketDataClient` (dans `market_data_agent.py`)
- `NewsClient` (dans `news_agent.py`)
- `OrderBroker` (dans `execution_agent.py`)

Pour brancher Binance par exemple : crée `brokers/binance_client.py` qui
implémente `MarketDataClient` et `OrderBroker` avec `ccxt`, puis remplace
`SimulatedMarketDataClient`/`SimulatedBroker` par tes nouvelles classes dans
`main.py`. **Aucun autre fichier n'a besoin de changer.**

## Brancher AvaTrade (via MetaApi)

AvaTrade fonctionne via MT4/MT5, pas d'API REST propriétaire. Le pont
utilisé ici est [MetaApi.cloud](https://metaapi.cloud) (tier gratuit
pour 1 compte).

**Étapes :**

1. Crée un compte sur https://metaapi.cloud et récupère un token sur
   https://app.metaapi.cloud/token
2. Copie `.env.example` en `.env` et remplis :
   ```
   BROKER_MODE=avatrade
   METAAPI_TOKEN=ton_token
   MT5_LOGIN=ton_login_mt5
   MT5_PASSWORD=ton_mot_de_passe_investisseur   # commence par celui-ci, en lecture seule
   MT5_SERVER=AvaTrade-Demo                      # nom exact visible dans ton terminal MT5
   ```
3. Installe la dépendance : `pip install metaapi-cloud-sdk --break-system-packages`
4. **Adapte les symboles** dans `config/settings.py` : MT5 utilise des
   tickers sans slash (`EURUSD` et non `EUR/USD`). Commence avec le seul
   marché forex/CFD pour valider la connexion avant d'ajouter les autres.
5. Lance `python main.py`

**Important :** le mot de passe investisseur (read-only) permet de voir
les prix et l'état du compte mais PAS de passer d'ordres — c'est
volontaire pour que tu puisses d'abord valider que tout le pipeline
d'analyse fonctionne avec de vraies données avant de risquer quoi que
ce soit. Une fois satisfait, passe au mot de passe trading complet.

⚠️ Le connecteur `brokers/avatrade_metaapi.py` n'a pas pu être testé en
conditions réelles dans cet environnement de développement (pas d'accès
réseau pour installer/valider le SDK). Teste-le d'abord avec un montant
minimal en démo et vérifie chaque étape (connexion, réception de prix,
exécution d'un ordre test) avant de t'y fier.

## Sécurité — À LIRE avant de passer en live

1. **`FIRM_MODE=paper`** doit rester la valeur par défaut. Ne passe à `live`
   dans ton `.env` qu'après avoir fait tourner le système en paper pendant
   au moins plusieurs jours/semaines et vérifié chaque agent individuellement.
2. Les clés API vont dans un fichier `.env` (jamais commit dans git — ajoute
   `.env` à ton `.gitignore`), chargées via `python-dotenv`.
3. Le `RiskManager` a un kill-switch automatique sur la perte journalière
   max (`max_daily_loss_pct` dans `config/settings.py`). Ne le désactive
   jamais.
4. Commence avec UN SEUL marché et un capital que tu peux te permettre de
   perdre entièrement, même en mode live "validé". Élargis progressivement.

## Prochaines étapes possibles

- Remplacer la stratégie RSI exemple par ta vraie logique de scalping
- Brancher une vraie source de news (Finnhub, Trading Economics)
- Ajouter TimescaleDB pour stocker l'historique et faire du backtesting
- Construire le dashboard FastAPI pour visualiser `portfolio.snapshot` en temps réel
- Ajouter des tests unitaires par agent (dossier `tests/`)
