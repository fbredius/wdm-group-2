import atexit
import json
import logging
import os
import uuid
import pika
import requests

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.types import String, Float, Boolean
from producer import Producer


app_name = 'order-service'
app = Flask(app_name)
logging.getLogger(app_name).setLevel(os.environ.get('LOGLEVEL', 'DEBUG'))

stock_url = f'http://{os.environ["STOCK_SERVICE_URL"]}'
payment_url = f'http://{os.environ["PAYMENT_SERVICE_URL"]}'

DB_URL = 'postgresql+psycopg2://{user}:{pw}@{host}/{db}' \
    .format(user=os.environ['POSTGRES_USER'],
            pw=os.environ['POSTGRES_PASSWORD'],
            host=os.environ['POSTGRES_HOST'],
            db=os.environ['POSTGRES_DB'])

app.config['SQLALCHEMY_DATABASE_URI'] = DB_URL
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False  # silence the deprecation warning

db = SQLAlchemy(app)

# Setup an AMQP connection for this service
connection = pika.BlockingConnection(pika.ConnectionParameters(host='rabbitmq'))  # Change to environment variable
atexit.register(connection.close)


class Order(db.Model):
    __tablename__ = 'orders'

    id = db.Column(String, primary_key=True)
    paid = db.Column(Boolean, unique=False, nullable=False)
    user_id = db.Column(String, unique=False, nullable=False)
    items = db.Column(ARRAY(String, dimensions=1), unique=False, nullable=True)
    total_cost = db.Column(Float, unique=False, nullable=False)

    def __init__(self, id, paid, items, user_id, total_cost):
        self.id = id
        self.paid = paid
        self.items = items
        self.user_id = user_id
        self.total_cost = total_cost

    def __repr__(self):
        return '<id {}>'.format(self.id)

    def as_dict(self):
        dct: dict = self.__dict__.copy()
        dct.pop('_sa_instance_state', None)
        return dct


if os.environ.get('DOCKER_COMPOSE_RUN') == "True":
    app.logger.info("Clearing all tables as we're running in DOCKER COMPOSE")
    db.drop_all()

db.create_all()
db.session.commit()


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
    app.logger.debug(f"Adding item to {order_id = }, {item_id =}")
    order = Order.query.get_or_404(order_id)
    app.logger.debug(f"before {order.items = }")

    # Add item to order.items list
    order.items.append(item_id)
    flag_modified(order, "items")

    # Increase total cost of order
    item = requests.get(f"{stock_url}/stock/find/{item_id}").json()
    order.total_cost += item.price
    flag_modified(order, "total_cost")

    db.session.merge(order)
    db.session.flush()
    db.session.commit()
    app.logger.debug(f"Added item to {order_id = }, {item_id =}, {order.items = }")
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
    return Order.query.get_or_404(order_id).as_dict()


@app.post('/checkout/<order_id>')
def checkout(order_id):
    """
    Handle the checkout.
    First we talk to the stock service to subtract the items.
    Then we talk to the payment service to make the payment.
    If one of both fails, we do rollback the commit, and we return status code 400.
    Else we return 200.
    :param order_id:
    :return:
    """
    app.logger.debug(f"Checking out order {order_id}")
    order: Order = Order.query.get_or_404(order_id)
    app.logger.debug(f"Found order in checkout: {order.as_dict()}")
    if order.paid:
        app.logger.debug(f"order already paid")
        return "Order already paid", 400

    # Setup RabbitMQ producers for the stock and payment requests
    stock_producer = Producer(connection, "stock")
    payment_producer = Producer(connection, "payment")

    # Subtract Stock
    app.logger.debug(f"sending request to stock-service at {stock_url} with order: {order.as_dict()}")
    # stock_response = requests.post(f"{stock_url}/subtractItems", json={
    #     "item_ids": order.items
    # })
    stock_body = json.dumps({"item_ids": order.Items})
    stock_producer.publish(stock_body, "subtractItems", reply=True)

    # Handle Payment
    # payment_request_url = f"{payment_url}/pay/{order.user_id}/{order.id}/{order.total_cost}"
    app.logger.debug(f"requesting payment for {order.total_cost}")  # to {payment_request_url}")
    # payment_response = requests.post(payment_request_url)
    payment_body = json.dumps({"user_id": order.user_id, "order_id": order.id, "total_cost": order.total_cost})
    payment_producer.publish(payment_body, "pay", reply=True)

    # Handle Transaction
    stock_producer.consume()
    payment_producer.consume()

    # TODO Add time-out
    while (stock_producer.status is None) or (payment_producer.status is None):
        stock_producer.connection.process_data_events()
        payment_producer.connection.process_data_events()

    if not (200 <= int(payment_producer.status) < 300):
        # Rollback Stock subtraction if payment fails
        if 200 <= int(stock_producer.status) < 300:
            # requests.post(f"{stock_url}/increaseItems", json={
            #     "item_ids": order.items
            # })
            stock_producer.publish(stock_body, "increaseItems", reply=False)

        msg = payment_producer.response.decode()
        app.logger.debug(f"payment response code not success, {msg}")
        return msg, 400

    if not (200 <= int(stock_producer.status) < 300):
        # Rollback Payment if stock fails
        if 200 <= int(payment_producer.status) < 300:
            requests.post(f"{payment_url}/cancel/{order.user_id}/{order.id}")
            payment_producer.publish(payment_body, "cancel", reply=False)

        msg = stock_producer.response.decode()
        app.logger.debug(f"stock response code not success, {msg}")
        return msg, 400
    else:
        order.paid = True
        db.session.add(order)
        db.session.commit()
    app.logger.debug(f"order successful")

    # Close RabbitMQ connection
    stock_producer.close()
    payment_producer.close()

    return "Order successful", 200
