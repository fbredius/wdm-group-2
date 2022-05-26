FROM python:3.10-slim

WORKDIR /home/flask-app

COPY ./requirements.txt .

RUN python -m pip install --upgrade pip
RUN apt-get update && apt-get -y install libpq-dev gcc curl
RUN pip install -r requirements.txt

COPY . .

EXPOSE 5000