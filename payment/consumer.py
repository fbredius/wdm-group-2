#!/usr/bin/env python
import atexit
import json
import time
import logging
import pika

from app import User, Payment, construct_payment_id, db

logging.basicConfig()
logging.getLogger().setLevel(logging.DEBUG)


class Consumer(object):
    def __init__(self):
        # Start an AMQP connection
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
        """
            This function is called when a message is consumed from the payment queue
        :param ch: channel
        :param method: method
        :param properties: properties (needed for the reply_to queue and task to execute)
        :param body: request body
        """
        # Read the request and task to do
        request = body.decode()
        routing = properties.reply_to
        task = properties.type

        # Set message en status code
        status = 400
        msg = "Payment task {} has not been processed".format(task)

        # Execute the task
        logging.debug(f"[payment queue] Executing task: {task =}")
        payment = json.loads(request)
        user_id = payment["user_id"]
        order_id = payment["order_id"]
        if task == "pay":
            total_cost = payment["total_cost"]
            msg, status = self._remove_credit(user_id, order_id, total_cost)
        elif task == "cancel":
            msg, status = self._cancel_payment(user_id, order_id)

        # Send back a reply if necessary
        if routing is not None:
            self.channel.basic_publish(exchange='',
                                       routing_key=str(routing),
                                       properties=pika.BasicProperties(
                                           correlation_id=properties.correlation_id,
                                           type=str(status)),
                                       body=str(msg))

        # Send acknowledgement to RabbitMQ (otherwise this task is enqueued again)
        self.channel.basic_ack(delivery_tag=method.delivery_tag)
        logging.debug(f"[payment queue] Done")

    def run(self):
        """
            This function is called to start consuming messages from the payment queue
        """
        logging.debug(f"Start consuming payment queue")
        self.channel.start_consuming()

    def close(self):
        """
            Close the channel and connection after use
        """
        logging.debug(f"Closing AMQP connection")
        self.channel.close()
        self.connection.close()

    @staticmethod
    def _remove_credit(user_id: str, order_id: str, amount: float):
        user = User.query.get_or_404(user_id)
        logging.debug(f"removing credit from user: {user.__dict__ =}")
        amount = float(amount)
        if user.credit < amount:
            logging.debug(f"{user.credit = } is smaller than {amount =} of credit to remove")
            msg, status_code = "Not enough credit", 403
        else:
            user.credit = user.credit - amount
            db.session.add(user)
            idx = construct_payment_id(user_id, order_id)
            payment = Payment(idx, user_id, order_id, amount, True)
            db.session.add(payment)
            logging.debug(f"succesfully removed {amount} credit from user with id {user_id}")
            db.session.commit()
            msg, status_code = "Credit removed", 200

        logging.debug(f"Remove credit result, {msg = }, {status_code = }")
        return msg, status_code

    @staticmethod
    def _cancel_payment(user_id: str, order_id: str):
        user = User.query.get_or_404(user_id)
        idx = construct_payment_id(user_id, order_id)
        payment = Payment.query.get_or_404(idx)
        payment.paid = False
        user.credit = user.credit + payment.amount
        db.session.add(user)
        db.session.commit()

        msg, status_code = "payment reset", 200

        logging.debug(f"Cancel payment result, {msg = }, {status_code = }")
        return msg, status_code


consumer = Consumer()
consumer.run()
atexit.register(consumer.close())
