# titan/portfolio_manager.py
import asyncio
import logging
import json
from pathlib import Path
from titan.config import config
from titan.datastructures import TradeSignal, Order

class PortfolioManager:
    """
    Manages position state, enforces risk rules, and translates abstract
    signals from the strategy into concrete, sized orders.
    This version includes multi-entry grid logic and state persistence.
    """
    def __init__(self, symbol: str, signal_queue: asyncio.Queue, order_queue: asyncio.Queue):
        self.symbol = symbol
        self.signal_queue = signal_queue
        self.order_queue = order_queue
        self.state_file = Path(f"./bot_state_{self.symbol}.json")
        
        # --- Core State ---
        self.balance_real = config.INITIAL_CAPITAL
        self.position_size = 0.0
        self.avg_entry_price = 0.0
        self.n_entries = 0
        
        # --- Grid State ---
        # Translates Pine Script arrays: LongLimitPrices, CloseLongLimitPrices, etc.
        self.long_grid_orders = []
        self.short_grid_orders = []
        self.long_tp_orders = []
        self.short_tp_orders = []

        self._load_state()

    def _load_state(self):
        """Loads the bot's state from a file on startup."""
        if self.state_file.exists():
            logging.info(f"[{self.symbol}] Found state file. Loading previous state.")
            with open(self.state_file, 'r') as f:
                state = json.load(f)
                self.position_size = state.get('position_size', 0.0)
                self.avg_entry_price = state.get('avg_entry_price', 0.0)
                self.n_entries = state.get('n_entries', 0)
                # In a real system, you'd also load and re-establish grid/tp orders
            logging.info(f"[{self.symbol}] State loaded: Pos Size {self.position_size}, Avg Price {self.avg_entry_price}")

    def save_state(self):
        """Saves the current state to a file for persistence."""
        state = {
            'position_size': self.position_size,
            'avg_entry_price': self.avg_entry_price,
            'n_entries': self.n_entries
        }
        logging.info(f"[{self.symbol}] Saving state: {state}")
        with open(self.state_file, 'w') as f:
            json.dump(state, f, indent=4)

    def get_position_status(self) -> str:
        # ... (same as before) ...
        if self.position_size > 0: return 'LONG'
        if self.position_size < 0: return 'SHORT'
        return 'FLAT'

    def _calculate_position_size(self, entry_price: float) -> float:
        # ... (logic is sound, but we'll use the entry_price now) ...
        risk_per_order_usd = self.balance_real * (config.RISK_PCT_PER_TRADE / 100.0)
        stop_loss_distance_pct = config.GRID_WIDTH_PCT / 100.0
        
        if entry_price <= 0: return 0.0
        
        quantity = risk_per_order_usd / (entry_price * stop_loss_distance_pct)
        return quantity

    async def _handle_signal(self, signal: TradeSignal, data: pd.DataFrame):
        """Processes signals and manages the grid based on the latest price data."""
        logging.info(f"PORTFOLIO: Processing signal: {signal}")
        current_status = self.get_position_status()
        last_price = data.iloc[-1]['close']

        # --- Exit Logic for Trend Reversal ---
        if (signal.signal_type == 'ENTRY_LONG' and current_status == 'SHORT') or \
           (signal.signal_type == 'ENTRY_SHORT' and current_status == 'LONG'):
            logging.info(f"[{self.symbol}] Trend reversal signal. Exiting current {current_status} position.")
            exit_order = Order(self.symbol, 'BUY' if current_status == 'SHORT' else 'SELL', 'MARKET', qty=abs(self.position_size))
            await self.order_queue.put(exit_order)
            self._reset_position_state()
            await asyncio.sleep(1)

        # --- Grid Entry Logic ---
        if 'ENTRY' in signal.signal_type:
            # This logic block now replaces the simplified entry logic
            await self._manage_grid_entry(signal.signal_type, last_price)
            
    async def _manage_grid_entry(self, signal_type: str, current_price: float):
        """
        Manages scaling into a position with multiple grid entries.
        This is the core translation of the complex grid loop in Pine Script.
        """
        if self.n_entries >= config.MAX_ENTRIES:
            logging.warning(f"[{self.symbol}] Max entries ({config.MAX_ENTRIES}) reached. Ignoring new entry.")
            return

        # Determine side and calculate order quantity
        side = 'BUY' if signal_type == 'ENTRY_LONG' else 'SELL'
        order_qty = self._calculate_position_size(current_price)

        if order_qty <= 0:
            logging.warning(f"[{self.symbol}] Calculated order quantity is zero. Skipping entry.")
            return

        # Place the first market order
        entry_order = Order(self.symbol, side, 'MARKET', qty=order_qty)
        logging.info(f"PORTFOLIO: Placing initial grid order -> {entry_order}")
        await self.order_queue.put(entry_order)
        self.n_entries += 1
        
        # --- Set up subsequent grid limit orders ---
        # This part translates the logic for setting up LongLimitPrices/ShortLimitPrices
        # and CloseLongLimitPrices/CloseShortLimitPrices
        
        grid_width_factor = config.GRID_WIDTH_PCT / 100.0
        
        # Naively update state here - a robust system waits for fills.
        # This logic is for demonstration of the grid setup.
        self.avg_entry_price = current_price # Simplified for first entry
        self.position_size += order_qty if side == 'BUY' else -order_qty
        
        # Set up the next grid entry orders
        for i in range(1, config.MAX_ENTRIES):
            if side == 'BUY':
                entry_price = self.avg_entry_price * (1 - i * grid_width_factor)
                next_entry_order = Order(self.symbol, 'BUY', 'LIMIT', qty=order_qty, price=entry_price)
                # await self.order_queue.put(next_entry_order) # This would place the limit orders
                logging.info(f"PORTFOLIO: Staging next grid entry -> {next_entry_order}")
            else: # SELL
                entry_price = self.avg_entry_price * (1 + i * grid_width_factor)
                next_entry_order = Order(self.symbol, 'SELL', 'LIMIT', qty=order_qty, price=entry_price)
                # await self.order_queue.put(next_entry_order)
                logging.info(f"PORTFOLIO: Staging next grid entry -> {next_entry_order}")
                
    def _reset_position_state(self):
        logging.info(f"[{self.symbol}] Resetting position state.")
        self.position_size = 0.0
        self.avg_entry_price = 0.0
        self.n_entries = 0
        self.save_state() # Save the reset state

    async def run(self):
        logging.info(f"PortfolioManager for {self.symbol} is running.")
        while True:
            # The portfolio manager now needs both signals and price data to manage the grid
            payload = await self.signal_queue.get()
            if payload['symbol'] == self.symbol:
                await self._handle_signal(payload['signal'], payload['data'])
            self.signal_queue.task_done()
