"""Instrument reference data per universe (id → currency)."""

UNIVERSES: dict[str, dict[str, str]] = {
    "ust": {"UST2Y": "USD", "UST5Y": "USD", "UST10Y": "USD", "UST30Y": "USD"},
    "gilts": {
        "UKT-4.5-2028": "GBP",
        "UKT-4.25-2032": "GBP",
        "UKT-3.75-2038": "GBP",
    },
}
