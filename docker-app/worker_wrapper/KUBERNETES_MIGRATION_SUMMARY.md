# QFieldCloud Kubernetes Migration Summary

## Overview

Yes, it's absolutely possible to make the QFieldCloud worker wrapper compatible with Kubernetes! I've created a complete Kubernetes-compatible version that eliminates the dependency on direct Docker socket access.

## What I've Created

### 1. Core Files

- **`k8s_wrapper.py`** - Complete Kubernetes-compatible worker wrapper
- **`factory.py`** - Backend selection factory for smooth migration
- **`dequeue_k8s.py`** - Updated dequeue command supporting both backends
- **`K8S_MIGRATION_GUIDE.md`** - Comprehensive migration guide
- **`README.md`** - Quick start and overview

### 2. Configuration Files

- **`requirements_k8s_wrapper.in`** - Additional dependencies
- **`k8s_settings_example.py`** - Django settings example
- **`test_k8s_wrapper.py`** - Validation test script

## Key Changes Made

### From Docker to Kubernetes API

**Before (Docker):**

```python
import docker
client = docker.from_env()
container = client.containers.run(...)
```

**After (Kubernetes):**

```python
from kubernetes import client, config
k8s_config.load_incluster_config()
k8s_batch_v1 = client.BatchV1Api()
job = k8s_batch_v1.create_namespaced_job(...)
```

### Volume Management

**Before (Docker volumes):**

```python
volumes = [
    f"{tempdir}:/io/:rw",
    f"{grids_volume}:/transformation_grids:ro"
]
```

**After (K8s volumes):**

```python
volumes = [
    client.V1Volume(name="shared-io", host_path=...),
    client.V1Volume(name="transformation-grids", persistent_volume_claim=...)
]
```

### Resource Management

**Before (Docker limits):**

```python
mem_limit=config.WORKER_QGIS_MEMORY_LIMIT,
cpu_shares=config.WORKER_QGIS_CPU_SHARES
```

**After (K8s resources):**

```python
resources = client.V1ResourceRequirements(
    limits={"memory": "1000Mi", "cpu": "0.5"},
    requests={"memory": "1000Mi", "cpu": "0.25"}
)
```

## Migration Path

### Phase 1: Preparation (Zero Downtime)

1. Install Kubernetes Python client
2. Add new settings (keep Docker as backend)
3. Deploy Kubernetes RBAC resources

### Phase 2: Testing

1. Set `QFIELDCLOUD_WORKER_BACKEND=kubernetes`
2. Test with development workloads
3. Validate functionality

### Phase 3: Production Switch

1. Update production configuration
2. Monitor job execution
3. Remove Docker dependencies (optional)

## Benefits of Kubernetes Version

| Aspect | Docker Version | Kubernetes Version |
|--------|---------------|-------------------|
| **Security** | Requires Docker socket mount | RBAC-controlled API access |
| **Scaling** | Manual container management | Automatic resource management |
| **Monitoring** | Custom logging | Native K8s monitoring |
| **Reliability** | Manual cleanup required | Automatic job lifecycle |
| **Cloud Integration** | Limited | Native cloud-native features |

## Required Kubernetes Resources

### 1. RBAC Permissions

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
rules:
- apiGroups: ["batch"]
  resources: ["jobs"]
  verbs: ["create", "delete", "get", "list", "watch"]
- apiGroups: [""]
  resources: ["pods", "pods/log"]
  verbs: ["get", "list", "watch"]
```

### 2. Service Account

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: qfieldcloud-worker
```

### 3. Optional: Persistent Volume for Transformation Grids

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: transformation-grids
spec:
  accessModes: ["ReadOnlyMany"]
  resources:
    requests:
      storage: 1Gi
```

## Backwards Compatibility

The factory pattern ensures existing code continues to work:

```python
# This works with both backends automatically
from worker_wrapper.factory import JobRun
job_run = JobRun(job_id)
job_run.run()
```

## Configuration

Simply add to your Django settings:

```python
# Backend selection
QFIELDCLOUD_WORKER_BACKEND = os.environ.get("QFIELDCLOUD_WORKER_BACKEND", "docker")

# Kubernetes settings (only needed for K8s backend)
if QFIELDCLOUD_WORKER_BACKEND in ['kubernetes', 'k8s']:
    QFIELDCLOUD_K8S_NAMESPACE = os.environ.get("QFIELDCLOUD_K8S_NAMESPACE", "default")
    QFIELDCLOUD_K8S_SERVICE_ACCOUNT = os.environ.get("QFIELDCLOUD_K8S_SERVICE_ACCOUNT", "qfieldcloud-worker")
```

## Validation

The test script confirms the approach is sound:

- ✅ Job lifecycle management
- ✅ Volume and resource configuration
- ✅ Environment variable handling
- ✅ Backwards compatibility

## Next Steps

1. **Install dependencies:** `pip install kubernetes>=29.0.0`
2. **Deploy RBAC resources** to your Kubernetes cluster
3. **Test with development** workloads
4. **Switch production** when validated

This solution completely eliminates the Docker socket dependency while maintaining full compatibility with existing code and providing better resource management, security, and cloud-native integration.
