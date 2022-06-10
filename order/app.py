import atexit
import json
import logging
import os
import shutil
import uuid
from http import HTTPStatus
import pika
import requests
from flask import Flask, make_response, jsonify
from flask import Response
from flask_sqlalchemy import SQLAlchemy
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Histogram,
    generate_latest, CollectorRegistry, multiprocess,
)
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
connection = pika.BlockingConnection(pika.ConnectionParameters(host='rabbitmq', heartbeat=None))  # Change to environment variable
atexit.register(connection.close)

PROMETHEUS_MULTIPROC_DIR = os.environ["PROMETHEUS_MULTIPROC_DIR"]
# make sure the dir is clean
shutil.rmtree(PROMETHEUS_MULTIPROC_DIR, ignore_errors=True)
os.makedirs(PROMETHEUS_MULTIPROC_DIR)

registry = CollectorRegistry()
multiprocess.MultiProcessCollector(registry)


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


def recreate_tables():
    db.drop_all()
    db.create_all()
    db.session.commit()


total_time_metric = Histogram("order_time", "Time of all requests in order app")
create_order_metric = Histogram("create_order", "Histogram of /create/<user_id> endpoint")
remove_order_metric = Histogram("remove_order", "Histogram of /remove<order_id>")
add_item_metric = Histogram("add_item", "Histogram of /removeItem/<order_id>/<item_id>")
find_order_metric = Histogram("find_order", "Histogram of /find/<order_id>")
checkout_metric = Histogram("checkout", "Histogram of /checkout/<order_id>")


@app.post('/create/<user_id>')
@create_order_metric.time()
@total_time_metric.time()
def create_order(user_id):
    """
    Creates an order for the given user, and returns an order_id
    :param user_id:
    :return: the order's id
    """
    idx = str(uuid.uuid4())
    order = Order(idx, False, [], user_id, 0)
    db.session.add(order)
    db.session.commit()
    return make_response(jsonify({"order_id": idx}), HTTPStatus.OK)


@app.delete('/remove/<order_id>')
@remove_order_metric.time()
@total_time_metric.time()
def remove_order(order_id):
    """
    Deletes an order by ID
    :param order_id:
    :return:
    """
    Order.query.filter_by(id=order_id).delete()
    db.session.commit()
    return make_response('success', HTTPStatus.OK)


@app.post('/addItem/<order_id>/<item_id>')
@add_item_metric.time()
@total_time_metric.time()
def add_item(order_id, item_id):
    """
    Adds a given item in the order given
    :param order_id:
    :param item_id:
    :return:
    """
    app.logger.debug(f"Adding item to {order_id = }, {item_id =}")
    order = Order.query.get_or_404(order_id)
    app.logger.debug(f"before {order.items = }")

    # Add item to order.items list
    order.items.append(item_id)
    flag_modified(order, "items")

    # Increase total cost of order
    item = requests.get(f"{stock_url}/find/{item_id}").json()
    order.total_cost += item['price']
    flag_modified(order, "total_cost")

    db.session.merge(order)
    db.session.flush()
    db.session.commit()
    app.logger.debug(f"Added item to {order_id = }, {item_id =}, {order.items = }")
    return make_response("Item added to order", HTTPStatus.OK)


@app.delete('/removeItem/<order_id>/<item_id>')
@remove_order_metric.time()
@total_time_metric.time()
def remove_item(order_id, item_id):
    """
    Removes the given item from the given order
    :param order_id:
    :param item_id:
    :return:
    """
    order = Order.query.get_or_404(order_id)

    # Remove item from order.items list
    order.items.remove(item_id)
    flag_modified(order, "items")

    # Decrease total cost of order
    item = requests.get(f"{stock_url}/find/{item_id}").json()
    order.total_cost -= item['price']
    flag_modified(order, "total_cost")

    db.session.add(order)
    db.session.commit()
    return make_response("Item removed from order", HTTPStatus.OK)


@app.get('/find/<order_id>')
@find_order_metric.time()
@total_time_metric.time()
def find_order(order_id):
    """
    Retrieves the information of an order
    :param order_id:
    :return: Order { order_id, paid, items, user_id, total_cost }
    """
    return Order.query.get_or_404(order_id).as_dict()


@app.post('/checkout/<order_id>')
@checkout_metric.time()
@total_time_metric.time()
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
        app.logger.debug(f"Order already paid")
        return make_response("Order already paid", HTTPStatus.BAD_REQUEST)

    # Setup RabbitMQ producers for the stock and payment requests
    stock_producer = Producer(connection, "stock")
    payment_producer = Producer(connection, "payment")

    # Subtract Stock
    stock_body = subtract_stock(order, stock_producer)

    # Handle Payment
    payment_body = handle_payment(order, payment_producer)

    # Handle Transaction
    stock_producer.consume()
    payment_producer.consume()

    # TODO Add time-out
    listen_for_events(payment_producer, stock_producer)

    # Handle Rollback according to SAGA Pattern
    if not status_code_is_success(int(payment_producer.status)) \
            or not status_code_is_success(int(stock_producer.status)):
        return handle_rollback(payment_producer, stock_producer, payment_body, stock_body)

    # If success set Order status to 'paid'
    set_order_to_paid(order)

    # Close RabbitMQ connection
    stock_producer.close()
    payment_producer.close()

    return make_response("Order successful", HTTPStatus.OK)


def status_code_is_success(status_code):
    return HTTPStatus.OK <= status_code < HTTPStatus.MULTIPLE_CHOICES


def handle_rollback(payment_producer, stock_producer, payment_body, stock_body):
    if not status_code_is_success(int(payment_producer.status)):
        # Rollback Stock subtraction if Payment fails and Stock subtraction was success
        if status_code_is_success(int(stock_producer.status)):
            stock_producer.publish(stock_body, "increaseItems", reply=False)

        # Close RabbitMQ connection
        stock_producer.close()
        payment_producer.close()

        app.logger.debug(f"Payment response code not success, {payment_producer.response.decode()}")
        return make_response(payment_producer.response.decode(), HTTPStatus.BAD_REQUEST)

    if not status_code_is_success(int(stock_producer.status)):
        # Rollback Payment if Stock subtraction fails and Payment was success
        if status_code_is_success(int(payment_producer.status)):
            payment_producer.publish(payment_body, "cancel", reply=False)

        # Close RabbitMQ connection
        stock_producer.close()
        payment_producer.close()

        app.logger.debug(f"Stock response code not success, {stock_producer.response.decode()}")
        return make_response(stock_producer.response.decode(), HTTPStatus.BAD_REQUEST)


def set_order_to_paid(order):
    order.paid = True
    db.session.add(order)
    db.session.commit()
    db.session.close()
    app.logger.debug(f"order successful")


def listen_for_events(payment_producer, stock_producer):
    while (stock_producer.status is None) or (payment_producer.status is None):
        stock_producer.connection.process_data_events()
        payment_producer.connection.process_data_events()


def handle_payment(order, payment_producer):
    payment_request_url = f"{payment_url}/pay/{order.user_id}/{order.id}/{order.total_cost}"
    app.logger.debug(f"requesting payment for {order.total_cost} to {payment_request_url}")
    payment_body = json.dumps({"user_id": order.user_id, "order_id": order.id, "total_cost": order.total_cost})
    payment_producer.publish(payment_body, "pay", reply=True)
    return payment_body


def subtract_stock(order, stock_producer):
    app.logger.debug(f"sending request to stock-service at {stock_url} with order: {order.as_dict()}")
    stock_body = json.dumps({"item_ids": order.items})
    stock_producer.publish(stock_body, "subtractItems", reply=True)
    return stock_body


@app.delete('/clear_tables')
def clear_tables():
    recreate_tables()
    return make_response("tables cleared", HTTPStatus.OK)


@app.route("/metrics")
def metrics():
    data = generate_latest(registry)
    app.logger.debug(f"Metrics, returning: {data}")
    return Response(data, mimetype=CONTENT_TYPE_LATEST)
