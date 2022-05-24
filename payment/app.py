import atexit
import json
import logging
import os
import uuid

import redis
from flask import Flask, jsonify

app_name = 'payment-service'
app = Flask(app_name)
logging.getLogger(app_name).setLevel(os.environ.get('LOGLEVEL', 'DEBUG'))

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
        app.logger.debug(f"removing credit from user: {user.__dict__ =}")
        if user.credit < int(amount):
            app.logger.debug(f"{user.credit = } is smaller than {amount =} of credit to remove")
            msg, status_code = "Not enough credit", 403
        else:
            user.credit = user.credit - int(amount)
            db.set(user_id, json.dumps(user.__dict__))
            idx = construct_payment_id(user_id, order_id)
            db.set(idx, json.dumps(Payment(idx, user_id, order_id, amount, True).__dict__))
            app.logger.debug(f"succesfully removed {amount} credit from user with id {user_id}")
            msg, status_code = "Credit removed", 200
    else:
        msg, status_code = "User not found", 404

    app.logger.debug(f"Remove credit result, {msg = }, {status_code = }")
    return msg, status_code


@app.post('/cancel/<user_id>/<order_id>')
def cancel_payment(user_id: str, order_id: str):
    msg, status_code = "User not found", 404
    if db.exists(user_id):
        idx = construct_payment_id(user_id, order_id)
        if db.exists(idx):
            payment = json.loads(db.get(idx))
            payment.paid = False
            user = user_from_json(db.get(user_id))
            user.credit = user.credit + payment.amount
            db.set(user_id, json.dumps(user.__dict__))
            msg, status_code = "payment reset", 200
        else:
            msg, status_code = "Payment not found", 404

    app.logger.debug(f"Cancel payment result, {msg = }, {status_code = }")
    return msg, status_code


@app.post('/status/<user_id>/<order_id>')
def payment_status(user_id: str, order_id: str):
    paid = False
    idx = construct_payment_id(user_id, order_id)
    if db.exists(idx):
        payment = payment_from_json(db.get(idx))
        paid = payment.paid

    app.logger.debug(f"Order with order id: {order_id} ({user_id = }, paid status: {paid}")
    return {"paid": paid}
