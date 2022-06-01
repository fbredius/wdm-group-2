#!/usr/bin/env python
import pika

class Consumer(object):
    def __init__(self, callback):
        host = pika.ConnectionParameters(host='rabbitmq')  # Should be changed to rabbitmq
        self.connection = pika.BlockingConnection(host)
        self.channel = self.connection.channel()

        # Declare payment queue
        res = self.channel.queue_declare(queue='payment', durable=True)
        self.queue = res.method.queue

        # Prevents dispatching new message to a worker that has not processed and acknowledged the previous one yet
        self.channel.basic_qos(prefetch_count=1)

        # Attach callback to 'payment' queue
        self.channel.basic_consume(queue=self.queue, on_message_callback=callback)

    def run(self):
        self.channel.start_consuming()

    def close(self):
        self.channel.close()
        self.connection.close()

