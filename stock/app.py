import json
import logging
import os
import shutil
import uuid
from http import HTTPStatus
from typing import Dict

import sqlalchemy.exc
from flask_sqlalchemy import SQLAlchemy
from prometheus_async.aio import time
from prometheus_client import CollectorRegistry, multiprocess, generate_latest, CONTENT_TYPE_LATEST, Summary
from quart import Quart, make_response, jsonify, Response, request
from sqlalchemy import CheckConstraint, case
from sqlalchemy.exc import ProgrammingError

app_name = 'stock-service'
app = Quart(app_name)

logging.basicConfig()
logging.getLogger('sqlalchemy.engine').setLevel(os.environ.get('DB_LOG_LEVEL', logging.WARNING))
logging.getLogger(app_name).setLevel(os.environ.get('LOG_LEVEL', 'DEBUG'))
logger = logging.getLogger(app_name)

payment_url = f"http://{os.environ['PAYMENT_SERVICE_URL']}"

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
os.makedirs(PROMETHEUS_MULTIPROC_DIR, exist_ok=True)

registry = CollectorRegistry()
multiprocess.MultiProcessCollector(registry)


create_item_metric = Summary("create_item", "Summary of /item/create/<price> endpoint")
find_item_metric = Summary("find_item", "Summary of /find/<item_id>")
add_stock_metric = Summary("add_stock", "Summary of /add/<item_id>/<amount>")
remove_stock_metric = Summary("remove_stock", "/subtract/<item_id>/<amount>")
increase_items_metric = Summary("increase_items", "/increaseItems/")
subtract_items_metric = Summary("decrease_items", "/decreaseItems/")
update_stock_db_metric = Summary("db_update_stock", "updateStock function")


class Item(db.Model):
    __tablename__ = 'items'

    id = db.Column(db.String, primary_key=True)
    price = db.Column(db.Float, unique=False, nullable=False)
    stock = db.Column(db.Integer, unique=False, nullable=False)
    __table_args__ = (
        CheckConstraint(stock >= 0, name='check_stock_positive'), {}
    )

    def __init__(self, id, price, stock):
        """
        Item object containing all relevant fields.
        :param id: ID of item
        :param price: Price of the item
        :param stock: Amount of stock left for the item
        """
        self.id = id
        self.price = price
        self.stock = stock

    def __repr__(self):
        """
        Representing an instance of this entity with a string containing ID.
        :return: string containing ID
        """
        return '<id {}>'.format(self.id)

    def as_dict(self):
        """
        Convert object to a dictionary.
        :return: dictionary of Item object
        """
        dct = self.__dict__.copy()
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
    logger.debug("DB committed")


@app.post('/item/create/<price>')
@time(create_item_metric)
async def create_item(price: float):
    """
    Create a new item with a certain price.
    :param price: price of the item
    :return: ID of the item
    """
    item_id = str(uuid.uuid4())
    item = Item(item_id, float(price), 0)
    logger.debug(f"Adding item {item.as_dict()} to db")

    db.session.add(item)
    db.session.commit()
    db.session.close()

    return await make_response(jsonify({"item_id": item_id}), HTTPStatus.OK)


@app.get('/find/<item_id>')
@time(find_item_metric)
async def find_item(item_id: str):
    """
    Return an item's availability and price.
    :param item_id: ID of item to get information from
    :return: item object as Item { id, stock, price }
    """
    logger.debug(f"Finding: {item_id=}")
    item = Item.query.get_or_404(item_id).as_dict()
    logger.debug(f"Found: {item}")
    return item


async def get_item_price(item_id: str):
    """
    Get price of a certain item.
    :param item_id: ID of item
    :return: price of item
    """
    item = Item.query.get_or_404(item_id).as_dict()
    return await make_response(json.dumps({"price": item["price"]}), HTTPStatus.OK)


@app.post('/add/<item_id>/<amount>')
@time(add_stock_metric)
async def add_stock(item_id: str, amount: int):
    """
    Adds the given number of stock items to the item count in the stock.
    :param item_id: ID of the item to be added
    :param amount: amount of items to be added
    :return: response indicating success of update
    """
    item = Item.query.get_or_404(item_id)
    item.stock = item.stock + int(amount)

    db.session.add(item)
    db.session.commit()
    db.session.close()

    return await make_response("Stock added", HTTPStatus.OK)


@app.post('/subtract/<item_id>/<amount>')
@time(remove_stock_metric)
async def remove_stock(item_id: str, amount: int):
    """
    Subtracts an item from stock by the amount specified.
    :param item_id: ID of item to be subtracted
    :param amount: amount to be subtracted
    :return: response indicating success of update
    """
    logger.debug(f"Attempting to take {amount} from stock of {item_id=}")
    return await update_stock({item_id: Item.stock - int(amount)})


@time(update_stock_db_metric)
async def update_stock(amounts: Dict[str, int]):
    """
    Update the stock in the database
    If the stock goes below zero, the db will throw an integrity error
    :param amounts: amount dictionary of items with corresponding amount to be updated
    :return: response indicating success of update
    """
    if len(amounts) <= 0:
        logger.warning("Items subtract call with no items")
        message = "No items in request"
        return await make_response(message, HTTPStatus.OK)

    try:
        items_affected = db.session.query(Item).filter(
            Item.id.in_(amounts)
        ).update({Item.stock: case(
            amounts,
            value=Item.id
        )})

        db.session.commit()
    except sqlalchemy.exc.IntegrityError:
        logger.debug(f"Violated constraint for item when subtracting items")
        message = "Not enough stock"
        response = await make_response(message, HTTPStatus.BAD_REQUEST)
        db.session.rollback()
    else:
        if items_affected != len(amounts):
            message = "Stock subtracting failed for at least 1 item"
            response = await make_response(message, HTTPStatus.BAD_REQUEST)
        else:
            message = "stock subtracted"
            response = await make_response(message, HTTPStatus.OK)

    logger.debug(f"Update stock response {message}, : {response.status_code}")

    db.session.close()
    return response


@app.post('/subtractItems/')
@time(subtract_items_metric)
async def subtract_items():
    """
    Subtracts all items in the list from stock by the amount of 1
    Pass in an 'items_ids" array as JSON in the POST request.
    :return: response indicating success of update
    """
    logger.debug(f"Subtract the items for request: {request.json =}")
    return await update_stock({id_: Item.stock - 1 for id_ in request.json['item_ids']})


@app.post('/increaseItems/')
@time(increase_items_metric)
async def increase_items():
    """
    This is a rollback function. Following the SAGA pattern.
    Increases all items in the list from stock by the amount of 1
    Pass in an 'items_ids" array as JSON in the POST request.
    :return: response indicating success of update
    """
    logger.debug(f"Increase the items for request: {request.json =}")
    return await update_stock({id_: Item.stock + 1 for id_ in request.json['item_ids']})


@app.delete('/clear_tables')
async def clear_tables():
    """
    Clear all database tables of this service.
    :return: 200 if database tables were cleared
    """
    recreate_tables()
    return await make_response("tables cleared", HTTPStatus.OK)


@app.route("/metrics")
def metrics():
    """
    Get metrics of this service instance.
    :return: response object with metrics data
    """
    data = generate_latest(registry)
    logger.debug(f"Metrics, returning: {data}")
    return Response(data, mimetype=CONTENT_TYPE_LATEST)
