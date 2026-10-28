"""Reusable organization business-day calendar helpers."""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select

from extensions import db
from shared.models import OrganizationBusinessDayOverride


class BusinessCalendarError(ValueError):
    pass


def load_business_day_overrides(
    organization_id: str, start: date, end: date
) -> dict[date, bool]:
    if end < start:
        return {}
    rows = db.session.scalars(
        select(OrganizationBusinessDayOverride).where(
            OrganizationBusinessDayOverride.organization_id == organization_id,
            OrganizationBusinessDayOverride.calendar_date >= start,
            OrganizationBusinessDayOverride.calendar_date <= end,
        )
    )
    return {row.calendar_date: row.is_working_day for row in rows}


def is_working_day(value: date, overrides: dict[date, bool] | None = None) -> bool:
    if overrides and value in overrides:
        return overrides[value]
    return value.weekday() < 5


def add_workdays(
    value: date, amount: int, overrides: dict[date, bool] | None = None
) -> date:
    step = 1 if amount >= 0 else -1
    remaining = abs(amount)
    current = value
    while remaining:
        current += timedelta(days=step)
        if is_working_day(current, overrides):
            remaining -= 1
    return current


def upsert_business_day_override(
    organization_id: str,
    calendar_date: date,
    is_working_day_value: bool,
    label: str,
    actor_user_id: int,
) -> OrganizationBusinessDayOverride:
    if calendar_date.year < 2000 or calendar_date.year > 2100:
        raise BusinessCalendarError("日期必须在 2000–2100 年之间。")
    clean_label = label.strip()
    if len(clean_label) > 120:
        raise BusinessCalendarError("日历说明不能超过 120 个字符。")
    row = db.session.scalar(
        select(OrganizationBusinessDayOverride).where(
            OrganizationBusinessDayOverride.organization_id == organization_id,
            OrganizationBusinessDayOverride.calendar_date == calendar_date,
        )
    )
    if row is None:
        row = OrganizationBusinessDayOverride(
            organization_id=organization_id,
            calendar_date=calendar_date,
            is_working_day=is_working_day_value,
            label=clean_label or None,
            created_by_user_id=actor_user_id,
            updated_by_user_id=actor_user_id,
        )
        db.session.add(row)
    else:
        row.is_working_day = is_working_day_value
        row.label = clean_label or None
        row.updated_by_user_id = actor_user_id
        row.version += 1
    db.session.flush()
    return row
