# Kubernetes Configuration for QFieldCloud Worker Wrapper

This document outlines the configuration needed to deploy QFieldCloud with Kubernetes-compatible worker wrapper.

## Environment Variables

Add these environment variables to your Django settings:

```python
# Kubernetes namespace for worker jobs
QFIELDCLOUD_K8S_NAMESPACE = os.environ.get("QFIELDCLOUD_K8S_NAMESPACE", "default")

# Kubernetes service account for worker jobs (must have permissions to create/delete jobs)
QFIELDCLOUD_K8S_SERVICE_ACCOUNT = os.environ.get("QFIELDCLOUD_K8S_SERVICE_ACCOUNT", "qfieldcloud-worker")
```

## Required Kubernetes Resources

### 1. Service Account and RBAC

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: qfieldcloud-worker
  namespace: default

---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  namespace: default
  name: qfieldcloud-worker-role
rules:
- apiGroups: ["batch"]
  resources: ["jobs"]
  verbs: ["create", "delete", "get", "list", "watch"]
- apiGroups: [""]
  resources: ["pods"]
  verbs: ["get", "list", "watch"]
- apiGroups: [""]
  resources: ["pods/log"]
  verbs: ["get"]

---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: qfieldcloud-worker-binding
  namespace: default
subjects:
- kind: ServiceAccount
  name: qfieldcloud-worker
  namespace: default
roleRef:
  kind: Role
  name: qfieldcloud-worker-role
  apiGroup: rbac.authorization.k8s.io
```

### 2. Persistent Volume for Transformation Grids (Optional)

If using transformation grids, create a PVC:

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: transformation-grids
  namespace: default
spec:
  accessModes:
    - ReadOnlyMany
  resources:
    requests:
      storage: 1Gi
  # Configure based on your storage class
  # storageClassName: your-storage-class
```

### 3. ConfigMap for Worker Configuration (Optional)

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: qfieldcloud-worker-config
  namespace: default
data:
  worker_timeout: "600"
  memory_limit: "1000Mi"
  cpu_shares: "512"
```

## Migration Steps

### 1. Install Kubernetes Dependencies

Add to your requirements:

```bash
pip install kubernetes>=29.0.0
```

### 2. Update Import Statements

Replace Docker-based imports:

```python
# OLD: Docker-based wrapper
from worker_wrapper.wrapper import JobRun, PackageJobRun, ApplyDeltaJobRun, ProcessProjectfileJobRun

# NEW: Kubernetes-based wrapper  
from worker_wrapper.k8s_wrapper import JobRun, PackageJobRun, ApplyDeltaJobRun, ProcessProjectfileJobRun
```

### 3. Update Volume Configuration

The transformation grids volume configuration changes:

**Docker (old):**
```python
QFIELDCLOUD_TRANSFORMATION_GRIDS_VOLUME_NAME = "transformation_grids_volume"
```

**Kubernetes (new):**
```python
# Name of the PVC containing transformation grids
QFIELDCLOUD_TRANSFORMATION_GRIDS_VOLUME_NAME = "transformation-grids"
```

### 4. Network Configuration

Docker networking is no longer needed:

```python
# Remove this setting (not used in K8s)
# QFIELDCLOUD_DEFAULT_NETWORK = "qfieldcloud_network"
```

### 5. Deploy with Kubernetes Configuration

Ensure your main application deployment includes:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: qfieldcloud-app
spec:
  template:
    spec:
      serviceAccountName: qfieldcloud-worker  # Important!
      containers:
      - name: app
        image: your-qfieldcloud-image
        env:
        - name: QFIELDCLOUD_K8S_NAMESPACE
          value: "default"
        - name: QFIELDCLOUD_K8S_SERVICE_ACCOUNT
          value: "qfieldcloud-worker"
        # ... other environment variables
```

## Benefits of Kubernetes Migration

1. **No Docker Socket Dependency**: Eliminates security risks of mounting Docker socket
2. **Better Resource Management**: Kubernetes handles resource allocation and limits
3. **Auto-scaling**: Kubernetes can auto-scale worker nodes based on demand
4. **Improved Logging**: Centralized logging through Kubernetes
5. **Better Monitoring**: Integration with Kubernetes monitoring tools
6. **Security**: Proper RBAC instead of Docker socket access

## Differences from Docker Version

1. **Job Naming**: Jobs use DNS-compliant names (`qfc-worker-{job-id}`)
2. **Volume Mounts**: Uses Kubernetes volume types (PVC, ConfigMap, HostPath)
3. **Resource Limits**: Uses Kubernetes resource specifications
4. **Networking**: No custom networks needed (uses cluster networking)
5. **Cleanup**: Automatic cleanup through Kubernetes job lifecycle

## Troubleshooting

### Common Issues

1. **Permission Errors**: Ensure service account has proper RBAC permissions
2. **Volume Mount Issues**: Check PVC is in the same namespace and accessible
3. **Image Pull Errors**: Verify QGIS image is accessible from worker nodes
4. **Timeout Issues**: Adjust `WORKER_TIMEOUT_S` configuration

### Debugging

Check job status:
```bash
kubectl get jobs -l app=dev-worker
kubectl describe job qfc-worker-{job-id}
kubectl logs job/qfc-worker-{job-id}
```