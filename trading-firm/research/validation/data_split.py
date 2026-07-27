"""
DataSplit — sépare une série temporelle en train/test en respectant l'ordre
chronologique (jamais de shuffle: on ne mélange pas le futur et le passé).

Le verrou (lock_test_set) et le compteur d'accès ne servent PAS à empêcher
techniquement de lire les données déjà retournées par split() — Python ne
peut pas révoquer une référence déjà donnée à l'appelant. Leur rôle est de
rendre visible et traçable toute tentative de "jeter un oeil" au test set
pendant la conception: regarder un résultat out-of-sample puis ajuster les
paramètres en fonction transforme silencieusement le test set en un second
train set, et c'est la source la plus insidieuse de surajustement — plus
difficile à détecter que le p-hacking sur des paramètres, parce qu'elle
laisse croire que la validation était honnête.
"""

import logging

logger = logging.getLogger("research.data_split")


class TestSetLockedError(RuntimeError):
    pass


class DataSplit:
    def __init__(self) -> None:
        self._locked = False
        self.test_set_accessed = 0
        self.train_data: dict[str, list[dict]] | None = None
        self._test_data: dict[str, list[dict]] | None = None

    def split(
        self, price_series: dict[str, list[dict]], test_ratio: float = 0.2,
    ) -> tuple[dict[str, list[dict]], dict[str, list[dict]]]:
        if self._locked:
            raise TestSetLockedError(
                "Le test set est verrouillé — impossible de re-découper les données "
                "(ça permettrait de régénérer un test set différent après coup)."
            )

        train_data, test_data = {}, {}
        for symbol, bars in price_series.items():
            cutoff = int(len(bars) * (1 - test_ratio))
            train_data[symbol] = bars[:cutoff]   # les plus anciennes
            test_data[symbol] = bars[cutoff:]    # les 20% les plus récentes

        self.train_data = train_data
        self._test_data = test_data
        return train_data, test_data

    def lock_test_set(self) -> None:
        self._locked = True
        logger.info("Test set verrouillé — tout accès ultérieur sera loggé et compté.")

    def get_test_set(self) -> dict[str, list[dict]]:
        if self._test_data is None:
            raise RuntimeError("split() doit être appelé avant get_test_set().")

        self.test_set_accessed += 1
        etat = "après verrouillage" if self._locked else "avant verrouillage"
        logger.warning(
            f"Accès aux données de test #{self.test_set_accessed} ({etat}) — "
            "vérifie que la conception de la stratégie n'a pas été influencée par ce regard."
        )
        return self._test_data
