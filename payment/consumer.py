#!/usr/bin/env python
import atexit
import json
import time

import pika

from app import User, Payment, construct_payment_id, db


class Consumer(object):
    def __init__(self, callback=None):
        host = pika.ConnectionParameters(host='rabbitmq')  # Should be changed to rabbitmq
        self.connection = pika.BlockingConnection(host)
        self.channel = self.connection.channel()

        # Declare payment queue
        res = self.channel.queue_declare(queue='payment', durable=True)
        self.queue = res.method.queue

        # Prevents dispatching new message to a worker that has not processed and acknowledged the previous one yet
        self.channel.basic_qos(prefetch_count=1)

        # Attach callback to 'payment' queue
        self.channel.basic_consume(queue=self.queue, on_message_callback=self.callback)

    def callback(self, ch, method, properties, body):
        # request = json.loads(body.decode())
        # Read the request and task to do
        request = body.decode()
        task = properties.type
        print("[payment queue] Received payment request: ", request)
        res = 400
        msg = "Payment {} has not been processed".format(request)

        # Execute the task
        if task == "pay":
            res = 200
            msg = "Credit removed"
            print("[payment queue] Credit removed")
        elif task == "notPay":
            res = 403
            msg = "Not enough credit"
            print("[payment queue] Not enough credit")
        # msg, res = remove_credit(str(request["user"]), str(request["order"]), float(request["amount"]))
        time.sleep(5)

        # Send back a reply
        ch.basic_publish(exchange='',
                         routing_key=str(properties.reply_to),
                         properties=pika.BasicProperties(
                             correlation_id=properties.correlation_id,
                             type=str(res)),
                         body=str(msg))
        ch.basic_ack(delivery_tag=method.delivery_tag)
        print("[payment queue] Done")

    def run(self):
        print("Start consuming payment queue")
        self.channel.start_consuming()

    def close(self):
        print("Closing AMQP connection")
        self.channel.close()
        self.connection.close()

def remove_credit(user_id: str, order_id: str, amount: float):
    user = User.query.get_or_404(user_id)
    print(f"removing credit from user: {user.__dict__ =}")
    amount = float(amount)
    if user.credit < amount:
        print(f"{user.credit = } is smaller than {amount =} of credit to remove")
        msg, status_code = "Not enough credit", 403
    else:
        user.credit = user.credit - amount
        db.session.add(user)
        idx = construct_payment_id(user_id, order_id)
        payment = Payment(idx, user_id, order_id, amount, True)
        db.session.add(payment)
        print(f"succesfully removed {amount} credit from user with id {user_id}")
        db.session.commit()
        msg, status_code = "Credit removed", 200

    print(f"Remove credit result, {msg = }, {status_code = }")
    return msg, status_code


# if __name__ == '__main__':
#     consumer = Consumer()
#     consumer.run()

consumer = Consumer()
consumer.run()
atexit.register(consumer.close())
