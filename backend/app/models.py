import enum
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


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
