---
title: Kubernetes basics
category: reliability
tags: [kubernetes, k8s, pods, deployments, services, ingress, configmap, hpa, probes, orchestration]
use_cases:
  - deploy a containerized API to Kubernetes with health checks and resource limits
  - expose a service inside and outside the cluster with a Service and Ingress
  - understand why a pod is stuck in CrashLoopBackOff or Pending
  - configure autoscaling and zero-downtime rollouts on Kubernetes
  - decide whether a small project really needs Kubernetes
status: draft
last_verified: 2026-10-10
sources:
  - https://kubernetes.io/docs/concepts/overview/
  - https://kubernetes.io/docs/concepts/workloads/
  - https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/
  - https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/
  - https://kubernetes.io/docs/tasks/run-application/horizontal-pod-autoscale/
  - Kubernetes Up and Running (Burns, Beda, Hightower, Evenson), O'Reilly
---

# Kubernetes basics

## Summary
Kubernetes is a declarative container orchestrator: you describe desired state (N replicas of this image, exposed on this port) and controllers continuously reconcile reality toward it, scheduling, restarting, scaling and rolling out workloads across a cluster of nodes. It gives portability and self-healing at the price of real operational and conceptual complexity.

## Key concepts
- **Pod**: the smallest deployable unit; one or more containers sharing network and volumes. Pods are ephemeral; never rely on a pod's IP or lifetime.
- **Deployment / ReplicaSet**: keeps N identical stateless pods running and performs rolling updates and rollbacks.
- **StatefulSet**: stable identity and storage per replica, for databases and clustered systems. **DaemonSet**: one pod per node (log agents). **Job / CronJob**: run-to-completion and scheduled work.
- **Service**: stable virtual IP and DNS name load balancing across matching pods (selected by labels). Types: ClusterIP (internal), NodePort, LoadBalancer.
- **Ingress / Gateway API**: HTTP routing from outside the cluster to Services; needs an ingress controller.
- **ConfigMap and Secret**: inject configuration and credentials as env vars or files. Secrets are base64-encoded, not encrypted by default (see [[secrets-management]]).
- **Requests and limits**: requests drive scheduling (guaranteed minimum); limits cap usage (CPU throttled, memory over limit gets OOM-killed).
- **Probes**: startup, liveness (restart if stuck), readiness (receive traffic or not).
- **Namespace**: logical partition for names, quotas and RBAC.
- **Control plane**: API server, etcd (state), scheduler, controller manager; kubelet on each node runs pods.
- **HPA**: Horizontal Pod Autoscaler adjusts replica count from metrics (see [[capacity-planning-and-autoscaling]]).

## When to use / scenarios
- Many services needing automated placement, self-healing, rolling updates and service discovery.
- Multi-team platforms where a standard deploy API (and ecosystem: Helm, operators, GitOps) is valuable.
- Burst or elastic workloads that benefit from cluster autoscaling.
- When NOT to: a handful of services on one or two machines (Compose, systemd or a managed PaaS/serverless platform is cheaper to run; see [[serverless-architecture]]), small teams with no capacity to operate or pay for a managed cluster, or a single monolith that deploys fine today. "We might scale" is not a reason.

## How it works / example

```
kubectl apply -> API server (stores desired state in etcd)
   -> scheduler assigns pod to node -> kubelet starts containers
   -> controllers watch and reconcile (replace dead pods, scale, roll out)
 client -> Ingress -> Service (label selector) -> ready Pods
```

A complete minimal workload: Deployment, Service, and HPA.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata: {name: orders-api, labels: {app: orders-api}}
spec:
  replicas: 3
  selector: {matchLabels: {app: orders-api}}
  strategy:
    type: RollingUpdate
    rollingUpdate: {maxSurge: 1, maxUnavailable: 0}
  template:
    metadata: {labels: {app: orders-api}}
    spec:
      containers:
        - name: app
          image: registry.example.com/orders-api:1.8.2
          ports: [{containerPort: 8080}]
          envFrom: [{configMapRef: {name: orders-config}}]
          env:
            - name: DB_PASSWORD
              valueFrom: {secretKeyRef: {name: orders-db, key: password}}
          resources:
            requests: {cpu: 200m, memory: 256Mi}
            limits: {memory: 512Mi}
          startupProbe:   {httpGet: {path: /healthz, port: 8080}, failureThreshold: 30, periodSeconds: 2}
          readinessProbe: {httpGet: {path: /readyz,  port: 8080}, periodSeconds: 5}
          livenessProbe:  {httpGet: {path: /healthz, port: 8080}, periodSeconds: 10}
---
apiVersion: v1
kind: Service
metadata: {name: orders-api}
spec:
  selector: {app: orders-api}
  ports: [{port: 80, targetPort: 8080}]
---
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata: {name: orders-api}
spec:
  scaleTargetRef: {apiVersion: apps/v1, kind: Deployment, name: orders-api}
  minReplicas: 3
  maxReplicas: 20
  metrics:
    - type: Resource
      resource: {name: cpu, target: {type: Utilization, averageUtilization: 60}}
```

Debugging flow that solves most problems:
1. `kubectl get pods` - status? Pending (scheduling: insufficient resources, taints, unbound PVC), ImagePullBackOff (image name, registry auth), CrashLoopBackOff (app crashes on start), OOMKilled (memory limit).
2. `kubectl describe pod <p>` - events at the bottom explain scheduling, probe and pull failures.
3. `kubectl logs <p> [--previous]` - the crashed container's last output.
4. `kubectl get endpoints <svc>` - empty means the selector matches no ready pods.
5. `kubectl exec -it <p> -- sh` or an ephemeral debug container for in-pod checks.

Other essentials: keep manifests in Git and apply via a pipeline or GitOps controller (see [[infrastructure-as-code]]); use `PodDisruptionBudget` to keep minimum replicas during node drains; spread replicas across zones with topology spread constraints; set NetworkPolicies and RBAC least privilege.

## Trade-offs
- **Managed (EKS/GKE/AKS) vs self-managed**: managed removes control-plane toil; self-managed gives control at large operational cost. Default to managed.
- **Plain YAML vs Helm vs Kustomize**: plain YAML is transparent but repetitive; Kustomize overlays per environment without templating; Helm packages third-party software well but templates can become unreadable.
- **One big cluster vs many**: shared clusters pack better but share blast radius and noisy neighbors; separate clusters isolate environments and teams at higher cost.
- **Memory limit equals request vs overcommit**: equal values make pods predictable (Guaranteed QoS) but waste capacity; overcommit packs tighter but risks eviction.
- **CPU limits**: they cause throttling even when the node is idle; many teams set CPU requests only. Decide deliberately.
- **Operators/CRDs** automate stateful systems but add another thing to upgrade and trust.

## Gotchas
- No readiness probe means traffic hits pods before they are ready; a liveness probe that checks dependencies can restart the whole fleet when the database blips.
- No resource requests means the scheduler overpacks nodes and HPA CPU percentages are meaningless (they are relative to requests).
- `latest` tag plus default pull policy gives unpredictable versions; pin tags or digests.
- Secrets in Git are secrets leaked; use sealed/external secret mechanisms.
- Pods get SIGTERM then SIGKILL after `terminationGracePeriodSeconds`; handle shutdown, and note that endpoint removal races with SIGTERM (a short preStop sleep helps).
- Service DNS and `ndots` defaults can add latency to external lookups; test resolution behavior if you see slow outbound calls.
- Stateful workloads with PersistentVolumes are zone-bound; a pod cannot move to another zone with its disk.
- Cluster upgrades lag: API versions get removed; track deprecations before upgrading.
- Cost surprises from unbounded autoscaling, idle load balancers and over-requested resources; set max replicas and review utilization.

## Related
- [[containers-and-docker]] - the images Kubernetes runs.
- [[deployment-strategies]] - rolling updates, canaries and rollbacks on top of Deployments.
- [[capacity-planning-and-autoscaling]] - HPA, VPA and cluster autoscaling in depth.
- [[infrastructure-as-code]] - managing clusters and manifests declaratively.
- [[api-gateway-and-service-mesh]] - ingress, gateways and meshes layered on Kubernetes.
- [[twelve-factor-app]] - app conventions that fit the platform.
- [[health-checks-and-graceful-shutdown]] - designing liveness, readiness and startup probes and draining on SIGTERM.

## References
- Kubernetes concepts: https://kubernetes.io/docs/concepts/overview/
- Probes configuration: https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/
- Resource management for containers: https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/
- Horizontal Pod Autoscaling: https://kubernetes.io/docs/tasks/run-application/horizontal-pod-autoscale/
- Burns, Beda, Hightower, Evenson, Kubernetes Up and Running (O'Reilly).
