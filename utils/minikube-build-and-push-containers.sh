#!/usr/bin/env sh

minikube status || minikube start
eval $(minikube docker-env --shell bash)
docker-compose build
