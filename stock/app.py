import logging
import os
import shutil
import uuid
from http import HTTPStatus
from typing import Dict

import sqlalchemy.exc
from flask_sqlalchemy import SQLAlchemy
from prometheus_client import CollectorRegistry, multiprocess, generate_latest, CONTENT_TYPE_LATEST, Summary
from quart import Quart, make_response, jsonify, Response, request
from sqlalchemy import CheckConstraint, case

logging.basicConfig()
logging.getLogger('sqlalchemy.engine').setLevel(logging.INFO)

app_name = 'stock-service'
app = Quart(app_name)
logging.getLogger(app_name).setLevel(os.environ.get('LOGLEVEL', 'DEBUG'))

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
os.makedirs(PROMETHEUS_MULTIPROC_DIR)

registry = CollectorRegistry()
multiprocess.MultiProcessCollector(registry)


class Item(db.Model):
    __tablename__ = 'items'

    id = db.Column(db.String, primary_key=True)
    price = db.Column(db.Float, unique=False, nullable=False)
    stock = db.Column(db.Integer, unique=False, nullable=False)
    __table_args__ = (
        CheckConstraint(stock >= 0, name='check_stock_positive'), {}
    )

    def __init__(self, id, price, stock):
        self.id = id
        self.price = price
        self.stock = stock

    def __repr__(self):
        return '<id {}>'.format(self.id)

    def as_dict(self):
        dct = self.__dict__.copy()
        dct.pop('_sa_instance_state', None)
        return dct


def recreate_tables():
    db.drop_all()
    db.create_all()
    db.session.commit()


if os.environ.get('DOCKER_COMPOSE_RUN') == "True":
    app.logger.info("Clearing all tables as we're running in DOCKER COMPOSE")
    recreate_tables()

db.create_all()
db.session.commit()

create_item_metric = Summary("create_item", "Summary of /item/create/<price> endpoint")
find_item_metric = Summary("find_item", "Summary of /find/<item_id>")
add_stock_metric = Summary("add_stock", "Summary of /add/<item_id>/<amount>")
remove_stock_metric = Summary("remove_stock", "/subtract/<item_id>/<amount>")
increase_items_metric = Summary("increase_items", "/increaseItems/")
subtract_items_metric = Summary("decrease_items", "/decreaseItems/")


@create_item_metric.time()
@app.post('/item/create/<price>')
async def create_item(price: float):
    """
    Adds an item and its price
    :param price:
    :return: the item's id
    """
    idx = str(uuid.uuid4())
    item = Item(idx, float(price), 0)
    app.logger.debug(f"Adding item {item.as_dict()} to db")
    db.session.add(item)
    db.session.commit()
    return await make_response(jsonify({"item_id": idx}), HTTPStatus.OK)


@find_item_metric.time()
@app.get('/find/<item_id>')
async def find_item(item_id: str):
    """
    Return an item's availability and price
    :param item_id:
    :return: Item { id, stock, price }
    """
    app.logger.debug(f"Finding: {item_id=}")
    return Item.query.get_or_404(item_id).as_dict()


@add_stock_metric.time()
@app.post('/add/<item_id>/<amount>')
async def add_stock(item_id: str, amount: int):
    """
    Adds the given number of stock items to the item count in the stock
    :param item_id:
    :param amount:
    :return:
    """
    item = Item.query.get_or_404(item_id)
    item.stock = item.stock + int(amount)
    db.session.add(item)
    db.session.commit()
    return await make_response("Stock added", HTTPStatus.OK)


@remove_stock_metric.time()
@app.post('/subtract/<item_id>/<amount>')
async def remove_stock(item_id: str, amount: int):
    """
    Subtracts an item from stock by the amount specified
    :param item_id:
    :param amount:
    :return:
    """
    app.logger.debug(f"Attempting to take {amount} from stock of {item_id=}")
    return await update_stock({item_id: Item.stock - int(amount)})


async def update_stock(amounts: Dict[str, int]):
    """
    Update the stock in the database
    If the stock goes below zero, the db will throw an integrity error
    :param amounts:
    :return:
    """
    if len(amounts) > 0:
        try:
            items_affected = db.session.query(Item).filter(
                Item.id.in_(amounts)
            ).update({Item.stock: case(
                amounts,
                value=Item.id
            )})

            db.session.commit()
        except sqlalchemy.exc.IntegrityError:
            app.logger.debug(f"Violated constraint for item when subtracting items")
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
    else:
        app.logger.warning("Items subtract call with no items")
        message = "No items in request"
        response = await make_response(message, HTTPStatus.OK)
    app.logger.debug(f"Update stock response {message}, : {response.status_code}")

    db.session.close()
    return response


@subtract_items_metric.time()
@app.post('/subtractItems/')
async def subtract_items():
    """
    Substracts all items in the list from stock by the amount of 1
    Pass in an 'items_ids" array as JSON in the POST request.
    :return:
    """
    app.logger.debug(f"Subtract the items for request: {request.json =}")
    return await update_stock({id_: Item.stock - 1 for id_ in request.json['item_ids']})


@increase_items_metric.time()
@app.post('/increaseItems/')
async def increase_items():
    """
    This is a rollback function. Following the SAGA pattern.
    Increases all items in the list from stock by the amount of 1
    Pass in an 'items_ids" array as JSON in the POST request.
    :return:
    """
    app.logger.debug(f"Increase the items for request: {request.json =}")
    return await update_stock({id_: Item.stock + 1 for id_ in request.json['item_ids']})


@app.delete('/clear_tables')
async def clear_tables():
    recreate_tables()
    return await make_response("tables cleared", HTTPStatus.OK)


@app.route("/metrics")
def metrics():
    data = generate_latest(registry)
    app.logger.debug(f"Metrics, returning: {data}")
    return Response(data, mimetype=CONTENT_TYPE_LATEST)
