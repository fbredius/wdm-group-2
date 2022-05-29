import logging
import os
import atexit

from flask import Flask
from flask import request
import redis
import uuid
import json
import requests

app = Flask("stock-service")

gateway_url = os.environ['GATEWAY_URL']
logging.getLogger('stock-service').setLevel(os.environ.get('LOGLEVEL', 'DEBUG'))

db: redis.Redis = redis.Redis(host=os.environ['REDIS_HOST'],
                              port=int(os.environ['REDIS_PORT']),
                              password=os.environ['REDIS_PASSWORD'],
                              db=int(os.environ['REDIS_DB']))



# TODO remove this duplicated code, fix with actual imports
class Order:
    def __init__(self, order_id, paid, items, user_id, total_cost):
        self.order_id = order_id
        self.paid = paid
        self.items = items
        self.user_id = user_id
        self.total_cost = total_cost


def order_from_json(json_str) -> Order:
    return Order(**json.loads(json_str))


def class_from_json(json_str):
    return Item(**json.loads(json_str))


def close_db_connection():
    db.close()


atexit.register(close_db_connection)


class Item:
    def __init__(self, item_id, price, stock):
        self.item_id = item_id
        self.price = price
        self.stock = stock


@app.post('/item/create/<price>')
def create_item(price: int):
    idx = str(uuid.uuid4())
    db.set(idx, json.dumps(Item(idx, int(price), 0).__dict__))
    return {"item_id": idx}, 200


@app.get('/find/<item_id>')
def find_item(item_id: str):
    app.logger.debug(item_id)
    app.logger.debug(db.exists(item_id))
    if db.exists(item_id):
        return db.get(item_id), 200
    else:
        return "Item not found", 404


@app.post('/add/<item_id>/<amount>')
def add_stock(item_id: str, amount: int):
    if db.exists(item_id):
        item = class_from_json(db.get(item_id))
        item.stock = item.stock + int(amount)
        db.set(item_id, json.dumps(item.__dict__))
        return "Stock added", 200
    else:
        return "Item not found", 404


@app.post('/subtract/<item_id>/<amount>')
def remove_stock(item_id: str, amount: int):
    msg, return_code = "item not found", 404
    if db.exists(item_id):
        item = class_from_json(db.get(item_id))
        app.logger.debug(f"Attempting to take {amount} from stock of {item.__dict__=}")
        if item.stock >= int(amount):
            item.stock = item.stock - int(amount)
            db.set(item_id, json.dumps(item.__dict__))
            msg, return_code = "Stock removed", 200
        else:
            msg, return_code = "Not enough stock", 400
    app.logger.debug(f"Remove stock {item_id=}, {amount=} return = {msg=}, {return_code=}")
    return msg, return_code


@app.post('/checkout/')
def checkout_items():
    app.logger.debug(f"checkout items for")
    app.logger.debug(f"{request.json =}")
    order = Order(**request.json['order'])
    items = order.items

    # Subtracts stock of all items by 1 and sums prices

    items = [class_from_json(x) for x in db.mget(items)]
    app.logger.debug(f"items= {items}")

    total_price = 0
    for item in items:
        item.stock -= 1
        total_price += item.price

    # pay
    app.logger.debug(f"requesting payment for {total_price}")
    payment_response = requests.post(f"{gateway_url}/payment/pay/{order.user_id}/{order.order_id}/{total_price}")
    if not (200 <= payment_response.status_code < 300):
        app.logger.debug(f"payment response code not success, {payment_response.text}")
        return payment_response.text, 400

    updated_items = {
        item.item_id: json.dumps(item.__dict__) for item in items
    }

    db.mset(updated_items)

    return "paid and stock subtracted", 200

