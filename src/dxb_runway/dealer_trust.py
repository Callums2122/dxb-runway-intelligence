from __future__ import annotations

import re
from typing import Any

DIRECT_DEALERS = (
    "RMA Motors", "GTA Cars", "Linda Cars", "Elena Cars", "Expat Motors", "Cars24", "AW Rostamani", "NXT",
    "Al Naboodah", "Al Futtaim", "Al Ghandi", "Hi Car", "Trading Enterprises", "Elite Cars", "Sun City", "CV Auto",
    "Approved", "VIP Motors", "Stoub.biz", "Pearl Motors", "Park Lane", "Zeus Auto", "Blackline Motors",
)
CONSIDER_DEALERS = (
    "Honey Jidosha", "Kavak", "Dubizzle Cars", "8 BA Motors", "Al Qassim", "Auto Max", "Auto Bank", "Phillipine",
    "Faris Auto", "RDM Motors", "The Car Superstore", "Car Buying People",
)
EXCLUDED_DEALERS = ("Sharjah Dealer", "Sharjah", "Ajman", "Ras Al Khor", "Al Aweer")


def _key(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def dealer_evidence(offer: dict[str, Any]) -> tuple[str, float, str]:
    seller=offer.get("marketSeller") or {}; name=str(seller.get("name") or ""); location=str(offer.get("shortAddress") or offer.get("address") or "")
    combined=_key(f"{name} {location}")
    if any(_key(value) in combined for value in EXCLUDED_DEALERS):return "exclude",0.0,name or location
    city_weight=1.15 if "dubai" in location.casefold() else 1.0
    if any(_key(value) in _key(name) or _key(name) in _key(value) for value in DIRECT_DEALERS if name):return "direct",1.25*city_weight,name
    if any(_key(value) in _key(name) or _key(name) in _key(value) for value in CONSIDER_DEALERS if name):return "consider",0.85*city_weight,name
    return "unrated",0.70*city_weight,name or "Unknown dealer"


def weighted_median(values: list[tuple[float,float]]) -> float | None:
    valid=sorted((float(value),max(0.0,float(weight))) for value,weight in values if value is not None and float(weight)>0)
    if not valid:return None
    halfway=sum(weight for _,weight in valid)/2; running=0.0
    for value,weight in valid:
        running+=weight
        if running>=halfway:return value
    return valid[-1][0]
