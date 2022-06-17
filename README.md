# Web-scale Data Management Project Template

Project implementation, deployment scripts and presentation for **Group 2** for the IN4331 Web-Scale Data Management course.

## Team

| Student Name        | Student Number |
|---------------------|----------------|
| Bailey Tjiong       | 4474686        |
| Frank Bredius       | 4575377        |
| Jan-Mark Dannenberg | 4889576        |
| Pepijn te Marvelde  | 4886496        |

## Project

### Technologies
* [Aio-Pika](https://aio-pika.readthedocs.io/en/latest/)
* [Docker](https://www.docker.com/)
* [Flask-SQLAlchemy](https://flask-sqlalchemy.palletsprojects.com/en/2.x/)
* [Grafana](https://grafana.com/)
* [Helm](https://helm.sh/)
* [Kubernetes](https://kubernetes.io/)
* [NGINX](https://www.nginx.com/)
* [PostgreSQL](https://www.postgresql.org/)
* [Prometheus](https://prometheus.io/)
* [QUnicorn](https://gunicorn.org/)
* [Quart](https://pgjones.gitlab.io/quart/)
* [RabbitMQ](https://www.rabbitmq.com/)
* [Uvicorn](https://www.uvicorn.org/)

### Structure

* `env`
    Folder containing the PostgreSQL env variables for the docker-compose deployment
    
* `helm-config`
  Helm chart values for Prometheus and ingress-nginx

* `k8s`
  Folder containing the kubernetes deployments, apps and services for the following services:
    * rabbitmq
        * RabbitMQ Orchestrator
    * database-deployments/
        * Order Postgres
        * Payment Postgres
        * Stock Postgres
    * kubegres
        * postgres cluster
    * Order Service
    * Payment Service
    * Stock Service
    * Payment Queue
    * Stock Queue


* `order`
  Folder containing the order application logic, the message producer and dockerfile.

* `payment`
  Folder containing the payment application logic, the message consumer and dockerfile.

* `stock`
  Folder containing the stock application logic, the message consumer and dockerfile.

* `test`
    Folder containing some basic correctness tests for the entire system.

### How to run

Make sure `kubectl` is pointing at a k8s endpiont.

- Run `deploy-to-cluster.sh`
- Verify everything is up by running `kubectl get pods`

### Architecture

In this project we have created a microservice architecture using the SAGA Pattern, see images. This architecture
consists of three different services: stock-, payment-, and order service. These services use PostgreSQL to store data
and RabbitMQ to communicate with each other in an event-driven manner.

![Architecture of Project with Technologies used](/assets/architecture.png)
**Image 1** Project Architecture

![SAGA Pattern](/assets/saga.png)
**Image 2**  SAGA Pattern

### Presentation

For more information regarding the project, see the presentation document in the `assets` folder.