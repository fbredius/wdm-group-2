import os
import atexit

import pika
from flask import Flask, jsonify
import redis
import uuid
import json

app = Flask("payment-service")

db: redis.Redis = redis.Redis(host=os.environ['REDIS_HOST'],
                              port=int(os.environ['REDIS_PORT']),
                              password=os.environ['REDIS_PASSWORD'],
                              db=int(os.environ['REDIS_DB']))


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


def close_db_connection():
    db.close()


atexit.register(close_db_connection)
atexit.register(connection.close())


class User:
    def __init__(self, user_id, credit):
        self.user_id = user_id
        self.credit = credit


class Payment:
    def __init__(self, payment_id, user_id, order_id, amount, paid):
        self.payment_id = payment_id
        self.user_id = user_id
        self.order_id = order_id
        self.amount = amount
        self.paid = paid


def user_from_json(json_str) -> User:
    return User(**json.loads(json_str))


def payment_from_json(json_str) -> Payment:
    return Payment(**json.loads(json_str))


def construct_payment_id(user_id, order_id):
    return user_id + '/' + order_id


@app.post('/create_user')
def create_user():
    idx = str(uuid.uuid4())
    db.set(idx, json.dumps(User(idx, 0).__dict__))
    return {"user_id": idx}


@app.get('/find_user/<user_id>')
def find_user(user_id: str):
    if db.exists(user_id):
        return db.get(user_id)
    else:
        return "User not found", 404


@app.post('/add_funds/<user_id>/<amount>')
def add_credit(user_id: str, amount: int):
    if db.exists(user_id):
        user = user_from_json(db.get(user_id))
        user.credit = user.credit + int(amount)
        return jsonify({"done": db.set(user_id, json.dumps(user.__dict__))})
    else:
        return "User not found", 404


@app.post('/pay/<user_id>/<order_id>/<amount>')
def remove_credit(user_id: str, order_id: str, amount: int):
    if db.exists(user_id):
        user = user_from_json(db.get(user_id))
        print(f"{user.__dict__ =}", flush=True)
        if user.credit < int(amount):
            return "Not enough credit", 403
        else:
            user.credit = user.credit - int(amount)
            db.set(user_id, json.dumps(user.__dict__))
            idx = construct_payment_id(user_id, order_id)
            db.set(idx, json.dumps(Payment(idx, user_id, order_id, amount, True).__dict__))
            return "Credit removed", 200
    else:
        return "User not found", 404


@app.post('/cancel/<user_id>/<order_id>')
def cancel_payment(user_id: str, order_id: str):
    if db.exists(user_id):
        idx = construct_payment_id(user_id, order_id)
        if db.exists(idx):
            payment = json.loads(db.get(idx))
            payment.paid = False
            user = user_from_json(db.get(user_id))
            user.credit = user.credit + payment.amount
            db.set(user_id, json.dumps(user.__dict__))
            return "payment reset", 200
        else:
            return "Payment not found", 404
    else:
        return "User not found", 404


@app.post('/status/<user_id>/<order_id>')
def payment_status(user_id: str, order_id: str):
    idx = construct_payment_id(user_id, order_id)
    if db.exists(idx):
        payment = payment_from_json(db.get(idx))
        return {"paid": payment.paid}
    else:
        return {"paid": False}
