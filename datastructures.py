# titan/datastructures.py
from dataclasses import dataclass
from typing import Literal

@dataclass
class TradeSignal:
    """Represents a high-level signal from the strategy logic."""
    symbol: str
    signal_type: Literal['ENTRY_LONG', 'ENTRY_SHORT', 'EXIT_LONG', 'EXIT_SHORT']
    reason: str

@dataclass
class Order:
    """Represents a concrete order to be executed."""
    symbol: str
    side: Literal['BUY', 'SELL']
    order_type: Literal['MARKET', 'LIMIT']
    qty: float
    price: float = None # Required for LIMIT orders
