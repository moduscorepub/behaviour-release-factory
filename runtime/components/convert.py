"""Output converters: Decision -> downstream payload. Pure; publishing is the engine's broker."""


def bus_rfq_v1(d, desk: str) -> dict:
    return {"type": d.kind, "rfq_id": d.rfq_id, "desk": desk, "side": d.side, "instrument": d.instrument, "size": d.size, "ccy": d.ccy}


def chat_suggestion_v1(d, desk: str) -> dict:
    return {"rfq_id": d.rfq_id, "text": f"LIVE {d.side} {d.size / 10**6:g}mm {d.instrument} [{desk}]"}
