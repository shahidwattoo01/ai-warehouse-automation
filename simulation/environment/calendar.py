"""The simulated business calendar shared by the dataset generator and the live predictions.

Dataset v3 covers Monday 2026-09-07 to Sunday 2026-12-06. The live simulator maps its day counter
onto the same calendar (day 1 = START_DATE), so models trained on the dataset see the same
weekday, month and promotion features at prediction time.
"""

from __future__ import annotations

import datetime as dt

START_DATE = dt.date(2026, 9, 7)  # a Monday
PROMOTIONS: dict[dt.date, tuple[str, float]] = {
    dt.date(2026, 11, 11): ("Singles Day", 1.12),
    dt.date(2026, 11, 27): ("Black Friday", 1.22),
    dt.date(2026, 11, 30): ("Cyber Monday", 1.15),
}
SEASONS = {12: "winter", 1: "winter", 2: "winter", 3: "spring", 4: "spring", 5: "spring",
           6: "summer", 7: "summer", 8: "summer"}  # fmt: skip


def season_name(date: dt.date) -> str:
    return SEASONS.get(date.month, "autumn")


def date_of_day(day: int, start: dt.date = START_DATE) -> dt.date:
    """Calendar date of simulated day `day` (1-based)."""
    return start + dt.timedelta(days=day - 1)


def calendar_features(date: dt.date) -> dict:
    """The calendar columns used as model features."""
    weekday = date.weekday()
    return {
        "date": date.isoformat(),
        "day_of_week": weekday,
        "is_weekend": weekday >= 5,
        "month": date.month,
        "season": season_name(date),
        "is_promo_day": date in PROMOTIONS,
        "promo_name": PROMOTIONS.get(date, (None,))[0],
    }
