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


def complete_invoice_amounts(values):
    """Complete absent components without overwriting explicit amounts or rates.

    A total-only receipt uses the existing expense-record convention (no tax
    recorded). This is a suggestion for explicit confirmation, not a tax claim.
    """
    keys = ("amount", "tax_amount", "total_amount")
    amounts = {
        key: None if values.get(key) is None or str(values[key]).strip() == ""
        else money(values[key]) for key in keys
    }
    net, tax, total = (amounts[key] for key in keys)
    note = ""
    if total is not None:
        if net is None and tax is None:
            amounts.update(amount=total, tax_amount=money(0))
            note = "仅识别到票价，金额按票价、税额暂记0；不代表免税或可抵扣税额。请核对原票，有税额请补填。"
        elif net is None:
            amounts["amount"] = money(total - tax)
        elif tax is None:
            amounts["tax_amount"] = money(total - net)
    elif net is not None and tax is not None:
        amounts["total_amount"] = money(net + tax)
    return {key: "" if value is None else str(value) for key, value in amounts.items()}, note


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
