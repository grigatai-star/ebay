"""Разбор немецких (и английских) текстовых кусочков из карточек eBay.

Всё построено на регулярках по тексту карточки, а не на CSS-классах: eBay
переименовывает классы каждые несколько месяцев, а слова "Gebote", "Versand",
"EUR" стабильны годами.
"""

from __future__ import annotations

import re
from typing import Optional

# --- цена -------------------------------------------------------------------

# "EUR 123,45", "123,45 EUR", "123,45 €", "€123.45", "US $99.00"
_PRICE_RE = re.compile(
    r"(?:EUR|€|\bUS\s*\$|\$|\bGBP|£)\s*([\d][\d.\s ']*,\d{2}|[\d][\d,\s ']*\.\d{2}|[\d][\d.\s ']*)"
    r"|([\d][\d.\s ']*,\d{2}|[\d][\d,\s ']*\.\d{2})\s*(?:EUR|€)",
    re.IGNORECASE,
)

_FREE_SHIPPING_RE = re.compile(
    r"(kostenlose[rn]?\s+versand|gratis\s*versand|versandkostenfrei|free\s+(?:postage|shipping|delivery))",
    re.IGNORECASE,
)
# "+ EUR 5,49 Versand", "+EUR 4,99 Versand", "EUR 6,99 Versand"
_SHIPPING_RE = re.compile(
    r"(?:\+\s*)?((?:EUR|€)\s*[\d][\d.,\s ']*)\s*(?:Versand|Porto|shipping|postage)",
    re.IGNORECASE,
)

# --- ставки -----------------------------------------------------------------

# "1 Gebot", "12 Gebote", "0 Gebote", англ. "5 bids"
# Число ставок всегда небольшое и без разделителей тысяч; жадный класс с
# пробелами склеивал бы "132,50 14 Gebote" в "5014".
_BIDS_RE = re.compile(r"(?<![\d,.])(\d{1,4})\s*(Gebote?n?|bids?)\b", re.IGNORECASE)

# --- остаток времени --------------------------------------------------------

_DAYS_RE = re.compile(r"(\d+)\s*(?:T\b|Tage?n?\b|d\b|days?\b)", re.IGNORECASE)
_HOURS_RE = re.compile(r"(\d+)\s*(?:Std\.?|Stunden?|h\b|hrs?\b|hours?\b)", re.IGNORECASE)
_MINUTES_RE = re.compile(r"(\d+)\s*(?:Min\.?|Minuten?|m\b|mins?\b)", re.IGNORECASE)
_SECONDS_RE = re.compile(r"(\d+)\s*(?:Sek\.?|Sekunden?|s\b|secs?\b)", re.IGNORECASE)
_TIME_LEFT_MARKER = re.compile(
    r"(Noch\b|Restzeit|verbleibend|endet\s+in|left\b|remaining)", re.IGNORECASE
)

# --- состояние --------------------------------------------------------------

_CONDITIONS = [
    ("defekt", "defekt"),
    ("als ersatzteil", "defekt"),
    ("for parts", "defekt"),
    ("brandneu", "neu"),
    ("nagelneu", "neu"),
    ("neu mit etikett", "neu"),
    ("neu (sonstige)", "neu_sonstige"),
    ("neuwertig", "neuwertig"),
    ("generalüberholt", "refurbished"),
    ("refurbished", "refurbished"),
    ("runderneuert", "refurbished"),
    ("vom verkäufer generalüberholt", "refurbished"),
    ("gebraucht", "gebraucht"),
    ("pre-owned", "gebraucht"),
    ("neu", "neu"),
]

_ITEM_ID_RE = re.compile(r"/itm/(?:[^/?#]*/)?(\d{9,15})")


def _to_float(raw: str) -> Optional[float]:
    """'1.234,56' -> 1234.56, '1,234.56' -> 1234.56, '99' -> 99.0."""
    s = re.sub(r"[^\d.,]", "", raw or "")
    if not s:
        return None
    if "," in s and "." in s:
        # какой разделитель ближе к концу — тот десятичный
        s = s.replace(".", "") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
        s = s.replace(",", ".")
    elif "," in s:
        # "1234,56" -> дробная часть; "1.234" уже обработано выше
        s = s.replace(",", ".") if re.search(r",\d{1,2}$", s) else s.replace(",", "")
    else:
        # только точки: "1.234" -> тысячи, "12.34" -> дробь
        if re.search(r"\.\d{3}(?:\D|$)", s) and not re.search(r"\.\d{1,2}$", s):
            s = s.replace(".", "")
    try:
        return round(float(s), 2)
    except ValueError:
        return None


def parse_price(text: str) -> Optional[float]:
    """Первая цена в тексте. Для диапазона 'EUR 80,00 bis EUR 120,00' вернёт нижнюю."""
    if not text:
        return None
    m = _PRICE_RE.search(text)
    if not m:
        return None
    return _to_float(m.group(1) or m.group(2) or "")


def parse_shipping(text: str) -> Optional[float]:
    """Стоимость доставки. 0.0 при бесплатной, None если не указана."""
    if not text:
        return None
    if _FREE_SHIPPING_RE.search(text):
        return 0.0
    m = _SHIPPING_RE.search(text)
    if not m:
        return None
    return _to_float(m.group(1))


def parse_bids(text: str) -> Optional[int]:
    """Число ставок. '1 Gebot' -> 1, '0 Gebote' -> 0, нет упоминания -> None."""
    if not text:
        return None
    m = _BIDS_RE.search(text)
    if not m:
        return None
    val = _to_float(m.group(1))
    return int(val) if val is not None else None


def parse_time_left(text: str) -> Optional[int]:
    """Остаток времени в секундах из '(Noch) 1T 04Std', '23Std 14Min', '5Min'."""
    if not text:
        return None
    window = text
    marker = _TIME_LEFT_MARKER.search(text)
    if marker:
        # берём кусок сразу после маркера, чтобы не поймать "3 Tage Rückgabe"
        window = text[marker.start(): marker.start() + 60]
    elif not re.search(r"\d+\s*(?:T|Std|Min|Sek)\b", text):
        return None

    days = _DAYS_RE.search(window)
    hours = _HOURS_RE.search(window)
    minutes = _MINUTES_RE.search(window)
    seconds = _SECONDS_RE.search(window)
    if not any((days, hours, minutes, seconds)):
        return None
    total = 0
    if days:
        total += int(days.group(1)) * 86400
    if hours:
        total += int(hours.group(1)) * 3600
    if minutes:
        total += int(minutes.group(1)) * 60
    if seconds:
        total += int(seconds.group(1))
    return total or None


def parse_condition(text: str) -> str:
    low = (text or "").lower()
    for needle, label in _CONDITIONS:
        if needle in low:
            return label
    return ""


def parse_item_id(url: str) -> Optional[str]:
    if not url:
        return None
    m = _ITEM_ID_RE.search(url)
    return m.group(1) if m else None


def looks_sold(text: str) -> Optional[bool]:
    """Для режима completed: 'Verkauft', 'Sold' -> True, 'Nicht verkauft' -> False."""
    if not text:
        return None
    low = text.lower()
    if "nicht verkauft" in low or "unsold" in low:
        return False
    if re.search(r"\bverkauft\b|\bsold\b", low):
        return True
    return None


def normalize_ws(text: str) -> str:
    return re.sub(r"[\s ]+", " ", text or "").strip()
