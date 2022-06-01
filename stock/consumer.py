#!/usr/bin/env python
import pika
from producer import Producer

# Establish connection with RabbitMQ Server
host = pika.ConnectionParameters(host='rabbitmq')
connection = pika.BlockingConnection(host)
channel = connection.channel()

producer = Producer()


# When a message is received, this function is called
def callback(ch, method, properties, body):
    request = body.decode()
    print(" [x] Received order %r" % request)
    check = int(producer.publish(request).decode())
    if check == 200:
        response = 200
        print(" [x] Payment successful")
    else:
        response = 400
        print(" [x] Not enough credit")
    ch.basic_publish(exchange='',
                     routing_key=str(properties.reply_to),
                     properties=pika.BasicProperties(correlation_id=properties.correlation_id),
                     body=str(response))
    ch.basic_ack(delivery_tag=method.delivery_tag)
    print(" [x] Done")


# Declare the queue
channel.queue_declare(queue='stock', durable=True)

# Prevents dispatching new message to a worker that has not processed and acknowledged the previous one yet
channel.basic_qos(prefetch_count=1)

# Attach the callback to 'stock' queue
channel.basic_consume(queue='stock', on_message_callback=callback)

# Start waiting for messages
print("Waiting for messages")
channel.start_consuming()
