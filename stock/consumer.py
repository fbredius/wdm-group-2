#!/usr/bin/env python
import asyncio
import json
import logging
import os

from aio_pika import Message, connect
from aio_pika.abc import AbstractIncomingMessage

from app import app, Item, update_stock, get_item_price

logging.basicConfig()
logging.getLogger().setLevel(os.environ.get('LOG_LEVEL', logging.INFO))


async def subtract_items(request_body):
    """
    Subtracts all items in the list from stock by the amount of 1
    Pass in an 'request_body' containing an 'item_ids' array
    :param request_body: body of request received
    """
    logging.debug(f"Subtract the items: {request_body['item_ids']}")

    async with app.app_context():
        return await update_stock({id_: Item.stock - 1 for id_ in request_body['item_ids']})


async def increase_items(request_body):
    """
    This is a rollback function. Following the SAGA pattern.
    Increases all items in the list from stock by the amount of 1
    Pass in an 'request_body' containing an 'item_ids' array
    :param request_body: body of request received
    """
    logging.debug(f"Increase the items for request: {request_body['item_ids']}")

    async with app.app_context():
        return await update_stock({id_: Item.stock + 1 for id_ in request_body['item_ids']})


async def get_price_of_item(item_id):
    """
    Get price of a certain item.
    :param item_id: ID of item
    :return: price of item
    """
    async with app.app_context():
        return await get_item_price(item_id)


async def main():
    """
    Main consumer function that consumes messages and redirects to correct function.
    """
    connection = await connect("amqp://guest:guest@rabbitmq/")

    channel = await connection.channel()
    queue = await channel.declare_queue("stock", durable=True)

    async with queue.iterator() as qiterator:
        message: AbstractIncomingMessage
        async for message in qiterator:
            try:
                async with message.process(requeue=False):
                    # Read the request and task to do
                    request = message.body.decode()
                    routing = message.reply_to
                    task = message.type

                    # Execute the task
                    logging.debug(f"[stock queue] Executing task: {task =}")
                    request_body = json.loads(request)
                    if task == "subtractItems":
                        response = await subtract_items(request_body)
                    elif task == "increaseItems":
                        response = await increase_items(request_body)
                    elif task == "getPrice":
                        response = await get_price_of_item(request_body["item_id"])
                    else:
                        return

                    # Send back a reply if necessary
                    if routing is not None:
                        body = await response.get_data()
                        await channel.default_exchange.publish(
                            Message(
                                body=body,
                                correlation_id=message.correlation_id,
                                type=str(response.status_code)
                            ),
                            routing_key=message.reply_to
                        )

                    logging.debug(f"[stock queue] Done")
            except Exception:
                logging.exception(f"Processing error for message {message}")

if __name__ == "__main__":
    asyncio.run(main())
