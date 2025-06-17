# titan/order_executor.py
import asyncio
import logging
from titan.datastructures import Order

class OrderExecutor:
    """
    Consumes concrete Order objects and sends them to the
    ExchangeConnector for execution.
    """
    def __init__(self, order_queue: asyncio.Queue, connector):
        self.order_queue = order_queue
        # The connector is passed in to provide the execution interface
        self.connector = connector

    async def run(self):
        """Main run loop to process and execute orders."""
        logging.info("OrderExecutor is running.")
        while True:
            try:
                # Wait for a concrete order from the PortfolioManager
                order_to_execute: Order = await self.order_queue.get()
                
                logging.info(f"Executor received order to process: {order_to_execute}")
                
                # Call the connector's method to place the order
                # The connector handles the actual API communication
                result = await self.connector.place_order(order_to_execute)
                
                # Basic handling of the result
                if result and result.get('retCode') == 0:
                    logging.info(f"Order submission successful for {order_to_execute.symbol}.")
                    # In a full system, we would now monitor this order's ID
                    # via the private WebSocket feed for fill events.
                else:
                    logging.error(f"Order submission failed for {order_to_execute.symbol}. Reason: {result.get('retMsg')}")

                self.order_queue.task_done()

            except Exception as e:
                logging.critical("An unexpected error occurred in OrderExecutor", exc_info=True)
