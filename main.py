# main.py
import asyncio
import logging
import signal
from typing import Set

from titan.logger import setup_logging
from titan.config import config
from titan.exchange_connector import ExchangeConnector
from titan.data_handler import DataHandler
from titan.orchestrator import MasterOrchestrator
from titan.bot_manager import BotManager # Import BotManager

running_tasks: Set[asyncio.Task] = set()

def handle_shutdown(sig, loop, bot_manager: BotManager):
    """Gracefully stop all running asyncio tasks and save state."""
    logging.info(f"Received shutdown signal {sig.name}. Saving states and cancelling tasks...")
    if bot_manager:
        bot_manager.save_all_states()
    
    for task in running_tasks:
        task.cancel()

async def main():
    """Initializes and runs all bot components as concurrent tasks."""
    setup_logging()
    logging.info(f"Initializing TitanGrid Master Control in {config.MODE} mode...")

    # --- Instantiate Global/Shared Modules ---
    # These are shared across all potential bots
    market_data_q = asyncio.Queue()
    
    connector = ExchangeConnector(
        symbols=[], # The Orchestrator/BotManager will now manage subscriptions
        output_queue=market_data_q
    )
    
    data_handler = DataHandler(
        input_queue=market_data_q
    )

    # --- Instantiate Lifecycle and Orchestration Managers ---
    bot_manager = BotManager(connector=connector, data_handler=data_handler)
    orchestrator = MasterOrchestrator(bot_manager=bot_manager)

    # --- Create and Track Core Service Tasks ---
    tasks_to_run = [
        orchestrator.run(),
        connector.run(),
        data_handler.run(),
    ]
    
    global running_tasks
    for coro in tasks_to_run:
        task = asyncio.create_task(coro)
        running_tasks.add(task)
        task.add_done_callback(running_tasks.discard)

    logging.info(f"Starting {len(running_tasks)} core service tasks.")
    
    try:
        await asyncio.gather(*running_tasks)
    except asyncio.CancelledError:
        logging.info("Main task group cancelled.")

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    
    # We need a placeholder BotManager to pass to the shutdown handler
    # In a more complex app, this might be handled by a global context object
    temp_connector = ExchangeConnector(symbols=[], output_queue=asyncio.Queue())
    temp_data_handler = DataHandler(input_queue=asyncio.Queue())
    main_bot_manager = BotManager(connector=temp_connector, data_handler=temp_data_handler)
    
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, handle_shutdown, sig, loop, main_bot_manager)

    try:
        loop.run_until_complete(main())
    finally:
        logging.info("Bot shutdown complete.")
        loop.close()
