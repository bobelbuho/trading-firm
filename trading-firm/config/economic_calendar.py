"""
Calendrier économique STATIQUE — maintenu À LA MAIN.

Ce module ne se connecte à aucune API de calendrier macro en temps réel: il
contient une liste d'événements pré-remplis, à corriger/compléter
manuellement au fur et à mesure. Le rôle de ce système n'est PAS de deviner
ces dates automatiquement — l'enjeu (un blackout raté sur un FOMC ou un NFP
peut coûter cher) est trop important pour dépendre d'une source non
vérifiée à la main.

OÙ METTRE À JOUR: ajoute/corrige des entrées dans ECONOMIC_EVENTS ci-dessous.
Format: date="YYYY-MM-DD", heure_utc="HH:MM". Sources fiables pour vérifier
les dates réelles: calendrier officiel de la Fed (federalreserve.gov), de la
BCE (ecb.europa.eu), et du Bureau of Labor Statistics (bls.gov) pour
CPI/NFP US. Les dates ci-dessous sont des PLACEHOLDERS plausibles pour 2025
— à vérifier/compléter avant tout usage en conditions réelles.

FENÊTRE DE BLACKOUT PAR ÉVÉNEMENT: chaque événement peut définir ses propres
"blackout_before_min"/"blackout_after_min" (ex: le FOMC a une conférence de
presse qui suit la décision et prolonge la réaction du marché — une fenêtre
15/15 générique est trop courte). Si absents, is_in_blackout() retombe sur
les valeurs par défaut passées en argument (avant_min/after_min globaux).
"""

from datetime import datetime, timedelta, timezone

ECONOMIC_EVENTS: list[dict] = [
    {
        "date": "2026-07-29", "heure_utc": "18:00", "nom": "FOMC Rate Decision",
        "impact": "high", "devises": ["USD"],
        # Décision à 18:00 UTC (14h00 ET), conférence de presse à 18:30 UTC
        # (14h30 ET) qui peut durer ~1h — la réaction de marché s'étale bien
        # au-delà d'une fenêtre 15/15 générique.
        "blackout_before_min": 60, "blackout_after_min": 120,
    },
    {"date": "2025-01-29", "heure_utc": "19:00", "nom": "FOMC Decision", "impact": "high", "devises": ["USD"]},
    {"date": "2025-03-19", "heure_utc": "18:00", "nom": "FOMC Decision", "impact": "high", "devises": ["USD"]},
    {"date": "2025-05-07", "heure_utc": "18:00", "nom": "FOMC Decision", "impact": "high", "devises": ["USD"]},
    {"date": "2025-06-18", "heure_utc": "18:00", "nom": "FOMC Decision", "impact": "high", "devises": ["USD"]},
    {"date": "2025-07-30", "heure_utc": "18:00", "nom": "FOMC Decision", "impact": "high", "devises": ["USD"]},
    {"date": "2025-09-17", "heure_utc": "18:00", "nom": "FOMC Decision", "impact": "high", "devises": ["USD"]},
    {"date": "2025-01-30", "heure_utc": "13:15", "nom": "BCE Decision de taux", "impact": "high", "devises": ["EUR"]},
    {"date": "2025-03-06", "heure_utc": "13:15", "nom": "BCE Decision de taux", "impact": "high", "devises": ["EUR"]},
    {"date": "2025-04-17", "heure_utc": "12:15", "nom": "BCE Decision de taux", "impact": "high", "devises": ["EUR"]},
    {"date": "2025-06-05", "heure_utc": "12:15", "nom": "BCE Decision de taux", "impact": "high", "devises": ["EUR"]},
    {"date": "2025-01-15", "heure_utc": "13:30", "nom": "CPI US (inflation)", "impact": "high", "devises": ["USD"]},
    {"date": "2025-02-12", "heure_utc": "13:30", "nom": "CPI US (inflation)", "impact": "high", "devises": ["USD"]},
    {"date": "2025-03-12", "heure_utc": "12:30", "nom": "CPI US (inflation)", "impact": "high", "devises": ["USD"]},
    {"date": "2025-01-10", "heure_utc": "13:30", "nom": "NFP US (emploi non-agricole)", "impact": "high", "devises": ["USD"]},
    {"date": "2025-02-07", "heure_utc": "13:30", "nom": "NFP US (emploi non-agricole)", "impact": "high", "devises": ["USD"]},
    {"date": "2025-03-07", "heure_utc": "13:30", "nom": "NFP US (emploi non-agricole)", "impact": "high", "devises": ["USD"]},
]


def _event_datetime(event: dict) -> datetime:
    return datetime.strptime(f"{event['date']} {event['heure_utc']}", "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)


def get_upcoming_events(now: datetime, lookahead_hours: float) -> list[dict]:
    """Retourne les événements dont l'horodatage tombe dans
    [now, now + lookahead_hours], triés du plus proche au plus lointain."""
    horizon = now + timedelta(hours=lookahead_hours)
    upcoming = [e for e in ECONOMIC_EVENTS if now <= _event_datetime(e) <= horizon]
    upcoming.sort(key=_event_datetime)
    return upcoming


def is_in_blackout(now: datetime, before_min: int, after_min: int) -> tuple[bool, dict | None]:
    """Retourne (True, event) si `now` tombe dans la fenêtre de blackout
    d'un événement à fort impact, sinon (False, None). Ne considère que
    impact == 'high'. Chaque événement peut surcharger la fenêtre via ses
    propres "blackout_before_min"/"blackout_after_min"; à défaut, retombe
    sur before_min/after_min (les valeurs globales passées en argument)."""
    for event in ECONOMIC_EVENTS:
        if event["impact"] != "high":
            continue
        event_before_min = event.get("blackout_before_min", before_min)
        event_after_min = event.get("blackout_after_min", after_min)
        event_dt = _event_datetime(event)
        window_start = event_dt - timedelta(minutes=event_before_min)
        window_end = event_dt + timedelta(minutes=event_after_min)
        if window_start <= now <= window_end:
            return True, event
    return False, None
