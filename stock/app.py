import os
import atexit

from flask import Flask
import redis
import uuid
import json

app = Flask("stock-service")

db: redis.Redis = redis.Redis(host=os.environ['REDIS_HOST'],
                              port=int(os.environ['REDIS_PORT']),
                              password=os.environ['REDIS_PASSWORD'],
                              db=int(os.environ['REDIS_DB']))


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
    db.set(idx, json.dumps(Item(idx, price, 0).__dict__))
    return {"item_id": idx}


@app.get('/find/<item_id>')
def find_item(item_id: str):
    print(item_id)
    print(db.exists(item_id))
    if db.exists(item_id):
        return json.loads(db.get(item_id))
    else:
        return "Item not found", 404


@app.post('/add/<item_id>/<amount>')
def add_stock(item_id: str, amount: int):
    if db.exists(item_id):
        item = json.loads(db.get(item_id))
        item.stock = item.stock + amount
        return db.set(item_id, json.dumps(item.__dict__))
    else:
        return "Item not found", 404


@app.post('/subtract/<item_id>/<amount>')
def remove_stock(item_id: str, amount: int):
    if db.exists(item_id):
        item = json.loads(db.get(item_id))
        item.stock = item.stock - amount
        return db.set(item_id, json.dumps(item.__dict__))
    else:
        return "Item not found", 404
