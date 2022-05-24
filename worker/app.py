#!/usr/bin/env python
import pika


def callback(ch, method, properties, body):
    print(" [x] Received %r" % body.decode())
    print(" [x] Done")
    ch.basic_ack(delivery_tag = method.delivery_tag)


connection = pika.BlockingConnection(pika.ConnectionParameters(host='localhost'))
channel = connection.channel()

channel.queue_declare(queue='task_queue', durable=True)

channel.basic_qos(prefetch_count=1)
channel.basic_consume(queue='task_queue', on_message_callback=callback)

print(' [*] Waiting for messages.')
channel.start_consuming()
