import logging
import os
import uuid

from flask import Flask
from flask import request
from flask_sqlalchemy import SQLAlchemy

app_name = 'stock-service'
app = Flask(app_name)
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


class Item(db.Model):
    __tablename__ = 'items'

    id = db.Column(db.String, primary_key=True)
    price = db.Column(db.Float, unique=False, nullable=False)
    stock = db.Column(db.Integer, unique=False, nullable=False)

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


if os.environ.get('DOCKER_COMPOSE_RUN') == "True":
    app.logger.info("Clearing all tables as we're running in DOCKER COMPOSE")
    db.drop_all()

db.create_all()
db.session.commit()


@app.post('/item/create/<price>')
def create_item(price: float):
    """
    Adds an item and its price
    :param price:
    :return: the item's id
    """
    idx = str(uuid.uuid4())
    item = Item(idx, float(price), 0)
    db.session.add(item)
    db.session.commit()
    return {"item_id": idx}, 200


@app.get('/find/<item_id>')
def find_item(item_id: str):
    """
    Return an item's availability and price
    :param item_id:
    :return: Item { id, stock, price }
    """
    app.logger.debug(f"Finding: {item_id=}")
    return Item.query.get_or_404(item_id).as_dict()


@app.post('/add/<item_id>/<amount>')
def add_stock(item_id: str, amount: int):
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
    return "Stock added", 200


@app.post('/subtract/<item_id>/<amount>')
def remove_stock(item_id: str, amount: int):
    """
    Subtracts an item from stock by the amount specified
    :param item_id:
    :param amount:
    :return:
    """
    item = Item.query.get_or_404(item_id)
    app.logger.debug(f"Attempting to take {amount} from stock of {item.__dict__=}")
    if item.stock >= int(amount):
        item.stock = item.stock - int(amount)
        db.session.add(item)
        db.session.commit()
        msg, return_code = "Stock removed", 200
    else:
        msg, return_code = "Not enough stock", 400

    app.logger.debug(f"Remove stock {item_id=}, {amount=} return = {msg=}, {return_code=}")
    return msg, return_code


@app.post('/subtractItems/')
def subtract_items():
    """
    Substracts all items in the list from stock by the amount of 1
    Pass in an 'items_ids" array as JSON in the POST request.
    :return:
    """
    app.logger.debug(f"Subtract the items for request:")
    app.logger.debug(f"{request.json =}")

    items = db.session.query(Item).filter(
        Item.id.in_(request.json['item_ids'])
    )
    app.logger.debug(f"items= {items}")

    item: Item
    for item in items:
        # Return 400 and do not commit when item is out of stock
        if item.stock < 1:
            app.logger.debug(f"Not enough stock")
            return "not enough stock", 400

        item.stock -= 1
        db.session.add(item)

    db.session.commit()

    return "stock subtracted", 200


@app.post('/increaseItems/')
def increase_items():
    """
    This is a rollback function. Following the SAGA pattern.
    Increases all items in the list from stock by the amount of 1
    Pass in an 'items_ids" array as JSON in the POST request.
    :return:
    """
    app.logger.debug(f"Increase the items for request:")
    app.logger.debug(f"{request.json =}")

    items = db.session.query(Item).filter(
        Item.id.in_(request.json['item_ids'])
    )
    app.logger.debug(f"items= {items}")

    item: Item
    for item in items:
        item.stock += 1
        db.session.add(item)

    db.session.commit()

    return "stock increased", 200
