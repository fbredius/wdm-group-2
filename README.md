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
  * RabbitMQ Queues
  * RabbitMQ Orchestrator
  * Order Service
  * Payment Service
  * Stock Service
  * Order Postgres
  * Payment Postgres
  * Stock Postgres
    
* `order`
    Folder containing the order application logic, the message producer and dockerfile. 
    
* `payment`
    Folder containing the payment application logic, the message consumer and dockerfile. 

* `stock`
    Folder containing the stock application logic, the message consumer and dockerfile. 

* `test`
    Folder containing some basic correctness tests for the entire system. (Feel free to enhance them)

### Deployment types:

#### docker-compose (local development)

After coding the REST endpoint logic run `docker-compose up --build` in the base folder to test if your logic is correct
(you can use the provided tests in the `\test` folder and change them as you wish). 

***Requirements:*** You need to have docker and docker-compose installed on your machine.

#### minikube (local k8s cluster)

This setup is for local k8s testing to see if your k8s config works before deploying to the cloud. 
First deploy your database using helm by running the `deploy-charts-minicube.sh` file (in this example the DB is Redis 
but you can find any database you want in https://artifacthub.io/ and adapt the script). Then adapt the k8s configuration files in the
`\k8s` folder to mach your system and then run `kubectl apply -f .` in the k8s folder. 

Addition Pepijn: Alternatively you can use the scripts in `\utils`. Running `deploy-and-apply-minikube` from `\utils` should
1. (re)build all services (as defined in `docker-compose.yml`) using the minikube docker-env.
2. run `deploy-charts-minikube`
3. run `kubectl apply -f ./k8s/` to run all services.
Running this script (in git bash) works for me to deploy everything locally.

***Requirements:*** You need to have minikube (with ingress enabled) and helm installed on your machine.

#### kubernetes cluster (managed k8s cluster in the cloud)

> Installation
1. Install the gcloud CLI from [here](https://cloud.google.com/sdk/docs/install).
___
2. Open a terminal and run `gcloud init`.
___
3. Authorize the console to your GCP`gcloud
   - `gcloud auth login`
   - opens window: login
___
4. Run `gcloud config set project versatile-field-350813` in your terminal. This sets our WDM project on Google Cloud for your current configuration of the CLI.
___
5. Run `gcloud container clusters get-credentials web-scale-cluster --zone europe-west4-a --project versatile-field-350813` in your terminal.
This updates **kubeconfig** to get **kubectl** to use a GKE cluster.
___
6. Navigate to the project root with cloud shell (`cd C:\User\.....\wdm-group-2`)
___
7. `echo %USERNAME% && echo %USERDOMAIN%` (No idea what this does)
___
8. The Docker security group is called docker-users. To add a user from the Administrator command prompt, run the following command:
`net localgroup docker-users <DOMAIN>\<USERNAME> /add`.
    - Where *DOMAIN* is your Windows domain.
    - *USERNAME* is your user name.
    - On Linux, run: `sudo usermod -a -G docker ${USER}`

___

9. Run `gcloud auth configure-docker europe-west4-docker.pkg.dev`. This will register `gcloud` as the credential helper
   for all Google-supported Docker registries.
   See [here](https://cloud.google.com/sdk/gcloud/reference/auth/configure-docker) for more info.

___
> Updating the existing cluster

10. How to push a container to the registry:

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