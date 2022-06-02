#!/usr/bin/env python
import uuid
import pika

class Producer(object):
    def __init__(self, connection, queue):
        # host = pika.ConnectionParameters(host='rabbitmq')
        # self.connection = pika.BlockingConnection(host)
        self.connection = connection
        self.channel = self.connection.channel()
        self.queue = queue

        res = self.channel.queue_declare(queue='', exclusive=True)
        self.callback_queue = res.method.queue

    def consume(self):
        self.channel.basic_consume(
            queue=self.callback_queue,
            on_message_callback=self.on_response,
            auto_ack=True)

    def on_response(self, ch, method, props, body):
        if self.corr_id == props.correlation_id:
            self.response = body
            self.status = props.type

    def publish(self, body, type=None):
        self.response = None
        self.status = None
        self.corr_id = str(uuid.uuid4())
        self.channel.basic_publish(
            exchange='',
            routing_key=self.queue,
            body=body,
            properties=pika.BasicProperties(
                  delivery_mode=pika.spec.PERSISTENT_DELIVERY_MODE,
                  reply_to=self.callback_queue,
                  correlation_id=self.corr_id,
                  type=type
            )
        )
        # while self.response is None:
        #     self.connection.process_data_events()
        # return self.response

    def close(self):
        self.channel.close()
        # self.connection.close()


if __name__ == '__main__':
    host = pika.ConnectionParameters(host='localhost')
    connection = pika.BlockingConnection(host)
    producer1 = Producer(connection, "stock")
    producer2 = Producer(connection, "payment")
    # print(json.loads(producer.publish("subtractItems", "ORDER 1").decode())["total_price"])
    # print(json.loads(producer.publish("increaseItems", "ORDER 2").decode())["total_price"])
    # print(producer1.publish("ORDER 1", "subtractItems").decode())
    # print(producer2.publish("PAYMENT 1").decode())
    producer1.publish("ORDER 12", "subtractItems")
    producer2.publish("ORDER 12", "pay")
    producer1.consume()
    producer2.consume()
    print("Waiting for response...")
    while (producer1.status is None) or (producer2.status is None):
        producer1.connection.process_data_events()
        producer2.connection.process_data_events()
    print(producer1.status, producer1.response.decode())
    print(producer2.status, producer2.response.decode())
    producer1.close()
    producer2.close()
    connection.close()

