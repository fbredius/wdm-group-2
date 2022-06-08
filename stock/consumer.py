#!/usr/bin/env python
import atexit
import json
import logging
import pika

from app import Item, db

logging.basicConfig()
logging.getLogger().setLevel(logging.DEBUG)


class Consumer(object):
    def __init__(self):
        # Start an AMQP connection
        host = pika.ConnectionParameters(host='rabbitmq')  # Change to environment variable
        self.connection = pika.BlockingConnection(host)
        self.channel = self.connection.channel()

        # Declare payment queue
        res = self.channel.queue_declare(queue='stock', durable=True)
        self.queue = res.method.queue

        # Prevents dispatching new message to a worker that has not processed and acknowledged the previous one yet
        self.channel.basic_qos(prefetch_count=1)

        # Attach callback to 'payment' queue
        self.channel.basic_consume(queue=self.queue, on_message_callback=self.callback)

    def callback(self, ch, method, properties, body):
        """
            This function is called when a message is consumed from the stock queue
        :param ch: channel
        :param method: method
        :param properties: properties (needed for the reply_to queue and task to execute)
        :param body: request body
        """
        # Send acknowledgement to RabbitMQ (otherwise this task is enqueued again)
        self.channel.basic_ack(delivery_tag=method.delivery_tag)

        # Read the request and task to do
        request = body.decode()
        routing = properties.reply_to
        task = properties.type

        # Set message en status code
        status = 400
        msg = "Stock task {} has not been processed".format(task)

        # Execute the task
        logging.debug(f"[stock queue] Executing task: {task =}")
        items = json.loads(request)
        if task == "subtractItems":
            msg, status = self._subtract_items(items)  # Subtract function here
        elif task == "increaseItems":
            msg, status = self._increase_items(items)  # Increase function here

        # Send back a reply if necessary
        if routing is not None:
            self.channel.basic_publish(exchange='',
                                       routing_key=str(routing),
                                       properties=pika.BasicProperties(
                                           correlation_id=properties.correlation_id,
                                           type=str(status)),
                                       body=str(msg))

        logging.debug(f"[stock queue] Done")

    def run(self):
        """
            This function is called to start consuming messages from the stock queue
        """
        logging.debug("Start consuming stock queue")
        self.channel.start_consuming()

    def close(self):
        """
            Close the channel and connection after use
        """
        logging.debug("Closing AMQP connection")
        self.channel.close()
        self.connection.close()

    @staticmethod
    def _subtract_items(item_ids):
        logging.debug(f"Subtract the items for request:")
        logging.debug(f"{item_ids =}")

        # Subtracts stock of all items by 1
        items = db.session.query(Item).filter(
            Item.id.in_(item_ids['item_ids'])
        )

        item: Item
        for item in items:
            # Return 400 and do not commit when item is out of stock
            if item.stock < 1:
                logging.debug(f"Not enough stock")
                return "not enough stock", 400

            item.stock -= 1
            db.session.add(item)

        db.session.commit()

        return "stock subtracted", 200

    @staticmethod
    def _increase_items(item_ids):
        """
            This is a rollback function. Following the SAGA pattern.
            :return:
            """
        logging.debug(f"Increase the items for request:")
        logging.debug(f"{item_ids =}")

        # Increases stock of all items by 1
        items = db.session.query(Item).filter(
            Item.id.in_(item_ids['item_ids'])
        )

        item: Item
        for item in items:
            item.stock += 1
            db.session.add(item)

        db.session.commit()

        return "stock increased", 200


consumer = Consumer()
consumer.run()
atexit.register(consumer.close())
