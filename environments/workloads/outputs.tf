
output "namespace" {
  description = "Kubernetes namespace"
  value       = kubernetes_namespace_v1.nginx.metadata[0].name
}

output "deployment_name" {
  description = "NGINX deployment name"
  value       = kubernetes_deployment_v1.nginx.metadata[0].name
}

output "service_name" {
  description = "NGINX service name"
  value       = kubernetes_service_v1.nginx.metadata[0].name
}

output "service_endpoint" {
  description = "Internal Kubernetes DNS endpoint"
  value       = "http://nginx.nginx.svc.cluster.local"
}

output "replicas" {
  description = "Desired NGINX replicas"
  value       = kubernetes_deployment_v1.nginx.spec[0].replicas
}
