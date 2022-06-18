#!/usr/bin/env bash
# First install helm charts
echo "Updating helm repos and installing charts"
sh deploy-charts-cluster.sh no-promstack

echo "Launching pods"
kubectl apply -f k8s/kubegres/base-kubegres-configy.yaml
kubectl apply -f k8s/kubegres/custom-postgres-config.yaml
sleep 5
kubectl apply -f k8s/kubegres/kubegres.yml
kubectl apply -f k8s/rabbitmq/cluster-operator.yml
sleep 5
kubectl apply -f k8s/rabbitmq/rabbitmq.yaml
echo "Waiting for kubegres to be ready"
kubectl wait --for=condition=available deployment -l control-plane=controller-manager -n kubegres-system

echo "Launching postgres clusters"
kubectl apply -f k8s/database-deployments
echo "Waiting for postgres clusters"
sleep 10
kubectl wait --for=condition=ready pod -l app=stock-postgres-service
kubectl wait --for=condition=ready pod -l app=user-postgres-service
kubectl wait --for=condition=ready pod -l app=order-postgres-service

echo "Launching services"
kubectl apply -f k8s/
echo "Waiting for services"
kubectl wait --for=condition=available deployment -l type=app-deployment

echo "Pods launched, cluster ready"

