import asyncio
import json
import logging
import os
import shutil
import uuid
import requests

from http import HTTPStatus
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
from quart import Quart, make_response, jsonify, Response

app_name = 'order-service'
app = Quart(app_name)
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


@create_order_metric.time()
@total_time_metric.time()
@app.post('/create/<user_id>')
async def create_order(user_id):
    """
    Creates an order for the given user, and returns an order_id
    :param user_id:
    :return: the order's id
    """
    idx = str(uuid.uuid4())
    app.logger.debug(f"ID IS:          {idx}")
    order = Order(idx, False, [], user_id, 0)
    db.session.add(order)
    db.session.commit()
    return await make_response(jsonify({"order_id": idx}), HTTPStatus.OK)


@remove_order_metric.time()
@total_time_metric.time()
@app.delete('/remove/<order_id>')
async def remove_order(order_id):
    """
    Deletes an order by ID
    :param order_id:
    :return:
    """
    Order.query.filter_by(id=order_id).delete()
    db.session.commit()
    return await make_response('success', HTTPStatus.OK)


@add_item_metric.time()
@total_time_metric.time()
@app.post('/addItem/<order_id>/<item_id>')
async def add_item(order_id, item_id):
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
    return await make_response("Item added to order", HTTPStatus.OK)


@remove_order_metric.time()
@total_time_metric.time()
@app.delete('/removeItem/<order_id>/<item_id>')
async def remove_item(order_id, item_id):
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
    return await make_response("Item removed from order", HTTPStatus.OK)


@find_order_metric.time()
@total_time_metric.time()
@app.get('/find/<order_id>')
async def find_order(order_id):
    """
    Retrieves the information of an order
    :param order_id:
    :return: Order { order_id, paid, items, user_id, total_cost }
    """
    return Order.query.get_or_404(order_id).as_dict()


@checkout_metric.time()
@total_time_metric.time()
@app.post('/checkout/<order_id>')
async def checkout(order_id):
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
    stock_producer = await Producer("stock").connect()
    payment_producer = await Producer("payment").connect()

    # Creating the body for the messages
    stock_body = json.dumps({"item_ids": order.items})
    payment_body = json.dumps({"user_id": order.user_id, "order_id": order.id, "total_cost": order.total_cost})

    # Send the payment and stock task to the respective queues simultaneously
    payment_response, stock_response = await asyncio.gather(payment_producer.publish(payment_body, "pay", reply=True),
                                                            stock_producer.publish(stock_body, "subtractItems", reply=True))

    # If one of the tasks fails, start a rollback
    if not status_code_is_success(int(payment_response["status"])) \
            or not status_code_is_success(int(stock_response["status"])):
        return await handle_rollback(payment_producer, stock_producer, payment_body, stock_body,
                                     payment_response, stock_response)

    # If success set Order status to 'paid'
    await set_order_to_paid(order)

    return await make_response("Order successful", HTTPStatus.OK)


def status_code_is_success(status_code):
    return HTTPStatus.OK <= status_code < HTTPStatus.MULTIPLE_CHOICES


async def handle_rollback(payment_producer, stock_producer, payment_body, stock_body, payment_response, stock_response):
    if not status_code_is_success(int(payment_response["status"])):
        # Rollback Stock subtraction if Payment fails and Stock subtraction was success
        if status_code_is_success(int(stock_response["status"])):
            await stock_producer.publish(stock_body, "increaseItems", reply=False)

        message = payment_response["message"]
        app.logger.debug(f"Payment response code not success, {message}")
        return await make_response(message, HTTPStatus.BAD_REQUEST)

    if not status_code_is_success(int(stock_response["status"])):
        # Rollback Payment if Stock subtraction fails and Payment was success
        if status_code_is_success(int(payment_response["status"])):
            await payment_producer.publish(payment_body, "cancel", reply=False)

        message = stock_response["message"]
        app.logger.debug(f"Stock response code not success, {message}")
        return await make_response(message, HTTPStatus.BAD_REQUEST)


async def set_order_to_paid(order):
    order.paid = True
    db.session.add(order)
    db.session.commit()
    db.session.close()
    app.logger.debug(f"order successful")


@app.delete('/clear_tables')
async def clear_tables():
    recreate_tables()
    return await make_response("tables cleared", HTTPStatus.OK)


@app.route("/metrics")
async def metrics():
    data = generate_latest(registry)
    app.logger.debug(f"Metrics, returning: {data}")
    return await Response(data, mimetype=CONTENT_TYPE_LATEST)
