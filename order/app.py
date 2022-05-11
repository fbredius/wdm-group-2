import os
import atexit

from flask import Flask
import redis
import uuid
import json

gateway_url = os.environ['GATEWAY_URL']

app = Flask("order-service")

db: redis.Redis = redis.Redis(host=os.environ['REDIS_HOST'],
                              port=int(os.environ['REDIS_PORT']),
                              password=os.environ['REDIS_PASSWORD'],
                              db=int(os.environ['REDIS_DB']))


def close_db_connection():
    db.close()


atexit.register(close_db_connection)


class Order:
    def __init__(self, order_id, paid, items, user_id, total_cost):
        self.order_id = order_id
        self.paid = paid
        self.items = items
        self.user_id = user_id
        self.total_cost = total_cost


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
    if db.exists(item_id):
        order = json.loads(db.get(order_id))
        order.items = order.items.append(item_id)
        return db.set(order_id, json.dumps(order.__dict__))
    else:
        return "Order not found", 404


@app.delete('/removeItem/<order_id>/<item_id>')
def remove_item(order_id, item_id):
    if db.exists(item_id):
        order = json.loads(db.get(order_id))
        order.items = order.items.remove(item_id)
        return db.set(order_id, json.dumps(order.__dict__))
    else:
        return "Order not found", 404


@app.get('/find/<order_id>')
def find_order(order_id):
    if db.exists(order_id):
        return json.loads(db.get(order_id))
    else:
        return "Order not found", 404


@app.post('/checkout/<order_id>')
def checkout(order_id):
    pass
