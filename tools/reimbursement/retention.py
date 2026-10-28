"""Pure reimbursement rules; amounts are validated before financial writes."""
from decimal import Decimal, InvalidOperation, ROUND_DOWN
import re

POLICIES = {"expense", "retain", "review"}
KINDS = {"invoice", "toll", "fuel", "toll_statement"}


def money(value):
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount < 0 or amount > Decimal("999999999.99"):
            raise ValueError
        if amount != amount.quantize(Decimal(".01")):
            raise ValueError
        return amount.quantize(Decimal(".01"))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("金额须为非负数，最多两位小数且不超过 999999999.99") from None


def month(value):
    if not isinstance(value, str) or not re.fullmatch(r"[1-9]\d{3}-(0[1-9]|1[0-2])", value):
        raise ValueError("月份须为 YYYY-MM")
    return value


def allocate(total, weights):
    cents = int(money(total) * 100)
    if not weights or len(weights) > 1000:
        raise ValueError("请选择 1 至 1000 条派车记录")
    values = [money(w or 0) for w in weights]
    # Incomplete mileage is not a reliable weight: use equal shares for all rows.
    if not all(w > 0 for w in values):
        values = [Decimal(1)] * len(values)
    weight_sum = sum(values)
    parts = [int((cents * w / weight_sum).to_integral_value(rounding=ROUND_DOWN)) for w in values]
    parts[-1] += cents - sum(parts)
    return [str(Decimal(p) / 100) for p in parts]
