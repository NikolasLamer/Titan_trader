# titan/order_executor.py
import asyncio
import logging
import random
from titan.datastructures import Order, FillConfirmation
from titan.exchange_connector import ExchangeConnector

class OrderExecutor:
    """
    Consumes concrete Order objects and sends them to the
    ExchangeConnector for execution. After a successful execution,
    it sends a FillConfirmation back to the PortfolioManager.
    """
    def __init__(self, order_queue: asyncio.Queue, connector: ExchangeConnector, fill_confirmation_queue: asyncio.Queue):
        self.order_queue = order_queue
        self.connector = connector
        self.fill_confirmation_queue = fill_confirmation_queue

    async def run(self):
        """Main run loop to process and execute orders."""
        logging.info("OrderExecutor is running.")
        while True:
            try:
                order_to_execute: Order = await self.order_queue.get()
                logging.info(f"Executor received order to process: {order_to_execute}")

                result = await self.connector.place_order(order_to_execute)

                if result and result.get('retCode') == 0:
                    logging.info(f"Order submission successful for {order_to_execute.symbol}.")

                    # In a real system, fill price would come from a private WebSocket feed.
                    # Here, we simulate it or use the order price for LIMIT orders.
                    # For MARKET orders, pybit does not return avgPrice, so we'd need another call or use last trade price.
                    # For this implementation, we'll assume the order price for simplicity.
                    fill_price = order_to_execute.price if order_to_execute.order_type == 'LIMIT' else float(result['result'].get('avgPrice', '0'))
                    if order_to_execute.order_type == 'MARKET':
                        # This is a simplification. A robust solution would fetch the last trade price.
                        # For now, we'll log a warning and proceed.
                        logging.warning("Market order fill price not available in response, using placeholder. A robust system would fetch this.")
                        # A better placeholder would be to fetch last trade price from connector
                        fill_price = await self.connector.get_last_trade_price(order_to_execute.symbol)


                    confirmation = FillConfirmation(
                        symbol=order_to_execute.symbol,
                        order_id=result['result']['orderId'],
                        side=order_to_execute.side,
                        qty=order_to_execute.qty,
                        price=float(fill_price)
                    )
                    await self.fill_confirmation_queue.put(confirmation)
                else:
                    logging.error(f"Order submission failed for {order_to_execute.symbol}. Reason: {result.get('retMsg')}")

                self.order_queue.task_done()

            except Exception as e:
                logging.critical("An unexpected error occurred in OrderExecutor", exc_info=True)
