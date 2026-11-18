
output "cluster_name" {
  description = "Minikube cluster name"
  value       = minikube_cluster.local.cluster_name
}

output "cluster_endpoint" {
  description = "Kubernetes API endpoint"
  value       = minikube_cluster.local.host
}

output "cluster_id" {
  description = "Minikube cluster resource ID"
  value       = minikube_cluster.local.id
}
