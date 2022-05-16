#!/usr/bin/env sh
./build-containers-minikube.sh
../deploy-charts-minikube.sh
kubectl apply -f ../k8s/
sleep 10
kubectl get pods