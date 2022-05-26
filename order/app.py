import json
import logging
import os
import uuid

import requests
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.dialects.postgresql import JSON

app_name = 'order-service'
app = Flask(app_name)
logging.getLogger(app_name).setLevel(os.environ.get('LOGLEVEL', 'DEBUG'))

stock_url = f'http://{os.environ["STOCK_SERVICE_URL"]}'
user_url = f'http://{os.environ["USER_SERVICE_URL"]}'

DB_URL = 'postgresql+psycopg2://{user}:{pw}@{url}/{db}'\
    .format(user=os.environ['POSTGRES_USER'],
            pw=os.environ['POSTGRES_PASSWORD'],
            url=os.environ['POSTGRES_URL'],
            db=os.environ['POSTGRES_DB'])

app.config['SQLALCHEMY_DATABASE_URI'] = DB_URL
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False  # silence the deprecation warning

db = SQLAlchemy(app)


class Order(db.Model):
    __tablename__ = 'orders'

    id = db.Column(db.String(), primary_key=True)
    paid = db.Column(db.Boolean, unique=False, nullable=False)
    user_id = db.Column(db.String(), unique=False, nullable=False)
    items = db.Column(JSON, unique=False, nullable=True)
    total_cost = db.Column(db.Float, unique=False, nullable=False)

    def __init__(self, id, paid, items, user_id, total_cost):
        self.id = id
        self.paid = paid
        self.items = items
        self.user_id = user_id
        self.total_cost = total_cost

    def __repr__(self):
        return '<id {}>'.format(self.id)


def order_from_json(json_str) -> Order:
    return Order(**json.loads(json_str))


@app.post('/create/<user_id>')
def create_order(user_id):
    idx = str(uuid.uuid4())
    order = Order(idx, False, [], user_id, 0)
    db.session.add(order)
    db.session.commit()
    return {"order_id": idx}


@app.delete('/remove/<order_id>')
def remove_order(order_id):
    Order.query.filter_by(id=order_id).delete()
    db.session.commit()
    return


@app.post('/addItem/<order_id>/<item_id>')
def add_item(order_id, item_id):
    order = Order.query.get_or_404(order_id)
    order.items.append(item_id)
    db.session.add(order)
    db.session.commit()
    return "Item added to order", 200


@app.delete('/removeItem/<order_id>/<item_id>')
def remove_item(order_id, item_id):
    order = Order.query.get_or_404(order_id)
    order.items.remove(item_id)
    db.session.add(order)
    db.session.commit()
    return "Item removed from order", 200


@app.get('/find/<order_id>')
def find_order(order_id):
    return Order.query.get_or_404(order_id)


@app.post('/checkout/<order_id>')
def checkout(order_id):
    app.logger.debug(f"Checking out order {order_id}")
    order = Order.query.get_or_404(order_id)
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
        db.session.add(order)
        db.session.commit()
    app.logger.debug(f"order successful")
    return "Order successful", 200
