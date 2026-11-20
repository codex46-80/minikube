resource "kubernetes_namespace_v1" "argocd" {
  metadata {
    name = "argocd"
  }
  lifecycle {
    prevent_destroy = true
  }
}

resource "helm_release" "argocd" {
  name       = "argocd"
  repository = "https://argoproj.github.io/argo-helm"
  chart      = "argo-cd"
  version    = "7.7.0"
  namespace  = "argocd"
}