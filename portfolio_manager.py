# titan/portfolio_manager.py
import asyncio
import logging
import json
from pathlib import Path
from titan.config import config
from titan.datastructures import TradeSignal, Order, FillConfirmation, PriceUpdate

class PortfolioManager:
    """
    Manages state, risk, and grid logic for a single asset.
    Reacts to signals, fill confirmations, and live price updates.
    """
    def __init__(self, symbol: str, signal_queue: asyncio.Queue, order_queue: asyncio.Queue, fill_confirmation_queue: asyncio.Queue, price_update_queue: asyncio.Queue, initial_params: dict):
        self.symbol = symbol
        self.signal_queue = signal_queue
        self.order_queue = order_queue
        self.fill_confirmation_queue = fill_confirmation_queue
        self.price_update_queue = price_update_queue
        self.params = initial_params
        self.state_file = Path(f"./bot_state_{self.symbol}.json")

        # State variables
        self.balance_real = config.INITIAL_CAPITAL
        self.position_size = 0.0
        self.avg_entry_price = 0.0
        self.n_entries = 0
        self.long_grid_prices = []
        self.short_grid_prices = []
        self.last_known_price = 0.0

        self._load_state()

    def _load_state(self):
        # ... (implementation is correct and remains the same) ...

    def save_state(self):
        # ... (implementation is correct and remains the same) ...

    def get_position_status(self) -> str:
        if self.position_size > 0: return 'LONG'
        if self.position_size < 0: return 'SHORT'
        return 'FLAT'

    def _calculate_position_size(self, entry_price: float) -> float:
        # ... (implementation is correct and remains the same) ...

    async def _handle_signal(self, signal: TradeSignal):
        """Acts on a strategy signal to potentially place the first order."""
        current_status = self.get_position_status()

        # If signal is to go long but we are short, first exit the short
        if signal.signal_type == 'ENTRY_LONG' and current_status == 'SHORT':
            await self._exit_position(f"Trend reversal to {signal.signal_type}")
        
        # If signal is to go short but we are long, first exit the long
        elif signal.signal_type == 'ENTRY_SHORT' and current_status == 'LONG':
            await self._exit_position(f"Trend reversal to {signal.signal_type}")

        # If we are flat, initiate a new grid
        if self.get_position_status() == 'FLAT':
            if self.last_known_price > 0:
                await self._initiate_grid(signal.signal_type, self.last_known_price)
            else:
                logging.warning(f"[{self.symbol}] Cannot initiate grid, last known price is 0.")

    async def _initiate_grid(self, signal_type: str, entry_price: float):
        """Sends the first market order for a new grid."""
        logging.info(f"[{self.symbol}] Initiating new grid based on {signal_type} at price {entry_price}")
        side = 'BUY' if signal_type == 'ENTRY_LONG' else 'SELL'
        order_qty = self._calculate_position_size(entry_price)

        if order_qty <= 0: return

        await self.order_queue.put(Order(self.symbol, side, 'MARKET', qty=order_qty, tag='GRID_ENTRY_1'))

    def _handle_fill_confirmation(self, fill: FillConfirmation):
        """Updates position state and sets up the next grid levels after a confirmed fill."""
        logging.info(f"[{self.symbol}] Processing fill confirmation: {fill}")

        # --- Nuanced Fill Logic ---
        current_status = self.get_position_status()
        
        if fill.side == 'BUY':
            if current_status == 'SHORT': # This BUY is closing a SHORT position
                realized_pnl = (self.avg_entry_price - fill.price) * fill.qty
                self.balance_real += realized_pnl
                self.position_size += fill.qty # Moves position size towards 0
            else: # This BUY is opening/adding to a LONG position
                current_value = self.avg_entry_price * self.position_size
                new_value = fill.price * fill.qty
                self.position_size += fill.qty
                self.avg_entry_price = (current_value + new_value) / self.position_size if self.position_size > 0 else 0
                self.n_entries += 1
                self._setup_limit_grids(fill.price, fill.qty, 'BUY')

        elif fill.side == 'SELL':
            if current_status == 'LONG': # This SELL is closing a LONG position
                realized_pnl = (fill.price - self.avg_entry_price) * fill.qty
                self.balance_real += realized_pnl
                self.position_size -= fill.qty # Moves position size towards 0
            else: # This SELL is opening/adding to a SHORT position
                current_value = self.avg_entry_price * abs(self.position_size)
                new_value = fill.price * fill.qty
                self.position_size -= fill.qty
                self.avg_entry_price = (current_value + new_value) / abs(self.position_size) if self.position_size != 0 else 0
                self.n_entries += 1
                self._setup_limit_grids(fill.price, fill.qty, 'SELL')
        
        # If position is now flat, reset state
        if abs(self.position_size) < 1e-9: # Use tolerance for float comparison
            self._reset_position_state()

    def _reset_position_state(self):
        self.position_size = 0.0
        self.avg_entry_price = 0.0
        self.n_entries = 0
        self.long_grid_prices = []
        self.short_grid_prices = []
        logging.info(f"[{self.symbol}] Position is now flat. State has been reset.")

    def _setup_limit_grids(self, base_price: float, qty_per_entry: float, side: str):
        # ... (implementation is correct and remains the same) ...

    async def manage_dropped_position(self):
        # ... (implementation is correct and remains the same) ...

    async def _exit_position(self, reason: str):
        status = self.get_position_status()
        if status == 'FLAT': return

        logging.info(f"[{self.symbol}] Exiting position due to: {reason}")
        side_to_close = 'SELL' if status == 'LONG' else 'BUY'
        qty_to_close = abs(self.position_size)
        await self.order_queue.put(Order(self.symbol, side_to_close, 'MARKET', qty=qty_to_close, tag='EXIT_FLATTEN'))

    async def _signal_handler_loop(self):
        """Listens for high-level signals from the strategy."""
        while True:
            signal = await self.signal_queue.get()
            await self._handle_signal(signal)
            self.signal_queue.task_done()

    async def _fill_handler_loop(self):
        """Listens for fill confirmations from the executor."""
        while True:
            fill = await self.fill_confirmation_queue.get()
            self._handle_fill_confirmation(fill)
            self.fill_confirmation_queue.task_done()

    async def _price_update_loop(self):
        """Listens for live price updates to maintain situational awareness."""
        while True:
            price_update = await self.price_update_queue.get()
            self.last_known_price = price_update.price
            self.price_update_queue.task_done()

    async def run(self):
        """Main loop to process signals, fills, and price updates concurrently."""
        logging.info(f"PortfolioManager for {self.symbol} is running.")
        signal_task = asyncio.create_task(self._signal_handler_loop())
        fill_task = asyncio.create_task(self._fill_handler_loop())
        price_task = asyncio.create_task(self._price_update_loop())
        await asyncio.gather(signal_task, fill_task, price_task)
