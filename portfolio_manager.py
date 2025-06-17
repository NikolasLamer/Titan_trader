# titan/portfolio_manager.py
import asyncio
import logging
import json
from pathlib import Path
from titan.config import config
from titan.datastructures import TradeSignal, Order

class PortfolioManager:
    """
    Manages state, risk, and grid logic for a single asset.
    Includes multi-entry logic and state persistence.
    """
    def __init__(self, symbol: str, signal_queue: asyncio.Queue, order_queue: asyncio.Queue):
        self.symbol = symbol
        self.signal_queue = signal_queue
        self.order_queue = order_queue
        self.state_file = Path(f"./bot_state_{self.symbol}.json")
        
        # --- State Management ---
        self.balance_real = config.INITIAL_CAPITAL
        self.position_size = 0.0
        self.avg_entry_price = 0.0
        self.n_entries = 0
        self.long_grid_orders = [] # Stores prices of pending limit buys
        self.short_grid_orders = [] # Stores prices of pending limit sells
        self.long_tp_orders = [] # Stores prices of pending take-profit sells
        self.short_tp_orders = [] # Stores prices of pending take-profit buys
        self.cumulative_risk_usd = 0.0

        self._load_state()

    # --- State Persistence ---
    def _load_state(self):
        """Loads the bot's state from a file on startup."""
        if self.state_file.exists():
            logging.info(f"[{self.symbol}] Found state file. Loading previous state.")
            with open(self.state_file, 'r') as f:
                state = json.load(f)
                self.balance_real = state.get('balance_real', config.INITIAL_CAPITAL)
                self.position_size = state.get('position_size', 0.0)
                self.avg_entry_price = state.get('avg_entry_price', 0.0)
                self.n_entries = state.get('n_entries', 0)
                self.long_grid_orders = state.get('long_grid_orders', [])
                # ... load other state variables ...
            logging.info(f"[{self.symbol}] State loaded: Pos Size {self.position_size:.4f}")

    def save_state(self):
        """Saves the current state to a file for persistence."""
        state = {
            'balance_real': self.balance_real,
            'position_size': self.position_size,
            'avg_entry_price': self.avg_entry_price,
            'n_entries': self.n_entries,
            'long_grid_orders': self.long_grid_orders,
             # ... save other state variables ...
        }
        logging.info(f"[{self.symbol}] Saving state: {state}")
        with open(self.state_file, 'w') as f:
            json.dump(state, f, indent=4)

    def get_position_status(self) -> str:
        if self.position_size > 0: return 'LONG'
        if self.position_size < 0: return 'SHORT'
        return 'FLAT'

    # --- Core Logic ---
    async def _handle_signal(self, signal: TradeSignal, data: pd.DataFrame):
        """Processes signals and manages grid logic."""
        current_status = self.get_position_status()
        last_price = data.iloc[-1]['close']

        # 1. Handle Trend Reversals (Exit existing position)
        if (signal.signal_type == 'ENTRY_LONG' and current_status == 'SHORT') or \
           (signal.signal_type == 'ENTRY_SHORT' and current_status == 'LONG'):
            logging.info(f"[{self.symbol}] Trend reversal. Exiting {current_status} position.")
            await self._exit_position(f"Trend reversal to {signal.signal_type}")
        
        # 2. Handle New Entries
        if 'ENTRY' in signal.signal_type and self.get_position_status() == 'FLAT':
            await self._initiate_grid(signal.signal_type, last_price)
        
        # 3. Handle Grid Fills (In a real bot, this would be triggered by fill events)
        # For simulation, we can check against the latest candle
        await self._check_simulated_fills(data.iloc[-1])

    async def _initiate_grid(self, signal_type: str, entry_price: float):
        """Places the first market order and sets up the entire grid."""
        if self.n_entries >= config.MAX_ENTRIES:
            return

        side = 'BUY' if signal_type == 'ENTRY_LONG' else 'SELL'
        order_qty = self._calculate_position_size(entry_price, side)

        if order_qty <= 0:
            return

        # Place initial market order
        await self.order_queue.put(Order(self.symbol, side, 'MARKET', qty=order_qty))
        
        # --- Optimistic state update (a real system waits for fill confirmation) ---
        self.n_entries = 1
        self.avg_entry_price = entry_price
        self.position_size = order_qty if side == 'BUY' else -order_qty
        risk_usd_this_trade = order_qty * (config.GRID_WIDTH_PCT / 100.0) * entry_price
        self.cumulative_risk_usd += risk_usd_this_trade
        logging.info(f"[{self.symbol}] Initial Entry. Pos Size: {self.position_size}, Avg Price: {self.avg_entry_price}, Risk Added: ${risk_usd_this_trade:.2f}")

        # --- Set up subsequent grid limit orders ---
        self._setup_limit_grids(entry_price, order_qty, side)

    def _setup_limit_grids(self, base_price: float, qty_per_entry: float, side: str):
        """Calculates and stages the pending limit orders for grid entries and TPs."""
        grid_pct = config.GRID_WIDTH_PCT / 100.0
        
        # Clear any old orders
        self.long_grid_orders, self.short_grid_orders, self.long_tp_orders, self.short_tp_orders = [], [], [], []

        if side == 'BUY':
            for i in range(1, config.MAX_ENTRIES):
                entry_p = base_price * (1 - i * grid_pct)
                self.long_grid_orders.append({'price': entry_p, 'qty': qty_per_entry})
            for i in range(1, config.MAX_ENTRIES + 1):
                 tp_p = base_price * (1 + i * grid_pct)
                 # This would need the progressive/equal exit logic from Titan.txt
                 self.long_tp_orders.append({'price': tp_p, 'qty': '...'})
            logging.info(f"[{self.symbol}] Staged {len(self.long_grid_orders)} limit buys and {len(self.long_tp_orders)} limit sells (TPs).")
        else: # SELL
             for i in range(1, config.MAX_ENTRIES):
                entry_p = base_price * (1 + i * grid_pct)
                self.short_grid_orders.append({'price': entry_p, 'qty': qty_per_entry})
             for i in range(1, config.MAX_ENTRIES + 1):
                tp_p = base_price * (1 - i * grid_pct)
                self.short_tp_orders.append({'price': tp_p, 'qty': '...'})
             logging.info(f"[{self.symbol}] Staged {len(self.short_grid_orders)} limit sells and {len(self.short_tp_orders)} limit buys (TPs).")

    async def _exit_position(self, reason: str):
        """Closes the entire current position with a market order."""
        status = self.get_position_status()
        if status == 'FLAT': return

        logging.info(f"[{self.symbol}] Exiting {status} position. Reason: {reason}")
        side = 'SELL' if status == 'LONG' else 'BUY'
        await self.order_queue.put(Order(self.symbol, side, 'MARKET', qty=abs(self.position_size)))
        self._reset_position_state()
    
    def _reset_position_state(self):
        """Resets all state variables after a position is fully closed."""
        logging.info(f"[{self.symbol}] Resetting position state.")
        self.position_size, self.avg_entry_price, self.n_entries, self.cumulative_risk_usd = 0.0, 0.0, 0, 0.0
        self.long_grid_orders, self.short_grid_orders, self.long_tp_orders, self.short_tp_orders = [], [], [], []
        self.save_state()

    # --- This method would be implemented for dropped token management ---
    async def manage_dropped_position(self):
        # This requires the current price, which this module would get from the DataHandler
        logging.info(f"[{self.symbol}] This token was dropped from the top 5. Managing position.")
        # ... logic to set SL to breakeven or 3% below current price ...
        pass

    async def run(self):
        """Main loop for the portfolio manager."""
        logging.info(f"PortfolioManager for {self.symbol} is running.")
        while True:
            # This logic needs to be enhanced to listen to the fill_q as well
            payload = await self.signal_queue.get()
            if payload['symbol'] == self.symbol:
                await self._handle_signal(payload['signal'], payload['data'])
            self.signal_queue.task_done()
