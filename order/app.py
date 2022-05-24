import atexit
import json
import logging
import os
import uuid

import redis
import requests
from flask import Flask

app_name = 'order-service'
app = Flask(app_name)
logging.getLogger(app_name).setLevel(os.environ.get('LOGLEVEL', 'DEBUG'))

stock_url = f'http://{os.environ["STOCK_SERVICE_URL"]}'
user_url = f'http://{os.environ["USER_SERVICE_URL"]}'
db: redis.Redis = redis.Redis(host=os.environ['REDIS_HOST'],
                              port=int(os.environ['REDIS_PORT']),
                              password=os.environ['REDIS_PASSWORD'],
                              db=int(os.environ['REDIS_DB']))


def close_db_connection():
    db.close()


atexit.register(close_db_connection)


# TODO remove this duplicated code, fix with actual imports
def class_from_json(json_str):
    return Item(**json.loads(json_str))


class Item:
    def __init__(self, item_id, price, stock):
        self.item_id = item_id
        self.price = price
        self.stock = stock


class Order:
    def __init__(self, order_id, paid, items, user_id, total_cost):
        self.order_id = order_id
        self.paid = paid
        self.items = items
        self.user_id = user_id
        self.total_cost = total_cost


def order_from_json(json_str) -> Order:
    return Order(**json.loads(json_str))


@app.post('/create/<user_id>')
def create_order(user_id):
    idx = str(uuid.uuid4())
    db.set(idx, json.dumps(Order(idx, False, [], user_id, 0).__dict__))
    return {"order_id": idx}


@app.delete('/remove/<order_id>')
def remove_order(order_id):
    return db.delete(order_id)


@app.post('/addItem/<order_id>/<item_id>')
def add_item(order_id, item_id):
    if db.exists(order_id):
        order = order_from_json(db.get(order_id))
        order.items.append(item_id)
        db.set(order_id, json.dumps(order.__dict__))
        return "Order added", 200
    else:
        return "Order not found", 404


@app.delete('/removeItem/<order_id>/<item_id>')
def remove_item(order_id, item_id):
    if db.exists(item_id):
        order = order_from_json(db.get(order_id))
        order.items.remove(item_id)
        return db.set(order_id, json.dumps(order.__dict__))
    else:
        return "Order not found", 404


@app.get('/find/<order_id>')
def find_order(order_id):
    if db.exists(order_id):
        return db.get(order_id)
    else:
        return "Order not found", 404


@app.post('/checkout/<order_id>')
def checkout(order_id):
    app.logger.debug(f"Checking out order {order_id}")
    if db.exists(order_id):
        order = order_from_json(db.get(order_id))
        if order.paid:
            app.logger.debug(f"order already paid")
            return "Order already paid", 200

        # Send all items to stock service
        # if enough stock
        # accumulate price and send to payment service
        # if enough credit
        # pay
        # if paid remove stock
        # if paid return success

        # Get prices of all items in order
        app.logger.debug(f"sending request to stock-service at {stock_url}")
        stock_response = requests.post(f"{stock_url}/checkout", json={
            "order": order.__dict__
        })

        # TODO handle all cases except the positive one
        if not (200 <= stock_response.status_code < 300):
            app.logger.debug(f"stock response code not success, {stock_response.text}")
            return stock_response.text, 400
        else:
            order.paid = True
            db.set(order_id, json.dumps(order.__dict__))
        app.logger.debug(f"order successful")
        return "Order successful", 200
    else:
        return "Order not found", 404
