#!/usr/bin/env python
import json
import logging
import asyncio

from aio_pika import Message, connect
from aio_pika.abc import AbstractIncomingMessage
from app import app, remove_credit, cancel_payment

logging.basicConfig()
logging.getLogger().setLevel(logging.DEBUG)


async def pay(user_id: str, order_id: str, amount: float):
    async with app.app_context():
        return await remove_credit(amount, order_id, user_id)


async def refund(user_id: str, order_id: str):
    async with app.app_context():
        return await cancel_payment(order_id, user_id)


async def main():
    connection = await connect("amqp://guest:guest@rabbitmq/")

    channel = await connection.channel()
    queue = await channel.declare_queue("payment", durable=True)

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
                    logging.debug(f"[payment queue] Executing task: {task =}")
                    request_body = json.loads(request)
                    user_id = request_body["user_id"]
                    order_id = request_body["order_id"]

                    if task == "pay":
                        amount = request_body["total_cost"]
                        response = await pay(user_id, order_id, amount)
                    elif task == "cancel":
                        response = await refund(user_id, order_id)
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

                    logging.debug(f"[payment queue] Done")
            except Exception:
                logging.exception(f"Processing error for message {message}")


if __name__ == "__main__":
    # asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
