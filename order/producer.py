#!/usr/bin/env python
import uuid
import asyncio

from typing import MutableMapping
from aio_pika import Message, connect
from aio_pika.abc import (
    AbstractChannel, AbstractConnection, AbstractIncomingMessage, AbstractQueue, DeliveryMode,
)


class Connection:
    connection: AbstractConnection

    def __init__(self):
        self.connection = None
        self.loop = asyncio.get_running_loop()

    async def get_connection(self):
        if self.connection is None or self.connection.is_closed:
            self.connection = await connect("amqp://guest:guest@rabbitmq/", loop=self.loop)
        return self.connection


class Producer:
    # connection: AbstractConnection
    channel: AbstractChannel
    callback_queue: AbstractQueue

    def __init__(self, connection, queue) -> None:
        self.futures: MutableMapping[str, asyncio.Future] = {}
        self.loop = asyncio.get_running_loop()
        self.queue = queue
        self.connection = connection

    async def connect(self) -> "Producer":
        """
        Setup the connection with RabbitMQ, and start consuming for a reply
        :return:
        """
        self.channel = await self.connection.channel()
        self.callback_queue = await self.channel.declare_queue(exclusive=True)
        await self.callback_queue.consume(self.on_response)
        return self

    async def consume(self):
        await self.callback_queue.consume(self.on_response)

    async def on_response(self, message: AbstractIncomingMessage) -> None:
        """
        Sets the result of the Future if it receives a reply
        :param message:
        :return:
        """
        async with message.process():
            if message.correlation_id is None:
                print(f"Incorrect message {message!r}")
                return

            # Set the result of the Future
            future: asyncio.Future = self.futures.pop(message.correlation_id)
            future.set_result({"message": message.body.decode(), "status": message.type})

    async def publish(self, body, task=None, reply=False):
        """
        Sends a task to the corresponding queue
        :param body:
        :param task:
        :param reply:
        :return:
        """
        correlation_id = str(uuid.uuid4())
        reply_queue = None
        # If a response is expected, set up the reply_to queue
        if reply:
            reply_queue = self.callback_queue.name

        # A Future represents an eventual result of an asynchronous operation.
        future = self.loop.create_future()
        self.futures[correlation_id] = future

        await self.channel.default_exchange.publish(
            Message(
                body=body.encode(),
                correlation_id=correlation_id,
                reply_to=reply_queue,
                delivery_mode=DeliveryMode.PERSISTENT,
                type=task
            ),
            routing_key=self.queue
        )

        # If an reply is expected, wait till the Future is ready
        if reply_queue is not None:
            response = await future
            return response
