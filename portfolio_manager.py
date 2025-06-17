# titan/portfolio_manager.py
import asyncio
import logging
from titan.config import config
from titan.datastructures import TradeSignal, Order

class PortfolioManager:
    """
    Manages position state, enforces risk rules, and translates abstract
    signals from the strategy into concrete, sized orders.
    This is the central state and risk authority for a single asset.
    """
    def __init__(self, symbol: str, signal_queue: asyncio.Queue, order_queue: asyncio.Queue):
        self.symbol = symbol
        self.signal_queue = signal_queue
        self.order_queue = order_queue
        
        # --- Position State ---
        self.balance_real = config.INITIAL_CAPITAL
        self.position_size = 0.0  # Positive for long, negative for short
        self.avg_entry_price = 0.0
        self.n_entries = 0

    def get_position_status(self) -> str:
        """Returns the current position status as a string."""
        if self.position_size > 0:
            return 'LONG'
        elif self.position_size < 0:
            return 'SHORT'
        return 'FLAT'

    def _calculate_position_size(self) -> float:
        """
        Calculates position size based on risk rules.
        This is a simplified version of fCalculateLongQuantity for the first entry.
        """
        # Rule 1: Max risk per order is 1% of total account value.
        risk_per_order_usd = self.balance_real * (config.RISK_PCT_PER_TRADE / 100.0)
        
        # Rule 2: Cumulative risk per ticker cannot exceed 3%. Since this is the first entry,
        # we ensure our single order doesn't exceed this.
        if config.RISK_PCT_PER_TRADE > 3.0:
             logging.warning(f"[{self.symbol}] Risk per trade ({config.RISK_PCT_PER_TRADE}%) exceeds max per ticker (3%). Clamping risk.")
             risk_per_order_usd = self.balance_real * (3.0 / 100.0)

        # Stop loss distance is based on the Grid Width from the Pine Script
        stop_loss_distance_pct = config.GRID_WIDTH_PCT / 100.0
        
        # We need the current price to calculate quantity from risk
        # This is a key piece of information that needs to be passed with the signal
        # or fetched. For now, we'll use a placeholder.
        # In a real system: last_price = data.iloc[-1]['close']
        last_price = 30000.0 # Placeholder
        
        quantity = risk_per_order_usd / (last_price * stop_loss_distance_pct)
        return quantity

    async def _handle_signal(self, signal: TradeSignal):
        """Processes a signal and generates orders if logic passes."""
        logging.info(f"PORTFOLIO: Processing signal: {signal}")
        current_status = self.get_position_status()
        
        # --- Exit Logic ---
        if (signal.signal_type == 'ENTRY_LONG' and current_status == 'SHORT') or \
           (signal.signal_type == 'ENTRY_SHORT' and current_status == 'LONG'):
            
            logging.info(f"[{self.symbol}] Trend reversal signal. Exiting current {current_status} position.")
            exit_side = 'BUY' if current_status == 'SHORT' else 'SELL'
            exit_order = Order(self.symbol, exit_side, 'MARKET', qty=abs(self.position_size))
            await self.order_queue.put(exit_order)
            self._reset_position_state() # Reset state after sending exit order
            # Wait a moment to allow exit order to be processed before placing a new entry
            await asyncio.sleep(1)

        # --- Entry Logic ---
        # Only enter if we are now (or were already) flat.
        if 'ENTRY' in signal.signal_type and self.get_position_status() == 'FLAT':
            if self.n_entries < config.MAX_ENTRIES:
                order_qty = self._calculate_position_size()
                
                if order_qty > 0:
                    side = 'BUY' if signal.signal_type == 'ENTRY_LONG' else 'SELL'
                    entry_order = Order(self.symbol, side, 'MARKET', qty=order_qty)
                    
                    logging.info(f"PORTFOLIO: Placing concrete order -> {entry_order}")
                    await self.order_queue.put(entry_order)
                    
                    # NOTE: This is an optimistic state update. A robust system would
                    # update its state only after receiving a fill confirmation from the fill_q.
                    self.n_entries += 1
                    # Further logic would update avg_entry_price and position_size upon fill.
            else:
                logging.warning(f"[{self.symbol}] Max entries ({config.MAX_ENTRIES}) reached. Ignoring new entry signal.")
    
    def _reset_position_state(self):
        """Resets state variables after a position is fully closed."""
        logging.info(f"[{self.symbol}] Resetting position state.")
        self.position_size = 0.0
        self.avg_entry_price = 0.0
        self.n_entries = 0
        self.current_risk_exposure = 0.0

    async def run(self):
        """Main run loop for the portfolio manager."""
        logging.info(f"PortfolioManager for {self.symbol} is running.")
        while True:
            signal = await self.signal_queue.get()
            if signal.symbol == self.symbol:
                await self._handle_signal(signal)
            self.signal_queue.task_done()
