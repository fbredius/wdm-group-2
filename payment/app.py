import logging
import os
import uuid

from flask import Flask
from flask_sqlalchemy import SQLAlchemy

app_name = 'payment-service'
app = Flask(app_name)
logging.getLogger(app_name).setLevel(os.environ.get('LOGLEVEL', 'DEBUG'))

DB_URL = 'postgresql+psycopg2://{user}:{pw}@{url}/{db}'\
    .format(user=os.environ['POSTGRES_USER'],
            pw=os.environ['POSTGRES_PASSWORD'],
            url=os.environ['POSTGRES_URL'],
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


def construct_payment_id(user_id, order_id):
    return user_id + '/' + order_id


@app.post('/create_user')
def create_user():
    idx = str(uuid.uuid4())
    user = User(idx, 0)
    db.session.add(user)
    db.session.commit()
    return {"user_id": idx}


@app.get('/find_user/<user_id>')
def find_user(user_id: str):
    return User.query.get_or_404(user_id)


@app.post('/add_funds/<user_id>/<amount>')
def add_credit(user_id: str, amount: int):
    user = User.query.filter_by(id=user_id).first()
    if bool(user):
        user.credit = user.credit + int(amount)
        return {"done": True}
    else:
        return {"done": False}


@app.post('/pay/<user_id>/<order_id>/<amount>')
def remove_credit(user_id: str, order_id: str, amount: int):
    user = User.query.get_or_404(user_id)
    app.logger.debug(f"removing credit from user: {user.__dict__ =}")
    if user.credit < int(amount):
        app.logger.debug(f"{user.credit = } is smaller than {amount =} of credit to remove")
        msg, status_code = "Not enough credit", 403
    else:
        user.credit = user.credit - int(amount)
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
def payment_status(user_id: str, order_id: str):
    paid = False
    idx = construct_payment_id(user_id, order_id)
    payment = Payment.query.filter_by(id=idx).first()
    if bool(payment):
        paid = payment.paid

    app.logger.debug(f"Order with order id: {order_id} ({user_id = }, paid status: {paid}")
    return {"paid": paid}
