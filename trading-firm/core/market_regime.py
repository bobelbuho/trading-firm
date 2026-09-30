"""
market_regime.py — évaluation DÉFENSIVE du régime de risque à partir de
l'historique de prix. Fonctions pures, sans état, dans le même esprit que
core/indicators.py.

IMPORTANT: ces fonctions ne prédisent JAMAIS de direction de marché. Elles
mesurent uniquement l'AGITATION du marché (volatilité), pour MODULER LE
RISQUE pris (taille de position, autorisation de trader) — jamais pour
décider d'acheter ou de vendre. La volatilité est PERSISTANTE (les périodes
agitées s'enchaînent, phénomène robuste et documenté), contrairement à la
direction du marché qui n'est pas prévisible de façon fiable par ces mêmes
méthodes: une vol élevée aujourd'hui prédit une vol élevée demain, donc
"réduire le risque quand la vol est haute" est une règle défensive solide,
même sans jamais dire si le marché va monter ou descendre.
"""

import math

DEFAULT_PRUDENCE_THRESHOLD = 50.0
DEFAULT_STRESS_THRESHOLD = 80.0


def realized_volatility(prices: list[float], window: int, periods_per_year: int = 252) -> float:
    """Écart-type des rendements logarithmiques sur la fenêtre, annualisé.
    Ne dit RIEN sur la direction — uniquement l'ampleur des mouvements."""
    recent = prices[-(window + 1):]
    if len(recent) < 2:
        return 0.0

    log_returns = [math.log(recent[i] / recent[i - 1]) for i in range(1, len(recent)) if recent[i - 1] > 0]
    if len(log_returns) < 2:
        return 0.0

    mean = sum(log_returns) / len(log_returns)
    variance = sum((r - mean) ** 2 for r in log_returns) / (len(log_returns) - 1)
    return (variance ** 0.5) * math.sqrt(periods_per_year)


def volatility_percentile(current_vol: float, historical_vols: list[float]) -> float:
    """Où se situe current_vol par rapport à son propre historique (0-100).
    Ex: 90 veut dire que la vol actuelle dépasse 90% des observations
    passées — une position relative, jamais une prédiction."""
    if not historical_vols:
        return 50.0   # pas d'historique -> position neutre par défaut
    below = sum(1 for v in historical_vols if v <= current_vol)
    return below / len(historical_vols) * 100


def classify_regime(
    vol_percentile: float,
    prudence_threshold: float = DEFAULT_PRUDENCE_THRESHOLD,
    stress_threshold: float = DEFAULT_STRESS_THRESHOLD,
) -> str:
    """Classe le régime de risque à partir du percentile de volatilité:
    "calme" (< prudence_threshold), "prudence" (entre les deux seuils),
    "stress" (> stress_threshold). Sert à MODULER LE RISQUE (taille de
    position, autorisation de trader) — ne génère jamais de signal
    directionnel (achat/vente)."""
    if vol_percentile > stress_threshold:
        return "stress"
    if vol_percentile > prudence_threshold:
        return "prudence"
    return "calme"
