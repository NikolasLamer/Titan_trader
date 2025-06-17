# titan/bot_manager.py
import asyncio
import logging
from typing import Dict, Set

from titan.config import config
from titan.datastructures import Order, TradeSignal
from titan.exchange_connector import ExchangeConnector
from titan.data_handler import DataHandler
from titan.strategy_logic import TitanStrategy
from titan.portfolio_manager import PortfolioManager
from titan.order_executor import OrderExecutor

class BotManager:
    """
    Manages the lifecycle of active trading bot instances for multiple symbols.
    """
    def __init__(self, connector: ExchangeConnector):
        self.connector = connector
        self.active_bots: Dict[str, Set[asyncio.Task]] = {}

    def start_bot(self, symbol: str, params: dict):
        """Spawns a full set of trading tasks for a new symbol."""
        if symbol in self.active_bots:
            logging.warning(f"Bot for {symbol} is already running. Ignoring start command.")
            return

        logging.info(f"BOT MANAGER: Starting bot for {symbol} with params: {params}")

        # Create a dedicated set of queues for this bot instance
        market_data_q = asyncio.Queue()
        strategy_input_q = asyncio.Queue()
        signal_q = asyncio.Queue()
        order_q = asyncio.Queue()

        # Update the connector to subscribe to the new symbol's data
        # In a real system, you'd manage subscriptions dynamically
        # For now, we assume the connector is already subscribed or can handle it.
        if symbol not in self.connector.symbols:
             logging.warning(f"Symbol {symbol} not in connector's initial list. Subscription might be required.")
             # self.connector.add_subscription(symbol) # Conceptual method

        # Instantiate all modules for the new bot
        # NOTE: The DataHandler needs to be adapted to handle per-bot data streams
        # This implementation shares the data handler for simplicity.
        portfolio_manager = PortfolioManager(symbol=symbol, signal_queue=signal_q, order_queue=order_q)
        strategy = TitanStrategy(symbol=symbol, input_queue=strategy_input_q, signal_queue=signal_q, portfolio_manager=portfolio_manager)
        order_executor = OrderExecutor(order_queue=order_q, connector=self.connector)

        tasks = {
            asyncio.create_task(strategy.run()),
            asyncio.create_task(portfolio_manager.run()),
            asyncio.create_task(order_executor.run()),
        }
        self.active_bots[symbol] = tasks
        logging.info(f"Bot for {symbol} is now active with {len(tasks)} tasks.")

    async def stop_bot(self, symbol: str):
        """Stops the trading bot for a symbol and handles its open position."""
        if symbol not in self.active_bots:
            logging.warning(f"No active bot found for {symbol} to stop.")
            return

        logging.info(f"BOT MANAGER: Stopping bot for {symbol}.")
        
        # Here you would retrieve the portfolio_manager instance for the bot
        # and call its position management logic before shutting down.
        # This requires passing module instances to the BotManager.
        # For now, we log the command.
        logging.info(f"COMMAND: Manage dropped position for {symbol}.")
        
        tasks = self.active_bots.pop(symbol)
        for task in tasks:
            task.cancel()
        
        await asyncio.gather(*tasks, return_exceptions=True)
        logging.info(f"Bot for {symbol} has been stopped.")
