#!/usr/bin/env bash

helm repo add bitnami https://charts.bitnami.com/bitnami
helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts

helm repo update

helm install promstack prometheus-community/kube-prometheus-stack
helm install -f helm-config/nginx-helm-values.yaml nginx ingress-nginx/ingress-nginx
