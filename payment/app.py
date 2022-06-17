import logging
import os
import shutil
import uuid
from http import HTTPStatus

from flask_sqlalchemy import SQLAlchemy
from prometheus_async.aio import time
from prometheus_client import CollectorRegistry, multiprocess, Summary, CONTENT_TYPE_LATEST, generate_latest
from quart import Quart, make_response, jsonify, Response
from sqlalchemy import CheckConstraint
from sqlalchemy.exc import ProgrammingError

app_name = 'payment-service'
app = Quart(app_name)

logging.basicConfig()
logging.getLogger('sqlalchemy.engine').setLevel(os.environ.get('DB_LOG_LEVEL', logging.WARNING))
logging.getLogger(app_name).setLevel(os.environ.get('LOG_LEVEL', 'DEBUG'))
logger = logging.getLogger(app_name)
logger.warning(f"LOG_LEVEL: {os.environ.get('LOG_LEVEL')}")

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


class User(db.Model):
    __tablename__ = 'users'

    id = db.Column(db.String(), primary_key=True)
    credit = db.Column(db.Float, unique=False, nullable=False)
    __table_args__ = (
        CheckConstraint(credit >= 0, name='check_credit_positive'), {}
    )

    def __init__(self, id, credit):
        """
        User object containing all relevant fields.
        :param id: ID of User
        :param credit: Credit of User
        """
        self.id = id
        self.credit = credit

    def as_dict(self):
        """
        Convert object to a dictionary.
        :return: dictionary of User object
        """
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
        """
        Payment object containing all relevant fields.
        :param id: ID of Payment
        :param user_id: User doing the Payment
        :param order_id: Order corresponding to Payment
        :param amount: Price of the payment
        :param paid: Status of payment
        """
        self.id = id
        self.user_id = user_id
        self.order_id = order_id
        self.amount = amount
        self.paid = paid

    def as_dict(self):
        """
        Convert object to a dictionary.
        :return: dictionary of Payment object
        """
        dct = self.__dict__.copy()
        dct.pop('_sa_instance_state', None)
        return dct


db.create_all()
db.session.commit()

create_user_metric = Summary("create_user", "Summary of /create_user endpoint")
find_user_metric = Summary("find_user", "Summary of /find_user/<user_id>")
add_credit_metric = Summary("add_credit", "Summary of /add_funds/<user_id>/<amount>")
pay_metric = Summary("pay", "Summary of /pay/<user_id>/<order_id>/<amount>")
cancel_metric = Summary("cancel", "/cancel/<user_id>/<order_id>")
payment_status_metric = Summary("payment_status", "/status/<user_id>/<order_id>")
cancel_payment_metric = Summary("db_cancel_payment", "cancel payment")


def construct_payment_id(user_id, order_id):
    return user_id + '/' + order_id


@app.post('/create_user')
@time(create_user_metric)
async def create_user():
    """
    Creates a user with 0 credit
    :return: the user's id
    """
    user_id = str(uuid.uuid4())
    user = User(user_id, 0)

    db.session.add(user)
    db.session.commit()
    db.session.close()

    return await make_response(jsonify({"user_id": user_id}), HTTPStatus.OK)


@app.get('/find_user/<user_id>')
@time(find_user_metric)
async def find_user(user_id: str):
    """
    Returns the user information
    :param user_id: The user to get information from
    :return: User { id, credit }
    """
    return User.query.get_or_404(user_id).as_dict()


@app.post('/add_funds/<user_id>/<amount>')
@time(add_credit_metric)
async def add_credit(user_id: str, amount: float):
    """
    Adds funds (amount) to the user's account
    :param user_id: The user to add funds to
    :param amount: The amount of funds to be added
    :return: true / false
    """
    user = User.query.filter_by(id=user_id).first()
    done = False
    if bool(user):
        user.credit = user.credit + float(amount)

        db.session.add(user)
        db.session.commit()
        db.session.close()

        done = True

    return await make_response(jsonify({"done": done}), HTTPStatus.OK)


@app.post('/pay/<user_id>/<order_id>/<amount>')
@time(pay_metric)
async def pay(user_id: str, order_id: str, amount: float):
    return await remove_credit(amount, order_id, user_id)


async def remove_credit(amount, order_id, user_id):
    """
    Subtracts the amount of the order from the user's credit
    Returns failure if credit is not enough
    :param amount: The amount to be subtracted
    :param user_id: The user id to subtract credit from
    :param order_id: The order id to which the amount corresponds
    :return:
    """
    user = User.query.get_or_404(user_id)
    logger.debug(f"removing credit from user: {user.as_dict() =}")
    amount = float(amount)

    if user.credit < amount:
        logger.debug(f"Remove credit result no success, {user.credit = } is smaller than {amount =}")
        return await make_response("Not enough credit", HTTPStatus.FORBIDDEN)

    # Update credit
    user.credit = user.credit - amount
    db.session.add(user)

    # Construct payment
    payment_id = construct_payment_id(user_id, order_id)
    payment = Payment(payment_id, user_id, order_id, amount, True)

    db.session.add(payment)
    db.session.commit()
    db.session.close()

    logger.debug(f"Remove credit result success")
    return await make_response("Credit removed", HTTPStatus.OK)


@app.post('/cancel/<user_id>/<order_id>')
@time(cancel_metric)
async def cancel(user_id: str, order_id: str):
    return await cancel_payment(order_id, user_id)


@time(cancel_payment_metric)
async def cancel_payment(order_id, user_id):
    """
    Cancels the payment made by a specific user for a specific order
    :param user_id: The user id to cancel the payment for
    :param order_id: The order id to cancel the payment for
    :return:
    """
    logger.debug(f"Cancelling payment for order: {order_id}")
    user = User.query.get_or_404(user_id)

    # Set paid to false
    payment_id = construct_payment_id(user_id, order_id)
    payment = Payment.query.get_or_404(payment_id)
    payment.paid = False
    db.session.add(payment)

    # Add credit
    user.credit = user.credit + payment.amount
    db.session.add(user)

    db.session.commit()
    db.session.close()

    logger.debug(f"Cancelled payment for order: {order_id}, db session closed and committed")
    return await make_response("payment reset", HTTPStatus.OK)


@app.post('/status/<user_id>/<order_id>')
@time(payment_status_metric)
async def payment_status(user_id: str, order_id: str):
    """
    Returns the status of the payment
    :param user_id: The user id to get the status for
    :param order_id: The order id to get the status for
    :return: true / false
    """
    paid = False
    payment_id = construct_payment_id(user_id, order_id)
    payment = Payment.query.filter_by(id=payment_id).first()

    if bool(payment):
        paid = payment.paid

    logger.debug(f"Order with order id: {order_id} ({user_id = }, paid status: {paid}")
    return await make_response(jsonify({"paid": paid}), HTTPStatus.OK)


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
