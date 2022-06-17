#!/usr/bin/env python
import uuid
import asyncio

from typing import MutableMapping
from aio_pika import Message, connect
from aio_pika.abc import (
    AbstractChannel, AbstractConnection, AbstractIncomingMessage, AbstractQueue, DeliveryMode,
)


class OrderConnection:
    connection: AbstractConnection

    def __init__(self):
        """
        Initialize OrderConnection with empty connection and create loop.
        """
        self.connection = None
        self.loop = asyncio.get_running_loop()

    async def get_connection(self):
        """
        Get an active connection to RabbitMQ.
        Create if not connected yet.
        :return: the active connection
        """
        if self.connection is None or self.connection.is_closed:
            self.connection = await connect("amqp://guest:guest@rabbitmq/", loop=self.loop)
        return self.connection


class Producer:
    connection: AbstractConnection
    channel: AbstractChannel
    callback_queue: AbstractQueue

    def __init__(self, queue) -> None:
        """
        Initializing Producer entity for order service.
        This Producer can produce to an queue and consume from a callback queue.
        :param queue: key of queue to create
        """
        self.futures: MutableMapping[str, asyncio.Future] = {}
        self.loop = asyncio.get_running_loop()
        self.queue = queue
        self.connection = None
        self.callback_queue = None

    def is_ready(self) -> bool:
        """
        Check to see if the producer is ready to create channel/queue, by checking connection.
        :return: boolean indicating if producer is ready
        """
        return self.connection is not None and self.connection.is_closed is False

    async def connect(self, connection):
        """
        Using the connection to create channel and queue, then start consuming for a reply.
        """
        self.connection = connection
        self.channel = await self.connection.channel()
        self.callback_queue = await self.channel.declare_queue(exclusive=True)
        await self.callback_queue.consume(self.on_response)

    async def consume(self):
        await self.callback_queue.consume(self.on_response)

    async def on_response(self, message: AbstractIncomingMessage) -> None:
        """
        Handles incoming messages and sets the result of the Future if it receives a reply.
        :param message: incoming message from callback queue
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
        Sends a task to the corresponding queue.
        :param body: body of message to be sent into queue
        :param task: indicating the task to handle this message
        :param reply: indicates if reply is expected
        :return: response if reply is expected
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
        if reply:
            response = await future
            return response
