resource "kubernetes_namespace_v1" "nginx" {
  metadata {
    name = "nginx"
  }
}

resource "kubernetes_deployment_v1" "nginx" {
  metadata {
    name      = "nginx"
    namespace = kubernetes_namespace_v1.nginx.metadata[0].name

    labels = {
      app = "nginx"
    }
  }

  spec {
    replicas = 4

    selector {
      match_labels = {
        app = "nginx"
      }
    }

    template {
      metadata {
        labels = {
          app = "nginx"
        }
      }

      spec {
        container {
          name  = "nginx"
          image = "nginx:stable"

          port {
            name           = "http"
            container_port = 80
            protocol       = "TCP"
          }

          resources {
            requests = {
              cpu    = "100m"
              memory = "128Mi"
            }

            limits = {
              cpu    = "500m"
              memory = "256Mi"
            }
          }

          readiness_probe {
            http_get {
              path = "/"
              port = 80
            }

            initial_delay_seconds = 5
            period_seconds        = 5
          }

          liveness_probe {
            http_get {
              path = "/"
              port = 80
            }

            initial_delay_seconds = 10
            period_seconds        = 10
          }
        }
      }
    }
  }
}

resource "kubernetes_service_v1" "nginx" {
  metadata {
    name      = "nginx"
    namespace = kubernetes_namespace_v1.nginx.metadata[0].name
  }

  spec {
    selector = {
      app = "nginx"
    }

    port {
      name        = "http"
      port        = 80
      target_port = 80
      node_port   = 30080
      protocol    = "TCP"
    }

    type = "NodePort"
  }
}

# Added Ingress Controller Routing
resource "kubernetes_ingress_v1" "nginx" {
  metadata {
    name      = "nginx-ingress"
    namespace = kubernetes_namespace_v1.nginx.metadata[0].name
    annotations = {
      "nginx.ingress.kubernetes.io/rewrite-target" = "/"
    }
  }

  spec {
    ingress_class_name = "nginx"

    rule {
      host = "nginx.local"
      http {
        path {
          path      = "/"
          path_type = "Prefix"

          backend {
            service {
              name = kubernetes_service_v1.nginx.metadata[0].name
              port {
                number = 80
              }
            }
          }
        }
      }
    }
  }
}