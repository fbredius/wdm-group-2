import logging
import os
import shutil
import uuid

from flask import Flask, Response
from flask_sqlalchemy import SQLAlchemy
from prometheus_client import CollectorRegistry, multiprocess, Summary, CONTENT_TYPE_LATEST, generate_latest

app_name = 'payment-service'
app = Flask(app_name)
logging.getLogger(app_name).setLevel(os.environ.get('LOGLEVEL', 'DEBUG'))

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


class User(db.Model):
    __tablename__ = 'users'

    id = db.Column(db.String(), primary_key=True)
    credit = db.Column(db.Float, unique=False, nullable=False)

    def __init__(self, id, credit):
        self.id = id
        self.credit = credit

    def as_dict(self):
        dct: dict = self.__dict__.copy()
        dct.pop('_sa_instance_state', None)
        return dct


class Payment(db.Model):
    __tablename__ = 'payments'

    id = db.Column(db.String(), primary_key=True)
    user_id = db.Column(db.String(), unique=False, nullable=False)
    order_id = db.Column(db.String(), unique=False, nullable=False)
    amount = db.Column(db.Float, unique=False, nullable=False)
    paid = db.Column(db.Boolean, unique=False, nullable=False)

    def __init__(self, id, user_id, order_id, amount, paid):
        self.id = id
        self.user_id = user_id
        self.order_id = order_id
        self.amount = amount
        self.paid = paid

    def as_dict(self):
        dct = self.__dict__.copy()
        dct.pop('_sa_instance_state', None)
        return dct


if os.environ.get('DOCKER_COMPOSE_RUN') == "True":
    app.logger.info("Clearing all tables as we're running in DOCKER COMPOSE")
    db.drop_all()

db.create_all()
db.session.commit()

create_order_metric = Summary("create_user", "Summary of /create_user endpoint")
find_user_metric = Summary("find_user", "Summary of /find_user/<user_id>")
add_credit_metric = Summary("add_credit", "Summary of /add_funds/<user_id>/<amount>")
remove_credit_metric = Summary("remove_credit", "Summary of /pay/<user_id>/<order_id>/<amount>")
cancel_payment_metric = Summary("cancel_payment", "/cancel/<user_id>/<order_id>")
payment_status_metric = Summary("payment_status", "/status/<user_id>/<order_id>")


def construct_payment_id(user_id, order_id):
    return user_id + '/' + order_id


@app.post('/create_user')
@create_order_metric.time()
def create_user():
    idx = str(uuid.uuid4())
    user = User(idx, 0)
    db.session.add(user)
    db.session.commit()
    return {"user_id": idx}


@app.get('/find_user/<user_id>')
@find_user_metric.time()
def find_user(user_id: str):
    return User.query.get_or_404(user_id).as_dict()


@app.post('/add_funds/<user_id>/<amount>')
@add_credit_metric.time()
def add_credit(user_id: str, amount: float):
    user = User.query.filter_by(id=user_id).first()
    done = False
    if bool(user):
        user.credit = user.credit + float(amount)
        db.session.add(user)
        db.session.commit()
        done = True

    return {"done": done}


@app.post('/pay/<user_id>/<order_id>/<amount>')
@remove_credit_metric.time()
def remove_credit(user_id: str, order_id: str, amount: float):
    user = User.query.get_or_404(user_id)
    app.logger.debug(f"removing credit from user: {user.__dict__ =}")
    amount = float(amount)
    if user.credit < amount:
        app.logger.debug(f"{user.credit = } is smaller than {amount =} of credit to remove")
        msg, status_code = "Not enough credit", 403
    else:
        user.credit = user.credit - amount
        db.session.add(user)
        idx = construct_payment_id(user_id, order_id)
        payment = Payment(idx, user_id, order_id, amount, True)
        db.session.add(payment)
        app.logger.debug(f"succesfully removed {amount} credit from user with id {user_id}")
        db.session.commit()
        msg, status_code = "Credit removed", 200

    app.logger.debug(f"Remove credit result, {msg = }, {status_code = }")
    return msg, status_code


@app.post('/cancel/<user_id>/<order_id>')
@cancel_payment_metric.time()
def cancel_payment(user_id: str, order_id: str):
    user = User.query.get_or_404(user_id)
    idx = construct_payment_id(user_id, order_id)
    payment = Payment.query.get_or_404(idx)
    payment.paid = False
    user.credit = user.credit + payment.amount
    db.session.add(user)
    db.session.commit()

    msg, status_code = "payment reset", 200

    app.logger.debug(f"Cancel payment result, {msg = }, {status_code = }")
    return msg, status_code


@app.post('/status/<user_id>/<order_id>')
@payment_status_metric.time()
def payment_status(user_id: str, order_id: str):
    paid = False
    idx = construct_payment_id(user_id, order_id)
    payment = Payment.query.filter_by(id=idx).first()
    if bool(payment):
        paid = payment.paid

    app.logger.debug(f"Order with order id: {order_id} ({user_id = }, paid status: {paid}")
    return {"paid": paid}


@app.route("/metrics")
def metrics():
    data = generate_latest(registry)
    app.logger.debug(f"Metrics, returning: {data}")
    return Response(data, mimetype=CONTENT_TYPE_LATEST)
