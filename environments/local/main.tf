terraform {
  required_version = ">= 1.6.0"

  required_providers {
    minikube = {
      source  = "scott-the-programmer/minikube"
      version = "0.8.0"
    }
  }
}

provider "minikube" {
  kubernetes_version = "v1.35.1"
}

resource "minikube_cluster" "local" {
  cluster_name = "kubernetes-lab"
  
  # Cluster configuration
  driver            = "docker"
  nodes             = 1
  cpus              = "6"
  memory            = "12g"
  disk_size         = "60g"
  container_runtime = "containerd"

  # Prevent interactive prompts during Terraform provisioning
  interactive = false

  # Essential Kubernetes addons
  addons = [
    "default-storageclass",
    "storage-provisioner",
    "metrics-server",
    "dashboard"
  ]

  # Wait for cluster components to become ready
  wait         = ["all"]
  wait_timeout = 30
}