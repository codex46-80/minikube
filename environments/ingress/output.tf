output "ingress_release_name" {
  description = "The Helm release name for NGINX Ingress"
  value       = helm_release.ingress_nginx.name
}

output "ingress_namespace" {
  description = "The namespace where NGINX Ingress is installed"
  value       = helm_release.ingress_nginx.namespace
}