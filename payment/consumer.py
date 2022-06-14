#!/usr/bin/env python
import atexit
import json
import logging
import pika

from app import app, remove_credit, cancel_payment

import asyncio
from asyncio import sleep
from typing import MutableMapping

from aio_pika import Message, connect
from aio_pika.abc import AbstractIncomingMessage

from aio_pika.abc import (
    AbstractChannel, AbstractConnection, AbstractIncomingMessage, AbstractQueue,
)

logging.basicConfig()
logging.getLogger().setLevel(logging.DEBUG)


# class Consumer(object):
#     def __init__(self):
#         # Start an AMQP connection
#         host = pika.ConnectionParameters(host='rabbitmq')  # Change to environment variable
#         self.connection = pika.BlockingConnection(host)
#         self.channel = self.connection.channel()
#
#         # Declare payment queue
#         res = self.channel.queue_declare(queue='payment', durable=True)
#         self.queue = res.method.queue
#
#         # Prevents dispatching new message to a worker that has not processed and acknowledged the previous one yet
#         self.channel.basic_qos(prefetch_count=1)
#
#         # Attach callback to 'payment' queue
#         self.channel.basic_consume(queue=self.queue, on_message_callback=self.callback)
#
#     def callback(self, ch, method, properties, body):
#         """
#             This function is called when a message is consumed from the payment queue
#         :param ch: channel
#         :param method: method
#         :param properties: properties (needed for the reply_to queue and task to execute)
#         :param body: request body
#         """
#         # Send acknowledgement to RabbitMQ (otherwise this task is enqueued again)
#         self.channel.basic_ack(delivery_tag=method.delivery_tag)
#
#         # Read the request and task to do
#         request = body.decode()
#         routing = properties.reply_to
#         task = properties.type
#
#         # Execute the task
#         logging.debug(f"[payment queue] Executing task: {task =}")
#         request_body = json.loads(request)
#         user_id = request_body["user_id"]
#         order_id = request_body["order_id"]
#
#         if task == "pay":
#             amount = request_body["total_cost"]
#             response = self._remove_credit(user_id, order_id, amount)
#         elif task == "cancel":
#             response = self._cancel_payment(user_id, order_id)
#         else:
#             return
#
#         # Send back a reply if necessary
#         if routing is not None:
#             self.channel.basic_publish(exchange='',
#                                        routing_key=str(routing),
#                                        properties=pika.BasicProperties(
#                                            correlation_id=properties.correlation_id,
#                                            type=str(response.status_code)),
#                                        body=response.get_data())
#
#         logging.debug(f"[payment queue] Done")
#
#     def run(self):
#         """
#             This function is called to start consuming messages from the payment queue
#         """
#         logging.debug(f"Start consuming payment queue")
#         self.channel.start_consuming()
#
#     def close(self):
#         """
#             Close the channel and connection after use
#         """
#         logging.debug(f"Closing AMQP connection")
#         self.channel.close()
#         self.connection.close()
#
#     @staticmethod
#     def _remove_credit(user_id: str, order_id: str, amount: float):
#         with app.app_context():
#             return remove_credit(amount, order_id, user_id)
#
#     @staticmethod
#     def _cancel_payment(user_id: str, order_id: str):
#         with app.app_context():
#             return cancel_payment(order_id, user_id)


# consumer = Consumer()
# consumer.run()
# atexit.register(consumer.close())

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
    # exchange = await channel.default_exchange
    # await queue.consume(on_message)

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
