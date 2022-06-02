#!/usr/bin/env python
import atexit
import json
import time

import pika

from app import Item, db


class Consumer(object):
    def __init__(self, callback=None):
        host = pika.ConnectionParameters(host='rabbitmq')  # Should be changed to rabbitmq
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
        # Read the request and task to do
        request = body.decode()
        task = properties.type
        print("[stock queue] Received order: ", request)
        res = 400
        msg = "Stock task {} has not been processed".format(request)

        # Execute the task
        if task == "subtractItems":
            # msg, res = subtract_items(request)  # Subtract function here
            res = 200
            msg = "stock subtracted"
            print("[stock queue] Items subtracted")
        elif task == "increaseItems":
            # msg, res = increase_items(request)  # Increase function here
            res = 200
            msg = "stock increased"
            print("[stock queue] Items increased")
        elif task == "calculatePrice":
            # msg, res = calculate_price(request)  # Calculate function here
            res = 200
            msg = json.dumps({"total_price": 10})
            print("[stock queue] Items price calculated")
        time.sleep(10)

        # Send back a reply
        ch.basic_publish(exchange='',
                         routing_key=str(properties.reply_to),
                         properties=pika.BasicProperties(
                             correlation_id=properties.correlation_id,
                             type=str(res)),
                         body=str(msg))
        ch.basic_ack(delivery_tag=method.delivery_tag)
        print("[stock queue] Done")

    def run(self):
        print("Start consuming stock queue")
        self.channel.start_consuming()

    def close(self):
        print("Closing AMQP connection")
        self.channel.close()
        self.connection.close()


def subtract_items(item_ids):
    # Subtracts stock of all items by 1
    # TODO Check if item is in stock
    items = db.session.query(Item).filter(
        Item.id.in_(item_ids)
    )
    print(f"items= {items}")

    item: Item
    for item in items:
        item.stock -= 1
        db.session.add(item)

    db.session.commit()

    return "stock subtracted", 200


def increase_items(item_ids):
    """
    This is a rollback function. Following the SAGA pattern.
    :return:
    """
    # Increases stock of all items by 1
    items = db.session.query(Item).filter(
        Item.id.in_(item_ids)
    )
    print(f"items= {items}")

    item: Item
    for item in items:
        item.stock += 1
        db.session.add(item)

    db.session.commit()

    return "stock increased", 200


def calculate_price(item_ids):
    items = db.session.query(Item).filter(
        Item.id.in_(item_ids)
    )

    total_price = sum(item.price for item in items)

    return {"total_price": total_price}, 200


# if __name__ == '__main__':
#     consumer = Consumer()
#     consumer.run()

consumer = Consumer()
consumer.run()
atexit.register(consumer.close())
