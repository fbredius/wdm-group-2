import asyncio
import json
import logging
import os
import shutil
import uuid
from http import HTTPStatus

from flask_sqlalchemy import SQLAlchemy
from prometheus_async.aio import time
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Histogram,
    generate_latest, CollectorRegistry, multiprocess,
)
from quart import Quart, make_response, jsonify, Response
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.types import String, Float, Boolean

from producer import Producer, OrderConnection

app_name = 'order-service'
app = Quart(app_name)

logging.basicConfig()
logging.getLogger('sqlalchemy.engine').setLevel(os.environ.get('DB_LOG_LEVEL', logging.WARNING))
logging.getLogger(app_name).setLevel(os.environ.get('LOG_LEVEL', 'DEBUG'))
logger = logging.getLogger(app_name)

stock_url = f'http://{os.environ["STOCK_SERVICE_URL"]}'
payment_url = f'http://{os.environ["PAYMENT_SERVICE_URL"]}'

DB_URL = 'postgresql+psycopg2://{user}:{pw}@{host}/{db}' \
    .format(user=os.environ['POSTGRES_USER'],
            pw=os.environ['POSTGRES_PASSWORD'],
            host=os.environ['POSTGRES_HOST'],
            db=os.environ['POSTGRES_DB'])

app.config['SQLALCHEMY_DATABASE_URI'] = DB_URL
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False  # silence the deprecation warning

db = SQLAlchemy(app, session_options={"expire_on_commit": False})

PROMETHEUS_MULTIPROC_DIR = os.environ["PROMETHEUS_MULTIPROC_DIR"]
# make sure the dir is clean
shutil.rmtree(PROMETHEUS_MULTIPROC_DIR, ignore_errors=True)
os.makedirs(PROMETHEUS_MULTIPROC_DIR)

registry = CollectorRegistry()
multiprocess.MultiProcessCollector(registry)

create_order_metric = Histogram("create_order", "Histogram of /create/<user_id> endpoint")
remove_order_metric = Histogram("remove_order", "Histogram of /remove/<order_id>")
remove_item_metric = Histogram("remove_item", "Histogram of '/removeItem/<order_id>/<item_id>'")
add_item_metric = Histogram("add_item", "Histogram of /removeItem/<order_id>/<item_id>")
find_order_metric = Histogram("find_order", "Histogram of /find/<order_id>")
checkout_metric = Histogram("checkout", "Histogram of /checkout/<order_id>")
handle_rollback_metric = Histogram("handle_rollback", "Histogram of handle rollback")
check_producer_metric = Histogram("check_producer", "Histogram of check producer func")
publish_checkout_metric = Histogram("publish_checkout", "Histogram of publish checkout")
publish_stock_metric = Histogram("publish_stock", "Histogram of publish checkout")
publish_payment_metric = Histogram("publish_payment", "Histogram of publish checkout")

# Create connection and producer objects.
connection = OrderConnection()
stock_producer = Producer("stock")
payment_producer = Producer("payment")


class Order(db.Model):
    __tablename__ = 'orders'

    id = db.Column(String, primary_key=True)
    paid = db.Column(Boolean, unique=False, nullable=False)
    user_id = db.Column(String, unique=False, nullable=False)
    items = db.Column(ARRAY(String, dimensions=1), unique=False, nullable=True)
    total_cost = db.Column(Float, unique=False, nullable=False)

    def __init__(self, id, paid, items, user_id, total_cost):
        """
        Order object containing all relevant fields.
        :param id: ID of order
        :param paid: indicating if order is paid
        :param items: item IDs of order
        :param user_id: ID of user this order belongs to
        :param total_cost: total cost of order
        """
        self.id = id
        self.paid = paid
        self.items = items
        self.user_id = user_id
        self.total_cost = total_cost

    def __repr__(self):
        """
        Representing an instance of this entity with a string containing ID.
        :return: string containing ID
        """
        return '<id {}>'.format(self.id)

    def as_dict(self):
        """
        Convert object to a dictionary.
        :return: dictionary of Order object
        """
        dct: dict = self.__dict__.copy()
        dct.pop('_sa_instance_state', None)
        return dct


# Create all needed tables in database.
db.create_all()
db.session.commit()


def recreate_tables():
    """
    Recreate all tables in the database.
    """
    logger.debug("DB drop all")
    try:
        db.session.close()
        db.drop_all()
    except ProgrammingError:
        logger.warning("Not dropping table as it does not exist")
    logger.debug("DB dropped all")
    logger.debug("DB create all")
    db.create_all()
    logger.debug("DB created all")
    logger.debug("DB commit")
    db.session.commit()
    logger.debug("DB commited")
    db.session.close()


@app.post('/create/<user_id>')
@time(create_order_metric)
async def create_order(user_id):
    """
    Creates an order for the given user, and returns an order_id.
    :param user_id: ID of user to create an order for
    :return: the created order's ID
    """
    order_id = str(uuid.uuid4())
    order = Order(order_id, False, [], user_id, 0)

    db.session.add(order)
    db.session.commit()
    db.session.close()

    return await make_response(jsonify({"order_id": order_id}), HTTPStatus.OK)


@app.delete('/remove/<order_id>')
@time(remove_order_metric)
async def remove_order(order_id):
    """
    Deletes an order by ID.
    :param order_id: order ID to delete
    :return: response indicating success of deletion
    """
    Order.query.filter_by(id=order_id).delete()

    db.session.commit()
    db.session.close()

    return await make_response('success', HTTPStatus.OK)


@app.post('/addItem/<order_id>/<item_id>')
@time(add_item_metric)
async def add_item(order_id, item_id):
    """
    Adds a given item, by ID, in the order, by ID, given.
    :param order_id: ID of order to add item to
    :param item_id: ID of item to add to order
    :return: response indicating success of adding item
    """
    logger.debug(f"Adding item to {order_id = }, {item_id =}")
    order = Order.query.get_or_404(order_id)
    logger.debug(f"before {order.items = }")

    # Add item to order.items list
    order.items.append(item_id)
    flag_modified(order, "items")

    # Increase total cost of order
    await check_producer()
    body = json.dumps({"item_id": item_id})
    response = await stock_producer.publish(body, "getPrice", reply=True)
    order.total_cost += json.loads(response['message'])['price']
    flag_modified(order, "total_cost")

    logger.debug(f"Added item to {order_id = }, {item_id =}, {order.items = }")

    db.session.merge(order)
    db.session.flush()
    db.session.commit()
    db.session.close()

    return await make_response("Item added to order", HTTPStatus.OK)


@app.delete('/removeItem/<order_id>/<item_id>')
@time(remove_item_metric)
async def remove_item(order_id, item_id):
    """
    Removes the given item, by ID, from the given order, by ID.
    :param order_id: ID of order to remove item from
    :param item_id: ID of item to remove from order
    :return: response indicating success of adding item
    """
    order = Order.query.get_or_404(order_id)

    # Remove item from order.items list
    order.items.remove(item_id)
    flag_modified(order, "items")

    # Decrease total cost of order
    await check_producer()
    body = json.dumps({"item_id": item_id})
    response = await stock_producer.publish(body, "getPrice", reply=True)
    order.total_cost -= json.loads(response['message'])['price']
    flag_modified(order, "total_cost")

    db.session.add(order)
    db.session.commit()
    db.session.close()

    return await make_response("Item removed from order", HTTPStatus.OK)


@app.get('/find/<order_id>')
@time(find_order_metric)
async def find_order(order_id):
    """
    Retrieve the order entity of given order ID.
    :param order_id: ID of order to find
    :return: object containing order: Order { order_id, paid, items, user_id, total_cost }
    """
    return Order.query.get_or_404(order_id).as_dict()


@time(publish_checkout_metric)
async def publish_checkout(payment_body, stock_body):
    await check_producer()

    payment_response, stock_response = await asyncio.gather(payment_producer.publish(payment_body, "pay", reply=True),
                                                            stock_producer.publish(stock_body, "subtractItems",
                                                                                   reply=True)
                                                            )
    return payment_response, stock_response


@app.post('/checkout/<order_id>')
@time(checkout_metric)
async def checkout(order_id):
    """
    Handle the checkout.
    First we talk to the stock service to subtract the items.
    Then we talk to the payment service to make the payment.
    If one of both fails, we do rollback the commit, and we return status code 400.
    Else we return 200.
    :param order_id: ID of order to checkout.
    :return: response 200 if successful, 400 if something fails
    """
    logger.debug(f"Checking out order {order_id}")
    order: Order = Order.query.get_or_404(order_id)
    logger.debug(f"Found order in checkout: {order.as_dict()}")

    if order.paid:
        logger.debug(f"Order already paid")
        return make_response("Order already paid", HTTPStatus.BAD_REQUEST)

    # Setup RabbitMQ producers for the stock and payment requests

    # Creating the body for the messages
    logger.info(f"order: {order.as_dict()}")
    stock_body = json.dumps({"item_ids": order.items})
    payment_body = json.dumps({"user_id": order.user_id, "order_id": order.id, "total_cost": order.total_cost})

    # Send the payment and stock task to the respective queues simultaneously
    payment_response, stock_response = await publish_checkout(payment_body, stock_body)

    # If one of the tasks fails, start a rollback
    logger.debug(f"order id: {order_id}, payment response: {payment_response}")
    logger.debug(f"order id: {order_id}, stock response: {stock_response}")
    if not status_code_is_success(int(payment_response["status"])) \
            or not status_code_is_success(int(stock_response["status"])):
        return await handle_rollback(payment_body, stock_body,
                                     payment_response, stock_response)

    logger.debug(f"order id: {order_id} Payment and stock successful")
    # If success set Order status to 'paid'
    await set_order_to_paid(order)

    return await make_response("Order successful", HTTPStatus.OK)


def status_code_is_success(status_code):
    """
    Check if a certain status code indicates success.
    :param status_code: status code to check for
    :return: boolean indicating whether code is successful
    """
    return HTTPStatus.OK <= status_code < HTTPStatus.MULTIPLE_CHOICES


@time(handle_rollback_metric)
async def handle_rollback(payment_body, stock_body, payment_response, stock_response):
    """
    Handles rollback for SAGA pattern. Handles different cases of failure.
    :param payment_body: body sent to payment service
    :param stock_body: body sent to stock service
    :param payment_response: response from payment service
    :param stock_response: response from stock service
    :return:
    """
    message = ""
    if not status_code_is_success(int(payment_response["status"])):
        logger.debug(f"Payment response code not success, {message}. payment body {payment_body}")
        # Rollback Stock subtraction if Payment fails and Stock subtraction was success
        if status_code_is_success(int(stock_response["status"])):
            logger.debug(
                f"stock_response response code success, {message}, rolling back stock. payment_body:{payment_body}")
            await stock_producer.publish(stock_body, "increaseItems", reply=False)

        message += payment_response["message"] + "\t\t"

    if not status_code_is_success(int(stock_response["status"])):
        logger.debug(f"Stock response code not success, {message}. payment body {payment_body}")
        # Rollback Payment if Stock subtraction fails and Payment was success
        if status_code_is_success(int(payment_response["status"])):
            logger.debug(
                f"Payment response code not success, {message}, rolling back payment. payment_body: {payment_body}")
            await payment_producer.publish(payment_body, "cancel", reply=False)

        message += stock_response["message"]
    return await make_response(message, HTTPStatus.BAD_REQUEST)


async def set_order_to_paid(order):
    """
    Updating an order to be paid.
    :param order: order object to be updated.
    """
    order.paid = True

    db.session.add(order)
    db.session.commit()
    db.session.close()

    logger.debug(f"order successful")


@app.delete('/clear_tables')
async def clear_tables():
    """
    Clear all database tables of this service.
    :return: 200 if database tables were cleared
    """
    recreate_tables()
    return await make_response("tables cleared", HTTPStatus.OK)


@app.route("/metrics")
async def metrics():
    """
    Get metrics of this service instance.
    :return: response object with metrics data
    """
    data = generate_latest(registry)
    logger.debug(f"Metrics, returning: {data}")
    return Response(data, mimetype=CONTENT_TYPE_LATEST)


@time(check_producer_metric)
async def check_producer():
    """
    Check producer if ready, otherwise initialize.
    """
    if not stock_producer.is_ready() or not payment_producer.is_ready():
        conn: OrderConnection = await connection.get_connection()
        await stock_producer.connect(conn)
        await payment_producer.connect(conn)
