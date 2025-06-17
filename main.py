# main.py
import asyncio
import logging
from typing import Set

from titan.logger import setup_logging
from titan.config import config
from titan.exchange_connector import ExchangeConnector
from titan.data_handler import DataHandler
from titan.strategy_logic import TitanStrategy
from titan.portfolio_manager import PortfolioManager
from titan.order_executor import OrderExecutor
from titan.orchestrator import MasterOrchestrator

async def main():
    """Initializes and runs all bot components as concurrent tasks."""
    # Logging is now setup in app.py
    logging.info(f"--- Main bot coroutine started in {config.MODE} mode ---")

    # This set will hold all our main running tasks
    running_tasks: Set[asyncio.Task] = set()

    try:
        # --- Initialize Queues ---
        market_data_q = asyncio.Queue()
        strategy_input_q = asyncio.Queue()
        signal_q = asyncio.Queue()
        order_q = asyncio.Queue()

        # --- Instantiate Modules ---
        # Note: In a real multi-bot system, a BotManager would dynamically create these workers.
        # This setup is for a single-symbol worker managed by the orchestrator's commands.
        connector = ExchangeConnector(symbols=config.SYMBOLS, output_queue=market_data_q)
        data_handler = DataHandler(input_queue=market_data_q, strategy_input_queue=strategy_input_q)
        portfolio_manager = PortfolioManager(symbol=config.SYMBOLS[0], signal_queue=signal_q, order_queue=order_q)
        strategy = TitanStrategy(symbol=config.SYMBOLS[0], input_queue=strategy_input_q, signal_queue=signal_q, portfolio_manager=portfolio_manager)
        order_executor = OrderExecutor(order_queue=order_q, connector=connector)
        orchestrator = MasterOrchestrator(bot_manager=None)

        # --- Create and track tasks ---
        tasks_to_run = [
            orchestrator.run(), 
            connector.run(),
            data_handler.run(),
            strategy.run(),
            portfolio_manager.run(),
            order_executor.run()
        ]
        
        for coro in tasks_to_run:
            task = asyncio.create_task(coro)
            running_tasks.add(task)
            task.add_done_callback(running_tasks.discard)

        logging.info(f"Starting {len(running_tasks)} concurrent bot tasks.")
        await asyncio.gather(*running_tasks)

    except asyncio.CancelledError:
        logging.info("Main bot coroutine was cancelled. Shutting down gracefully.")
    except Exception as e:
        logging.critical(f"A critical error occurred in the main bot task: {e}", exc_info=True)
    finally:
        logging.info("All bot tasks have concluded.")
