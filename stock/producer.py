#!/usr/bin/env python
import uuid
import pika


class Producer(object):
    def __init__(self):
        # host = pika.URLParameters(
        #     'amqps://sskbplbr:33XzmeNedhO9KVfmaxsHZfiVquNzl6DO@whale.rmq.cloudamqp.com/sskbplbr')
        host = pika.ConnectionParameters(host='rabbitmq')
        self.connection = pika.BlockingConnection(host)
        self.channel = self.connection.channel()

        # channel.queue_declare(queue='task_queue', durable=True)
        res = self.channel.queue_declare(queue='', exclusive=True)
        self.callback_queue = res.method.queue

        self.channel.basic_consume(
            queue=self.callback_queue,
            on_message_callback=self.on_response,
            auto_ack=True)

    def on_response(self, ch, method, props, body):
        if self.corr_id == props.correlation_id:
            self.response = body

    def publish(self, body):
        self.response = None
        self.corr_id = str(uuid.uuid4())
        self.channel.basic_publish(exchange='',
                              routing_key="payment",
                              body=body,
                              properties=pika.BasicProperties(
                                  delivery_mode=pika.spec.PERSISTENT_DELIVERY_MODE,
                                  reply_to=self.callback_queue,
                                  correlation_id=self.corr_id,
                              ))
        while self.response is None:
            self.connection.process_data_events()
        return self.response


# connection.close()
# channel.close()
