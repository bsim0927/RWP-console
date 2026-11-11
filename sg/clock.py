"""The screen clock: a screen is due five business days after RWP files the fund (Charter, Section V;
decision G4). Business days are Monday to Friday; public holidays are not taken out."""

from datetime import date, timedelta

BUSINESS_DAYS = 5


def due(filed_on: date) -> date:
    d, left = filed_on, BUSINESS_DAYS
    while left:
        d += timedelta(days=1)
        left -= d.weekday() < 5
    return d


def business_days_between(a: date, b: date) -> int:
    """Business days after a, up to and including b; negative when b is before a."""
    if b < a:
        return -business_days_between(b, a)
    return sum((a + timedelta(days=i)).weekday() < 5 for i in range(1, (b - a).days + 1))


def status(filed_on: str | None, screened_on: str | None, today: date) -> dict | None:
    """Where a fund stands against its clock. screened_on is the date the screen was done, if it was.
    A screen done after its due date stays late, so the record shows it."""
    if not filed_on:
        return None
    f = date.fromisoformat(filed_on)
    d = due(f)
    end = date.fromisoformat(screened_on) if screened_on else today
    return {
        "filed_on": filed_on,
        "due": d.isoformat(),
        "done": bool(screened_on),
        "days_left": None if screened_on else business_days_between(today, d),
        "late": end > d,
    }
