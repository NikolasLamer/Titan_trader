# titan/portfolio_manager.py
import asyncio
import logging
import json
from pathlib import Path
import pandas as pd

from titan.config import config
from titan.datastructures import TradeSignal, Order, FillConfirmation

class PortfolioManager:
    """
    Manages state, risk, and full grid logic for a single asset.
    Reacts to signals to create orders and to fill confirmations to update state.
    """
    def __init__(self, symbol: str, signal_queue: asyncio.Queue, order_queue: asyncio.Queue, fill_confirmation_queue: asyncio.Queue, initial_params: dict):
        self.symbol = symbol
        self.signal_queue = signal_queue
        self.order_queue = order_queue
        self.fill_confirmation_queue = fill_confirmation_queue
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
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r') as f:
                    state = json.load(f)
                    self.balance_real = state.get('balance_real', config.INITIAL_CAPITAL)
                    self.position_size = state.get('position_size', 0.0)
                    self.avg_entry_price = state.get('avg_entry_price', 0.0)
                    self.n_entries = state.get('n_entries', 0)
                    self.long_grid_prices = state.get('long_grid_prices', [])
                    self.short_grid_prices = state.get('short_grid_prices', [])
                logging.info(f"[{self.symbol}] State loaded successfully.")
            except Exception as e:
                logging.error(f"[{self.symbol}] Failed to load state file: {e}")

    def save_state(self):
        state = {
            'balance_real': self.balance_real,
            'position_size': self.position_size,
            'avg_entry_price': self.avg_entry_price,
            'n_entries': self.n_entries,
            'long_grid_prices': self.long_grid_prices,
            'short_grid_prices': self.short_grid_prices,
        }
        try:
            with open(self.state_file, 'w') as f:
                json.dump(state, f, indent=4)
            logging.info(f"[{self.symbol}] State saved successfully.")
        except Exception as e:
            logging.error(f"[{self.symbol}] Failed to save state: {e}")

    def get_position_status(self) -> str:
        if self.position_size > 0: return 'LONG'
        if self.position_size < 0: return 'SHORT'
        return 'FLAT'

    def _calculate_position_size(self, entry_price: float) -> float:
        """Calculates position size based on the 1% risk rule."""
        if self.balance_real <= 0:
            return 0.0

        risk_amount_usd = self.balance_real * (config.RISK_PCT_PER_TRADE / 100.0)
        stop_loss_pct = config.GRID_WIDTH_PCT / 100.0

        if stop_loss_pct <= 0:
            logging.error(f"[{self.symbol}] Grid Width must be > 0 for risk calculation.")
            return 0.0

        position_size_usd = risk_amount_usd / stop_loss_pct
        order_qty = position_size_usd / entry_price

        logging.info(f"[{self.symbol}] Risk Calc: Equity=${self.balance_real:.2f}, Risk=${risk_amount_usd:.2f}, PosSize=${position_size_usd:.2f}, Qty={order_qty:.4f}")
        return order_qty

    async def _handle_signal(self, signal: TradeSignal):
        """Acts on a strategy signal to potentially place the first order."""
        current_status = self.get_position_status()

        if (signal.signal_type == 'ENTRY_LONG' and current_status == 'SHORT') or \
           (signal.signal_type == 'ENTRY_SHORT' and current_status == 'LONG'):
            await self._exit_position(f"Trend reversal to {signal.signal_type}")

        if 'ENTRY' in signal.signal_type and self.get_position_status() == 'FLAT':
            await self._initiate_grid(signal.signal_type, self.last_known_price)

    async def _initiate_grid(self, signal_type: str, entry_price: float):
        """Sends the first market order for a new grid."""
        logging.info(f"[{self.symbol}] Initiating new grid based on {signal_type} at price {entry_price}")
        side = 'BUY' if signal_type == 'ENTRY_LONG' else 'SELL'
        order_qty = self._calculate_position_size(entry_price)

        if order_qty <= 0: return

        await self.order_queue.put(Order(self.symbol, side, 'MARKET', qty=order_qty))

    def _handle_fill_confirmation(self, fill: FillConfirmation):
        """Updates position state and sets up the next grid levels after a confirmed fill."""
        logging.info(f"[{self.symbol}] Processing fill confirmation: {fill}")

        if fill.side == 'BUY':
            current_value = self.avg_entry_price * self.position_size
            new_value = fill.price * fill.qty
            self.position_size += fill.qty
            self.avg_entry_price = (current_value + new_value) / self.position_size if self.position_size > 0 else 0
        else: # SELL
            # This logic needs to handle both entering a new short and closing a long
            # For simplicity, we assume this fill is for a new short entry
            current_value = self.avg_entry_price * abs(self.position_size)
            new_value = fill.price * fill.qty
            self.position_size -= fill.qty
            self.avg_entry_price = (current_value + new_value) / abs(self.position_size) if self.position_size != 0 else 0

        self.n_entries += 1
        self._setup_limit_grids(fill.price, fill.qty, fill.side)

    def _setup_limit_grids(self, base_price: float, qty_per_entry: float, side: str):
        """Calculates and stages pending limit orders for the grid."""
        # This is where you would send LIMIT orders to the order_queue
        # For now, it just logs the intended grid.
        grid_pct = config.GRID_WIDTH_PCT / 100.0
        self.long_grid_prices, self.short_grid_prices = [], []

        if side == 'BUY':
            for i in range(1, config.MAX_ENTRIES):
                price = base_price * (1 - i * grid_pct)
                self.long_grid_prices.append(price)
                # Example of sending the limit order:
                # await self.order_queue.put(Order(self.symbol, 'BUY', 'LIMIT', qty=qty_per_entry, price=price))
        else: # SELL
            for i in range(1, config.MAX_ENTRIES):
                price = base_price * (1 + i * grid_pct)
                self.short_grid_prices.append(price)

        logging.info(f"[{self.symbol}] Grid setup complete. Staged {len(self.long_grid_prices or self.short_grid_prices)} limit orders.")

    async def manage_dropped_position(self):
        """Logic to handle a position when its token is dropped from the top 5."""
        logging.info(f"[{self.symbol}] Managing dropped position. Status: {self.get_position_status()}")
        # Placeholder for exit logic (e.g., market close, trailing stop)
        await self._exit_position("Token dropped from top 5")

    async def _exit_position(self, reason: str):
        """Places a market order to flatten the current position."""
        status = self.get_position_status()
        if status == 'FLAT': return

        logging.info(f"[{self.symbol}] Exiting position due to: {reason}")
        side_to_close = 'SELL' if status == 'LONG' else 'BUY'
        qty_to_close = abs(self.position_size)
        await self.order_queue.put(Order(self.symbol, side_to_close, 'MARKET', qty=qty_to_close))
        # State will be reset upon fill confirmation of this closing order

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

    async def run(self):
        """Main loop to process signals and fill confirmations concurrently."""
        logging.info(f"PortfolioManager for {self.symbol} is running.")
        signal_task = asyncio.create_task(self._signal_handler_loop())
        fill_task = asyncio.create_task(self._fill_handler_loop())
        await asyncio.gather(signal_task, fill_task)
