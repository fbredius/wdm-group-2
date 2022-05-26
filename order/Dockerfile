FROM python:3.10-slim

WORKDIR /home/flask-app

COPY ./requirements.txt .

RUN apt-get install psycopg2 libpq-dev python-dev
RUN pip install -r requirements.txt
RUN apt-get -y update; apt-get -y install curl

COPY . .

EXPOSE 5000