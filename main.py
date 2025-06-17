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
from titan.bot_manager import BotManager

running_tasks: Set[asyncio.Task] = set()
# Global reference to the BotManager for the signal handler
main_bot_manager: BotManager = None

def handle_shutdown(sig, loop):
    """Gracefully stop all running asyncio tasks and save state."""
    logging.info(f"Received shutdown signal {sig.name}. Saving states and cancelling tasks...")
    if main_bot_manager:
        main_bot_manager.save_all_states()
    
    for task in list(running_tasks): # Use a copy to iterate
        task.cancel()

async def main():
    """Initializes and runs all bot components as concurrent tasks."""
    global main_bot_manager
    setup_logging()
    logging.info(f"Initializing TitanGrid Master Control in {config.MODE} mode...")

    # Instantiate Global/Shared Modules
    market_data_q = asyncio.Queue()
    
    connector = ExchangeConnector(
        symbols=[],
        output_queue=market_data_q
    )
    
    data_handler = DataHandler(
        input_queue=market_data_q
    )

    # Instantiate Lifecycle and Orchestration Managers
    main_bot_manager = BotManager(connector=connector, data_handler=data_handler)
    orchestrator = MasterOrchestrator(bot_manager=main_bot_manager)

    # Create and Track Core Service Tasks
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
    
    for sig in (signal.SIGINT, signal.SIGTERM):
        # Use a lambda to pass the loop without executing the function immediately
        loop.add_signal_handler(sig, lambda s=sig: handle_shutdown(s, loop))

    try:
        loop.run_until_complete(main())
    finally:
        logging.info("Bot shutdown complete.")
        loop.close()
