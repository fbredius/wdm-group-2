import os
import atexit

from flask import Flask
import redis
import uuid
import json

app = Flask("payment-service")

db: redis.Redis = redis.Redis(host=os.environ['REDIS_HOST'],
                              port=int(os.environ['REDIS_PORT']),
                              password=os.environ['REDIS_PASSWORD'],
                              db=int(os.environ['REDIS_DB']))


def close_db_connection():
    db.close()


atexit.register(close_db_connection)


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
        return json.loads(db.get(user_id))
    else:
        return "User not found", 404


@app.post('/add_funds/<user_id>/<amount>')
def add_credit(user_id: str, amount: int):
    if db.exists(user_id):
        user = json.loads(db.get(user_id))
        user.credit = user.credit + amount
        return db.set(user_id, json.dumps(user.__dict__))
    else:
        return "User not found", 404


@app.post('/pay/<user_id>/<order_id>/<amount>')
def remove_credit(user_id: str, order_id: str, amount: int):
    if db.exists(user_id):
        user = json.loads(db.get(user_id))
        if user.credit < amount:
            return "Not enough credit", 403
        else:
            user.credit = user.credit - amount
            db.set(user_id, json.dumps(user.__dict__))
            idx = construct_payment_id(user_id, order_id)
            return db.set(idx, json.dumps(Payment(idx, user_id, order_id, amount, True).__dict__))
    else:
        return "User not found", 404


@app.post('/cancel/<user_id>/<order_id>')
def cancel_payment(user_id: str, order_id: str):
    if db.exists(user_id):
        idx = construct_payment_id(user_id, order_id)
        if db.exists(idx):
            payment = json.loads(db.get(idx))
            payment.paid = False
            user = json.loads(db.get(user_id))
            user.credit = user.credit + payment.amount
            db.set(user_id, json.dumps(user.__dict__))
            return db.set(idx, json.dumps(payment.__dict__))
        else:
            return "Payment not found", 404
    else:
        return "User not found", 404


@app.post('/status/<user_id>/<order_id>')
def payment_status(user_id: str, order_id: str):
    idx = construct_payment_id(user_id, order_id)
    if db.exists(idx):
        payment = json.loads(db.get(idx))
        return {"paid": payment.paid}
    else:
        return {"paid": False}
