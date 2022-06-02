#!/usr/bin/env python
import uuid
import time

import pika

class Producer(object):
    def __init__(self, connection, queue):
        # Start a connection outside of this object and pass it to the object
        # This ensures only 1 active AMQP connection per service
        self.connection = connection
        self.channel = self.connection.channel()
        self.queue = queue
        self.response = None
        self.status = None
        self.corr_id = None

        # Declare the queue the response must be send to
        res = self.channel.queue_declare(queue='', exclusive=True)
        self.callback_queue = res.method.queue

    def consume(self):
        """
            Start consuming the message from the response queue
        """
        self.channel.basic_consume(
            queue=self.callback_queue,
            on_message_callback=self.on_response,
            auto_ack=True)

    def on_response(self, ch, method, props, body):
        """
            This function is called when a message is consumed from the response queue
        :param ch: channel
        :param method: method
        :param props: properties (needed for the status code)
        :param body: response body
        """
        if self.corr_id == props.correlation_id:
            self.response = body
            self.status = props.type

    def publish(self, body, task=None, reply=False):
        """
            This function is used to send a message to the indicated queue
        :param body: request body
        :param task: task that must be executed by the other service
        :param reply: whether or not a response is expected
        :return:
        """
        # TODO Set priority for rollback higher then for normal transactions
        self.response = None
        self.status = None
        queue = None
        self.corr_id = str(uuid.uuid4())

        # If a response is expected, set up the reply_to queue
        if reply:
            queue = self.callback_queue
        self.channel.basic_publish(
            exchange='',
            routing_key=self.queue,
            body=body,
            properties=pika.BasicProperties(
                  delivery_mode=pika.spec.PERSISTENT_DELIVERY_MODE,
                  reply_to=queue,
                  correlation_id=self.corr_id,
                  type=task
            )
        )

    def close(self):
        """
            Close the channel after use
        """
        self.channel.close()
        # self.connection.close()


if __name__ == '__main__':
    # Set host to rabbitmq
    host = pika.ConnectionParameters(host='localhost')
    connection = pika.BlockingConnection(host)

    # Set up a producer (channel) for each queue to send a message to
    producer1 = Producer(connection, "stock")
    producer2 = Producer(connection, "payment")
    # print(json.loads(producer.publish("subtractItems", "ORDER 1").decode())["total_price"])
    # print(json.loads(producer.publish("increaseItems", "ORDER 2").decode())["total_price"])
    # print(producer1.publish("ORDER 1", "subtractItems").decode())
    # print(producer2.publish("PAYMENT 1").decode())

    # Send a message by calling the publish method with (body, task=None, reply=False)
    producer1.publish("ORDER 12", "subtractItems", reply=True)
    producer2.publish("ORDER 12", "pay", reply=True)

    # At the end of an order, consume the queues for the responses
    producer1.consume()
    producer2.consume()
    print("Waiting for response...")
    timeout = time.time() + 20
    while (producer1.status is None or producer2.status is None) and (time.time() < timeout):
        producer1.connection.process_data_events()
        producer2.connection.process_data_events()
        time.sleep(1)
    print(producer1.status, producer1.response.decode())
    print(producer2.status, producer2.response.decode())
    producer1.close()
    producer2.close()
    connection.close()

