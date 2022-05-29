#!/usr/bin/env python
import pika

# When a message is received, this function is called
def callback(ch, method, properties, body):
    print(" [x] Received payment %r" % body.decode())
    print(" [x] Done")
    ch.basic_ack(delivery_tag = method.delivery_tag)

params = pika.URLParameters('amqps://sskbplbr:33XzmeNedhO9KVfmaxsHZfiVquNzl6DO@whale.rmq.cloudamqp.com/sskbplbr')
connection = pika.BlockingConnection(params)
channel = connection.channel()

# Declare the queue
channel.queue_declare(queue='payment', durable=True)

# Prevents dispatching new message to a worker that has not processed and acknowledged the previous one yet
channel.basic_qos(prefetch_count=1)
channel.basic_consume(queue='payment', on_message_callback=callback)

# Start waiting for messages
print("Waiting for messages")
channel.start_consuming()