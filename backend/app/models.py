import enum


class OrderStatus(str, enum.Enum):
    active = "active"
    shipped = "shipped"
    partially_returned = "partially_returned"
    returned = "returned"
    cancelled = "cancelled"


class ItemStatus(str, enum.Enum):
    active = "active"
    returned = "returned"
    cancelled = "cancelled"


class MessageResult(str, enum.Enum):
    extracted = "extracted"
    skipped_prefilter = "skipped_prefilter"
    skipped_llm = "skipped_llm"
    error = "error"
