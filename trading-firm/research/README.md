# research/ — l'unité de recherche d'edge

## Philosophie

Un backtest qui a l'air bon n'est pas une preuve d'edge — c'est une
hypothèse qui n'a pas encore été réfutée. La différence entre les deux
tient presque entièrement à la **discipline du processus**, pas à la
sophistication du code: un modèle simple validé honnêtement bat un modèle
complexe qui a juste bien mémorisé son historique de test.

Ce module n'implémente aucune nouvelle stratégie. Il encadre la façon dont
on en propose, on en teste, et on en rejette. La valeur est dans les
garde-fous, pas dans la complexité.

## Pourquoi chaque garde-fou existe

**Une hypothèse doit être écrite AVANT de regarder les résultats**
(`hypotheses/hypothesis.py`, `is_complete()`). Sans raison économique
explicite, sans prédiction précise, sans critère d'échec chiffré défini à
l'avance, il est trivial de raconter après coup une histoire qui justifie
n'importe quel résultat — y compris du pur bruit. `HypothesisRegistry`
refuse d'enregistrer une hypothèse incomplète: c'est la première ligne de
défense, avant même le premier backtest.

**Le cimetière (`hypotheses/graveyard.py`) est aussi précieux que les
succès.** Une idée déjà testée et rejetée, avec sa raison précise et ses
métriques finales archivées, évite de re-brûler du temps — et du risque de
p-hacking — à la re-tester sous une forme légèrement différente en ayant
oublié qu'elle avait déjà échoué.

**Le split train/test est chronologique, jamais mélangé**
(`validation/data_split.py`). Ce sont des séries temporelles: un shuffle
laisserait fuiter de l'information du futur vers le passé. Le verrou
(`lock_test_set`) et le compteur d'accès ne bloquent pas techniquement la
lecture des données — Python ne peut pas révoquer une référence déjà
retournée — mais rendent **visible et traçable** toute tentative de
regarder le test set pendant la conception. Regarder un résultat
out-of-sample puis ajuster les paramètres en conséquence transforme
silencieusement le test set en second train set — la source la plus
insidieuse de surajustement, parce qu'elle laisse croire que la validation
était honnête alors qu'elle ne l'est plus.

**Les 5 stages (`validation/stages.py`, `validation/pipeline.py`)
s'exécutent dans l'ordre et s'arrêtent au premier échec.** Chaque étape
suppose que les précédentes sont vraies — pas la peine de tester la
robustesse paramétrique ou temporelle d'un signal qui n'existe même pas en
in-sample:
1. **in_sample** — le signal existe-t-il seulement, sur les données
   d'entraînement ?
2. **out_of_sample** — marche-t-il sur des données jamais vues ? C'est le
   **seul** regard autorisé sur le test set, et il applique les critères
   d'échec définis À L'AVANCE dans l'hypothèse, pas de nouveaux seuils
   inventés après coup.
3. **param_robustness** — la performance s'effondre-t-elle sur des
   paramètres voisins (RSI 33/67 au lieu de 35/65, par ex.) ? Un edge réel
   n'est pas fragile aux réglages; s'il ne survit qu'avec exactement les
   paramètres qui ont servi à le découvrir, c'est le symptôme classique du
   surajustement.
4. **temporal_robustness** — l'edge est-il stable dans le temps (walk-
   forward), ou concentré sur une seule fenêtre chanceuse ?
5. **cost_survival** — le profit factor survit-il aux coûts de
   transaction réels ? Et si non, l'edge existe-t-il quand même à spread
   nul (`spread_only_failure`) ? C'est la distinction qu'on a dû
   reconstruire manuellement sur BTC/USDT et GC=F avant ce module: "pas de
   edge" et "edge mangé par les coûts" appellent des conclusions très
   différentes.

**Les garde-fous anti-p-hacking (`overfitting/guards.py`) rendent visible
le coût des essais successifs.** Plus on teste de variantes de paramètres
sur une même hypothèse, plus la probabilité de tomber sur une combinaison
qui a l'air bonne par pur hasard augmente — mécaniquement, sans mauvaise
intention. `check_trial_budget` avertit au-delà d'un budget raisonnable
d'essais. `complexity_penalty` relève le seuil de validation exigé en
fonction du nombre de paramètres de la stratégie: plus de degrés de
liberté, plus de risque d'avoir mémorisé le bruit plutôt que capturé un
edge réel.

**Tout est journalisé (`reports/research_log.py`), y compris les accès au
test set.** Pas pour la bureaucratie — pour pouvoir reconstituer après
coup l'historique complet d'une hypothèse sans dépendre de la mémoire de
qui l'a testée.

## Workflow type

```
1. Formuler    — écrire la raison économique, la prédiction, les critères
                 d'échec ET la description des données de test AVANT tout
                 backtest.
2. Enregistrer — HypothesisRegistry.register(hypothesis) — refuse si
                 incomplète.
3. Split       — DataSplit.split(price_series) — train (ancien) / test
                 (les 20% les plus récentes), jamais mélangés.
4. Concevoir   — itérer UNIQUEMENT sur data_split.train_data. Le test set
                 reste non observé.
5. Valider     — ValidationPipeline.validate(...) une seule fois: appelle
                 lock_test_set() puis regarde le test set exactement une
                 fois, dans le stage out_of_sample.
6. Décider     — tous les stages passent -> Statut.VALIDEE.
                 un stage échoue -> Statut.REJETEE + Graveyard.bury(...)
                 avec la raison précise et les métriques qui l'ont tuée.
```

Voir `research/example_hypothesis.py` pour une démonstration complète et
exécutable de ce workflow, du brouillon d'hypothèse jusqu'au verdict.

## Structure

```
research/
├── hypotheses/
│   ├── hypothesis.py   — dataclass Hypothesis + Statut
│   ├── registry.py     — HypothesisRegistry (garde: is_complete())
│   └── graveyard.py    — Graveyard (bury/list_buried/search_similar)
├── validation/
│   ├── data_split.py   — DataSplit (split chronologique + verrou test set)
│   ├── stages.py       — les 5 fonctions de stage
│   └── pipeline.py     — ValidationPipeline (orchestre les 5 stages)
├── overfitting/
│   └── guards.py       — OverfittingGuard (budget d'essais, pénalité de complexité)
├── reports/
│   └── research_log.py — ResearchLog (JSON-lines, append-only)
├── data/                — fichiers persistés (hypotheses.json, graveyard.json,
│                          research_log.jsonl), créés automatiquement
├── example_hypothesis.py
└── README.md
```

Tout réutilise `backtesting/engine.py` (`BacktestEngine`), qui réutilise
lui-même `core/indicators.py`, `core/strategy_logic.py` et
`core/risk_logic.py` — ce module n'implémente aucune logique de signal ou
de risque, uniquement l'orchestration et la discipline.
