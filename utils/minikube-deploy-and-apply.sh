#!/usr/bin/env sh
./minikube-build-and-push-containers.sh
../deploy-charts-minikube.sh
kubectl apply -f ../k8s/
sleep 10
minikube tunnel
kubectl get pods