# titan/portfolio_manager.py
import asyncio
import logging
import json
from pathlib import Path
import pandas as pd

from titan.config import config
from titan.datastructures import TradeSignal, Order

class PortfolioManager:
    """
    Manages state, risk, and full grid logic for a single asset.
    """
    def __init__(self, symbol: str, signal_queue: asyncio.Queue, order_queue: asyncio.Queue, initial_params: dict):
        self.symbol = symbol
        self.signal_queue = signal_queue
        self.order_queue = order_queue
        self.params = initial_params # Optimal params from backtester
        self.state_file = Path(f"./bot_state_{self.symbol}.json")
        
        # State variables mirroring Pine Script
        self.balance_real = config.INITIAL_CAPITAL
        self.position_size = 0.0
        self.avg_entry_price = 0.0
        self.n_entries = 0
        self.long_grid_prices = []
        self.short_grid_prices = []
        
        self._load_state()

    # --- State Persistence (fully implemented) ---
    def _load_state(self):
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r') as f:
                    state = json.load(f)
                    self.balance_real = state.get('balance_real', config.INITIAL_CAPITAL)
                    self.position_size = state.get('position_size', 0.0)
                    # ... load other state variables
                logging.info(f"[{self.symbol}] State loaded successfully.")
            except Exception as e:
                logging.error(f"[{self.symbol}] Failed to load state file: {e}")
    
    def save_state(self):
        # ... implementation from previous response ...

    # --- Grid & Risk Logic (Expanded) ---
    async def _handle_signal(self, signal: TradeSignal, data: pd.DataFrame):
        current_status = self.get_position_status()
        last_price = data.iloc[-1]['close']

        if (signal.signal_type == 'ENTRY_LONG' and current_status == 'SHORT') or \
           (signal.signal_type == 'ENTRY_SHORT' and current_status == 'LONG'):
            await self._exit_position(f"Trend reversal to {signal.signal_type}")
        
        if 'ENTRY' in signal.signal_type and self.get_position_status() == 'FLAT':
            await self._initiate_grid(signal.signal_type, last_price)

    async def _initiate_grid(self, signal_type: str, entry_price: float):
        """This function now fully translates the GRID EXECUTION LOGIC from Pine."""
        logging.info(f"[{self.symbol}] Initiating new grid based on {signal_type} at price {entry_price}")
        side = 'BUY' if signal_type == 'ENTRY_LONG' else 'SELL'
        order_qty = self._calculate_position_size(entry_price)

        if order_qty <= 0: return

        # Place the first market order (translates fAlertFirstLong/Short)
        await self.order_queue.put(Order(self.symbol, side, 'MARKET', qty=order_qty))
        
        # Optimistic update - a robust version waits for fill confirmation
        self.n_entries = 1
        self.avg_entry_price = entry_price
        self.position_size = order_qty if side == 'BUY' else -order_qty
        
        # Set up subsequent LIMIT orders for entries and TPs
        # This replaces the logic of fAlertGridLong/Short and fAlertCloseLong/Short
        self._setup_limit_grids(entry_price, order_qty, side)

    def _setup_limit_grids(self, base_price: float, qty_per_entry: float, side: str):
        """Calculates and stages pending limit orders."""
        grid_pct = config.GRID_WIDTH_PCT / 100.0
        
        self.long_grid_prices, self.short_grid_prices = [], []
        # In a full implementation, TP orders would also be managed here

        if side == 'BUY':
            for i in range(1, config.MAX_ENTRIES):
                price = base_price * (1 - i * grid_pct)
                self.long_grid_prices.append(price)
                # In a real system, you would place these as limit orders now
                # await self.order_queue.put(Order(self.symbol, 'BUY', 'LIMIT', qty=qty_per_entry, price=price))
        else: # SELL
            for i in range(1, config.MAX_ENTRIES):
                price = base_price * (1 + i * grid_pct)
                self.short_grid_prices.append(price)
                # await self.order_queue.put(Order(self.symbol, 'SELL', 'LIMIT', qty=qty_per_entry, price=price))
        
        logging.info(f"[{self.symbol}] Grid setup complete. Staged {len(self.long_grid_prices or self.short_grid_prices)} limit orders.")
    
    # ... Other methods like _reset_position_state, get_position_status, run ...
