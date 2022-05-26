#!/usr/bin/env python
import pika
import sys

params = pika.URLParameters('amqps://sskbplbr:33XzmeNedhO9KVfmaxsHZfiVquNzl6DO@whale.rmq.cloudamqp.com/sskbplbr')
connection = pika.BlockingConnection(params)
channel = connection.channel()

# channel.queue_declare(queue='task_queue', durable=True)


def publish(message):
    channel.basic_publish(exchange='',
                          routing_key="payment",
                          body=message,
                          properties=pika.BasicProperties(
                              delivery_mode=pika.spec.PERSISTENT_DELIVERY_MODE
                          ))


# connection.close()
# channel.close()
