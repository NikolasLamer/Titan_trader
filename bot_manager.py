# titan/bot_manager.py
import asyncio
import logging
from typing import Dict, Set

from titan.config import config
from titan.exchange_connector import ExchangeConnector
from titan.data_handler import DataHandler
from titan.strategy_logic import TitanStrategy
from titan.portfolio_manager import PortfolioManager
from titan.order_executor import OrderExecutor

class BotManager:
    """
    Creates, manages, and destroys trading bot instances for multiple symbols.
    Each bot is a complete set of interconnected asyncio tasks.
    """
    def __init__(self, connector: ExchangeConnector, data_handler: DataHandler):
        self.connector = connector
        self.data_handler = data_handler
        self.active_bots: Dict[str, Dict[str, any]] = {}

    def start_bot(self, symbol: str, params: dict):
        """Spawns a full set of trading tasks for a new symbol."""
        if symbol in self.active_bots:
            logging.warning(f"Bot for {symbol} is already running. Ignoring start command.")
            return

        logging.info(f"BOT MANAGER: Starting bot for {symbol} with params: {params}")

        # Create a dedicated set of queues for this bot instance
        strategy_input_q = asyncio.Queue()
        signal_q = asyncio.Queue()
        order_q = asyncio.Queue()
        
        # Link the DataHandler to this bot's specific queue
        self.data_handler.register_strategy_queue(symbol, strategy_input_q)

        # Instantiate all modules for the new bot
        portfolio_manager = PortfolioManager(symbol=symbol, signal_queue=signal_q, order_queue=order_q)
        strategy = TitanStrategy(
            symbol=symbol,
            input_queue=strategy_input_q,
            signal_queue=signal_q,
            portfolio_manager=portfolio_manager
        )
        order_executor = OrderExecutor(order_queue=order_q, connector=self.connector)

        tasks = {
            asyncio.create_task(strategy.run()),
            asyncio.create_task(portfolio_manager.run()),
            asyncio.create_task(order_executor.run()),
        }
        
        self.active_bots[symbol] = {
            "tasks": tasks,
            "portfolio_manager": portfolio_manager
        }
        logging.info(f"Bot for {symbol} is now active with {len(tasks)} tasks.")

    async def stop_bot(self, symbol: str):
        """Stops the trading bot for a symbol."""
        if symbol not in self.active_bots:
            logging.warning(f"No active bot found for {symbol} to stop.")
            return

        logging.info(f"BOT MANAGER: Stopping bot for {symbol}.")
        
        bot_instance = self.active_bots.pop(symbol)
        
        # --- Manage Dropped Position ---
        # A more robust implementation would fetch the current price here to pass it
        # to the position management logic.
        await bot_instance["portfolio_manager"].manage_dropped_position()
        
        # --- Save Final State ---
        bot_instance["portfolio_manager"].save_state()

        # --- Cancel Tasks ---
        for task in bot_instance["tasks"]:
            task.cancel()
        
        await asyncio.gather(*bot_instance["tasks"], return_exceptions=True)
        self.data_handler.deregister_strategy_queue(symbol)
        logging.info(f"Bot for {symbol} has been stopped and state saved.")

    def save_all_states(self):
        """Iterates through all active bots and saves their state."""
        logging.info("Saving state for all active bots...")
        for symbol, bot_instance in self.active_bots.items():
            logging.info(f"Saving state for {symbol}...")
            bot_instance["portfolio_manager"].save_state()
