# titan/strategy_logic.py
import asyncio
import logging
import pandas as pd
from titan.datastructures import TradeSignal
from titan.portfolio_manager import PortfolioManager
from titan.config import config

class TitanStrategy:
    """
    Analyzes market data with indicators and generates trading signals.
    This module contains the "alpha" logic.
    """
    def __init__(
        self,
        symbol: str,
        input_queue: asyncio.Queue,
        signal_queue: asyncio.Queue,
        portfolio_manager: PortfolioManager
    ):
        self.symbol = symbol
        self.input_queue = input_queue
        self.signal_queue = signal_queue
        self.portfolio_manager = portfolio_manager
        self.last_signal_sent = None # To prevent spamming signals

    async def _generate_signals(self, data: pd.DataFrame):
        """The core logic translated from the TitanGrid Pine Script."""
        if data.empty:
            return

        # Dynamically get column names from pandas-ta attributes
        st_period = config.SUPERTREND_PERIOD
        st_multiplier = config.SUPERTREND_MULTIPLIER
        st_direction_col = f'SUPERTd_{st_period}_{st_multiplier}'

        if st_direction_col not in data.columns or len(data) < 2:
            logging.debug(f"SuperTrend column not ready for {self.symbol}. Waiting for more data.")
            return

        # Use the latest fully-formed candle for decisions
        last_row = data.iloc[-2]
        is_trend_up = last_row[st_direction_col] == 1
        is_trend_down = last_row[st_direction_col] == -1
        
        position_status = self.portfolio_manager.get_position_status()

        # --- Signal Generation Logic ---
        # This logic determines the desired state (LONG or SHORT).
        # The PortfolioManager will handle the transition (e.g., closing a short to go long).
        
        signal = None
        if is_trend_up and position_status != 'LONG':
            signal = TradeSignal(self.symbol, 'ENTRY_LONG', 'SuperTrend flipped to bullish')
            
        elif is_trend_down and position_status != 'SHORT':
            signal = TradeSignal(self.symbol, 'ENTRY_SHORT', 'SuperTrend flipped to bearish')

        # To prevent sending the same signal repeatedly, we check against the last one
        if signal and signal != self.last_signal_sent:
            logging.info(f"STRATEGY: Generated Signal -> {signal}")
            await self.signal_queue.put(signal)
            self.last_signal_sent = signal

    async def run(self):
        """Main loop to process data and generate signals."""
        logging.info(f"Strategy for {self.symbol} is running.")
        while True:
            payload = await self.input_queue.get()
            symbol = payload.get('symbol')
            data = payload.get('data')
            
            if symbol == self.symbol:
                await self._generate_signals(data)
            
            self.input_queue.task_done()
