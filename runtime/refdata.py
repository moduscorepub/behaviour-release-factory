# SPDX-FileCopyrightText: 2026 The behaviour-release-factory contributors
# SPDX-License-Identifier: MIT

"""Reference data for each universe, which maps each instrument ID to its currency."""

UNIVERSES: dict[str, dict[str, str]] = {
    "ust": {"UST2Y": "USD", "UST5Y": "USD", "UST10Y": "USD", "UST30Y": "USD"},
    "gilts": {
        "UKT-4.5-2028": "GBP",
        "UKT-4.25-2032": "GBP",
        "UKT-3.75-2038": "GBP",
    },
}
