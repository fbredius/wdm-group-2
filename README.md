# Web-scale Data Management Project Template

Basic project structure with Python's Flask and Redis. 
**You are free to use any web framework in any language and any database you like for this project.**

### Project structure

* `env`
    Folder containing the Redis env variables for the docker-compose deployment
    
* `helm-config` 
   Helm chart values for Redis and ingress-nginx
        
* `k8s`
    Folder containing the kubernetes deployments, apps and services for the ingress, order, payment and stock services.
    
* `order`
    Folder containing the order application logic and dockerfile. 
    
* `payment`
    Folder containing the payment application logic and dockerfile. 

* `stock`
    Folder containing the stock application logic and dockerfile. 

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

- Install google cloud console, open the cloud console
- authorize the console to your GCP`gcloud
   - `gcloud auth login`
   - opens window: login
- `gcloud config set project versatile-field-350813`
- `gcloud container clusters get-credentials web-scale-cluster --zone europe-west4-a --project versatile-field-350813`
- Navigate to project root with cloud shell (`cd C:\User\.....\wdm-group-2`)
- `echo %USERNAME% && echo %USERDOMAIN%`
   `net localgroup docker-users <DOMAIN>\<USERNAME> /add`
- `gcloud auth configure-docker europe-west4-docker.pkg.dev`
- Pushing a container to the registry is now done by
  - Tagging the container with tag `europe-west4-docker.pkg.dev/versatile-field-350813/web-scale-repository/<image_name>:<some_optional_tag>`
    - example: docker tag stock:latest europe-west4-docker.pkg.dev/versatile-field-350813/web-scale-repository/stock:latest
  - Pushing the container to the registry
    - `docker push europe-west4-docker.pkg.dev/versatile-field-350813/web-scale-repository/stock:latest`
  - using docker-compose this can be done by first building (appropriate tags should already be set in the .yml) and then pushing
    - `docker-compose build`
    - `docker-compose push`
    
Similarly to the `minikube` deployment but run the `deploy-charts-cluster.sh` in the helm step to also install an ingress to the cluster.

***Requirements:*** You need to have access to kubectl of a k8s cluster.
