#!/usr/bin/env python
import atexit
import json
import logging
import pika

import asyncio
from asyncio import sleep

from aio_pika import Message, connect
from aio_pika.abc import AbstractIncomingMessage

from aio_pika.abc import (
    AbstractChannel, AbstractConnection, AbstractIncomingMessage, AbstractQueue,
)

from app import app, Item, update_stock

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
#         res = self.channel.queue_declare(queue='stock', durable=True)
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
#             This function is called when a message is consumed from the stock queue
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
#         logging.debug(f"[stock queue] Executing task: {task =}")
#         request_body = json.loads(request)
#         if task == "subtractItems":
#             response = self._subtract_items(request_body)
#         elif task == "increaseItems":
#             response = self._increase_items(request_body)
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
        # logging.debug(f"[stock queue] Done")
#
#     def run(self):
#         """
#             This function is called to start consuming messages from the stock queue
#         """
#         logging.debug("Start consuming stock queue")
#         self.channel.start_consuming()
#
#     def close(self):
#         """
#             Close the channel and connection after use
#         """
#         logging.debug("Closing AMQP connection")
#         self.channel.close()
#         self.connection.close()
#
#     @staticmethod
#     def _subtract_items(request_body):
#         """
#         Subtracts all items in the list from stock by the amount of 1
#         Pass in an 'request_body' containing an 'item_ids' array
#         :return:
#         """
#         logging.debug(f"Subtract the items: {request_body['item_ids']}")
#
#         with app.app_context():
#             return update_stock({id_: Item.stock - 1 for id_ in request_body['item_ids']})
#
#     @staticmethod
#     def _increase_items(request_body):
#         """
#         This is a rollback function. Following the SAGA pattern.
#         Increases all items in the list from stock by the amount of 1
#         Pass in an 'request_body' containing an 'item_ids' array
#         :return:
#         """
#         logging.debug(f"Increase the items for request: {request_body['item_ids']}")
#
#         with app.app_context():
#             return update_stock({id_: Item.stock + 1 for id_ in request_body['item_ids']})


# consumer = Consumer()
# consumer.run()
# atexit.register(consumer.close())


async def subtract_items(request_body):
    """
    Subtracts all items in the list from stock by the amount of 1
    Pass in an 'request_body' containing an 'item_ids' array
    :return:
    """
    logging.debug(f"Subtract the items: {request_body['item_ids']}")

    async with app.app_context():
        return await update_stock({id_: Item.stock - 1 for id_ in request_body['item_ids']})


async def increase_items(request_body):
    """
    This is a rollback function. Following the SAGA pattern.
    Increases all items in the list from stock by the amount of 1
    Pass in an 'request_body' containing an 'item_ids' array
    :return:
    """
    logging.debug(f"Increase the items for request: {request_body['item_ids']}")

    async with app.app_context():
        return await update_stock({id_: Item.stock + 1 for id_ in request_body['item_ids']})


async def main():
    connection = await connect("amqp://guest:guest@rabbitmq/")

    channel = await connection.channel()
    queue = await channel.declare_queue("stock", durable=True)
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
                    logging.debug(f"[stock queue] Executing task: {task =}")
                    request_body = json.loads(request)
                    if task == "subtractItems":
                        response = await subtract_items(request_body)
                    elif task == "increaseItems":
                        response = await increase_items(request_body)
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
    # asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
