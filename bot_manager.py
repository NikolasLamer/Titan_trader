# titan/bot_manager.py
import asyncio
import logging
from typing import Dict

from titan.data_handler import DataHandler
from titan.exchange_connector import ExchangeConnector
from titan.order_executor import OrderExecutor
from titan.portfolio_manager import PortfolioManager
from titan.strategy_logic import TitanStrategy

class BotManager:
    """
    Creates, manages, and destroys trading bot instances for multiple symbols.
    """
    def __init__(self, connector: ExchangeConnector, data_handler: DataHandler):
        self.connector = connector
        self.data_handler = data_handler
        self.active_bots: Dict[str, Dict[str, any]] = {}

    def start_bot(self, symbol: str, params: dict):
        """Spawns a full set of trading tasks for a new symbol."""
        if symbol in self.active_bots:
            logging.warning(f"Bot for {symbol} is already running.")
            return

        logging.info(f"BOT MANAGER: Starting bot for {symbol} with params: {params}")

        # Create dedicated queues for this bot instance
        strategy_q = asyncio.Queue()
        signal_q = asyncio.Queue()
        order_q = asyncio.Queue()
        fill_confirmation_q = asyncio.Queue()
        price_update_q = asyncio.Queue() # New queue for live price updates

        # Register all queues with the DataHandler
        self.data_handler.register_bot_queues(symbol, strategy_q, price_update_q)
        self.connector.add_symbol(symbol)

        # Instantiate all components for the bot
        portfolio_manager = PortfolioManager(
            symbol=symbol,
            signal_queue=signal_q,
            order_queue=order_q,
            fill_confirmation_queue=fill_confirmation_q,
            price_update_queue=price_update_q, # Pass it here
            initial_params=params
        )
        strategy = TitanStrategy(
            symbol=symbol,
            input_queue=strategy_q,
            signal_queue=signal_q,
            portfolio_manager=portfolio_manager
        )
        order_executor = OrderExecutor(
            order_queue=order_q,
            connector=self.connector,
            fill_confirmation_queue=fill_confirmation_q
        )

        # Create and track all tasks for this bot
        tasks = {
            asyncio.create_task(strategy.run()),
            asyncio.create_task(portfolio_manager.run()),
            asyncio.create_task(order_executor.run()),
        }

        self.active_bots[symbol] = {
            "tasks": tasks,
            "portfolio_manager": portfolio_manager
        }
        logging.info(f"Bot for {symbol} is now active.")

    async def stop_bot(self, symbol: str, manage_position=True):
        """Stops the trading bot for a symbol, saving its state."""
        if symbol not in self.active_bots:
            return

        logging.info(f"BOT MANAGER: Stopping bot for {symbol}.")

        bot_instance = self.active_bots.pop(symbol)
        pm = bot_instance["portfolio_manager"]

        if manage_position:
            await pm.manage_dropped_position()

        pm.save_state()

        for task in bot_instance["tasks"]:
            task.cancel()

        await asyncio.gather(*bot_instance["tasks"], return_exceptions=True)
        self.data_handler.deregister_bot_queues(symbol)
        self.connector.remove_symbol(symbol)
        logging.info(f"Bot for {symbol} has been fully stopped.")

    def save_all_states(self):
        """Iterates through all active bots and saves their state."""
        logging.info("Saving state for all active bots on shutdown...")
        for symbol, bot_instance in self.active_bots.items():
            bot_instance["portfolio_manager"].save_state()
