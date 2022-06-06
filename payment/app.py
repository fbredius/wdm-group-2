import logging
import os
import uuid
from http import HTTPStatus

from flask import Flask, make_response, jsonify
from flask_sqlalchemy import SQLAlchemy

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


def construct_payment_id(user_id, order_id):
    return user_id + '/' + order_id


@app.post('/create_user')
def create_user():
    """
    Creates a user with 0 credit
    :return: the user's id
    """
    idx = str(uuid.uuid4())
    user = User(idx, 0)
    db.session.add(user)
    db.session.commit()
    return make_response(jsonify({"user_id": idx}), HTTPStatus.OK)


@app.get('/find_user/<user_id>')
def find_user(user_id: str):
    """
    Returns the user information
    :param user_id:
    :return: User { id, credit }
    """
    return User.query.get_or_404(user_id).as_dict()


@app.post('/add_funds/<user_id>/<amount>')
def add_credit(user_id: str, amount: float):
    """
    Adds funds (amount) to the user's account
    :param user_id:
    :param amount:
    :return: true / false
    """
    user = User.query.filter_by(id=user_id).first()
    done = False
    if bool(user):
        user.credit = user.credit + float(amount)
        db.session.add(user)
        db.session.commit()
        done = True

    return make_response(jsonify({"done": done}), HTTPStatus.OK)


@app.post('/pay/<user_id>/<order_id>/<amount>')
def remove_credit(user_id: str, order_id: str, amount: float):
    """
    Subtracts the amount of the order from the user's credit
    Returns failure if credit is not enough
    :param user_id:
    :param order_id:
    :param amount:
    :return:
    """
    user = User.query.get_or_404(user_id)
    app.logger.debug(f"removing credit from user: {user.as_dict() =}")
    amount = float(amount)
    if user.credit < amount:
        app.logger.debug(f"{user.credit = } is smaller than {amount =} of credit to remove")
        response = make_response("Not enough credit", HTTPStatus.FORBIDDEN)
    else:
        user.credit = user.credit - amount
        db.session.add(user)
        idx = construct_payment_id(user_id, order_id)
        payment = Payment(idx, user_id, order_id, amount, True)
        db.session.add(payment)
        app.logger.debug(f"succesfully removed {amount} credit from user with id {user_id}")
        db.session.commit()
        response = make_response("Credit removed", HTTPStatus.OK)

    app.logger.debug(f"Remove credit result, {response}")
    return response


@app.post('/cancel/<user_id>/<order_id>')
def cancel_payment(user_id: str, order_id: str):
    """
    Cancels the payment made by a specific user for a specific order
    :param user_id:
    :param order_id:
    :return:
    """
    user = User.query.get_or_404(user_id)
    idx = construct_payment_id(user_id, order_id)
    payment = Payment.query.get_or_404(idx)
    payment.paid = False
    user.credit = user.credit + payment.amount
    db.session.add(user)
    db.session.commit()

    response = make_response("payment reset", HTTPStatus.OK)

    app.logger.debug(f"Cancel payment result, {response}")
    return response


@app.post('/status/<user_id>/<order_id>')
def payment_status(user_id: str, order_id: str):
    """
    Returns the status of the payment
    :param user_id:
    :param order_id:
    :return: true / false
    """
    paid = False
    idx = construct_payment_id(user_id, order_id)
    payment = Payment.query.filter_by(id=idx).first()
    if bool(payment):
        paid = payment.paid

    app.logger.debug(f"Order with order id: {order_id} ({user_id = }, paid status: {paid}")
    return make_response(jsonify({"paid": paid}), HTTPStatus.OK)
