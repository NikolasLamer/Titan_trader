# titan/datastructures.py
from dataclasses import dataclass
from typing import Literal, Optional

@dataclass
class TradeSignal:
    """Represents a high-level signal from the strategy logic."""
    symbol: str
    signal_type: Literal['ENTRY_LONG', 'ENTRY_SHORT'] # Simplified to entry signals only
    reason: str

@dataclass
class Order:
    """Represents a concrete order to be executed."""
    symbol: str
    side: Literal['BUY', 'SELL']
    order_type: Literal['MARKET', 'LIMIT']
    qty: float
    price: Optional[float] = None # Required for LIMIT orders
    # Add a tag to distinguish order intent (e.g., closing a position vs. opening)
    tag: Optional[str] = None

@dataclass
class FillConfirmation:
    """Represents a confirmed trade fill from the exchange."""
    symbol: str
    order_id: str
    side: Literal['BUY', 'SELL']
    qty: float
    price: float
    tag: Optional[str] = None # Carry the tag from the order

@dataclass
class PriceUpdate:
    """Represents the latest price update for a symbol."""
    symbol: str
    price: float
