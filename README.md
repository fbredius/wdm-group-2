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
9. Run `gcloud auth configure-docker europe-west4-docker.pkg.dev`. This will register `gcloud` as the credential helper for all Google-supported Docker registries. See [here](https://cloud.google.com/sdk/gcloud/reference/auth/configure-docker) for more info.
___
> Updating the existing cluster
10. How to push a container to the registry:

    1. Tag the container `europe-west4-docker.pkg.dev/versatile-field-350813/web-scale-repository/<image_name>:<some_optional_tag>`
       - Example: `docker tag stock:latest europe-west4-docker.pkg.dev/versatile-field-350813/web-scale-repository/stock:latest`
    2. Push the container `docker push europe-west4-docker.pkg.dev/versatile-field-350813/web-scale-repository/<image_name>:<some_optional_tag>`
       - Example: `docker push europe-west4-docker.pkg.dev/versatile-field-350813/web-scale-repository/stock:latest`
    3. Or by using `docker-compose`. This can be done by first building (appropriate tags should already be set in the .yml) and then pushing
       - `docker-compose build`
       - `docker-compose push`
    
NOT TESTED, but you should be able to init a cluster with some nodes to test deploying stuff with:

```
gcloud beta container --project "versatile-field-350813" node-pools create "pool-1" --cluster "web-scale-cluster" --zone "europe-west4-a" --node-version "1.21.11-gke.900" --machine-type "e2-standard-4" --image-type "COS_CONTAINERD" --disk-type "pd-standard" --disk-size "100" --metadata disable-legacy-endpoints=true --scopes "https://www.googleapis.com/auth/devstorage.read_only","https://www.googleapis.com/auth/logging.write","https://www.googleapis.com/auth/monitoring","https://www.googleapis.com/auth/servicecontrol","https://www.googleapis.com/auth/service.management.readonly","https://www.googleapis.com/auth/trace.append" --num-nodes "1" --enable-autoupgrade --enable-autorepair --max-surge-upgrade 0 --max-unavailable-upgrade 2 --max-pods-per-node "110"
```

(run in console), DONT FORGET TO DELETE THE NODE POOL AFTER to prevent cost

Similarly to the `minikube` deployment but run the `deploy-charts-cluster.sh` in the helm step to also install an
ingress to the cluster.

***Requirements:*** You need to have access to kubectl of a k8s cluster.

## Kubernetes commands storage:

- Deploy changes made to code: <br>
  `docker-compose build && docker-compose push && kubectl replace --force -f ./k8s/`
- Resizing cluster (can take a while) <br>
  `gcloud container clusters resize web-scale-cluster --region europe-west4-a --num-nodes <num_nodes> `