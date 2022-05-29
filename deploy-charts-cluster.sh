#!/usr/bin/env bash

helm repo add bitnami https://charts.bitnami.com/bitnami
helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx

helm repo update

helm install -f helm-config/nginx-helm-values.yaml nginx ingress-nginx/ingress-nginx
kubectl apply -f https://raw.githubusercontent.com/reactive-tech/kubegres/v1.15/kubegres.yaml
