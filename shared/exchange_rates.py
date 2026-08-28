"""Shared exchange-rate lookup with a small in-process cache."""
from __future__ import annotations

import time
from typing import Any

import requests


class ExchangeRateError(RuntimeError):
    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = status_code


def get_exchange_rate(app: Any, from_currency: str, to_currency: str) -> dict[str, Any]:
    """Return a rate result reusable by pages and domain services."""
    source = str(from_currency or "").upper().strip()
    target = str(to_currency or "").upper().strip()
    if len(source) != 3 or len(target) != 3 or not source.isalpha() or not target.isalpha():
        raise ExchangeRateError("Invalid currency code", 400)

    def calculate(rates: dict[str, float]) -> float | None:
        if source == target:
            return 1.0
        if source not in rates or target not in rates:
            return None
        return round(float(rates[target]) / float(rates[source]), 6)

    cache = getattr(app, "_fx_cache", None)
    if cache is None:
        cache = {"rates": {}, "updated": None, "ts": 0}
        app._fx_cache = cache

    now = time.time()
    if cache["rates"] and now - cache["ts"] < 600:
        rate = calculate(cache["rates"])
        if rate is not None:
            return {
                "rate": rate,
                "from_cur": source,
                "to_cur": target,
                "updated": cache["updated"],
                "cached": True,
            }

    try:
        response = requests.get("https://open.er-api.com/v6/latest/USD", timeout=5)
        if response.status_code >= 400:
            raise RuntimeError(f"HTTP {response.status_code}")
        data = response.json()
        if data.get("result") != "success":
            raise RuntimeError("API returned non-success")
        cache["rates"] = data["rates"]
        cache["updated"] = data.get("time_last_update_utc", "")
        cache["ts"] = now
        rate = calculate(cache["rates"])
        if rate is None:
            raise ExchangeRateError(f"不支持币种 {source}/{target}", 400)
        return {
            "rate": rate,
            "from_cur": source,
            "to_cur": target,
            "updated": cache["updated"],
            "cached": False,
        }
    except ExchangeRateError:
        raise
    except Exception as exc:
        app.logger.warning("exchange-rate fetch failed: %s", exc)
        if cache["rates"]:
            rate = calculate(cache["rates"])
            if rate is not None:
                return {
                    "rate": rate,
                    "from_cur": source,
                    "to_cur": target,
                    "updated": cache["updated"],
                    "cached": True,
                    "stale": True,
                }
        raise ExchangeRateError("汇率获取失败，请稍后再试。") from exc
