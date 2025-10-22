# QFieldCloud Kubernetes Worker Wrapper

This directory contains both the original Docker-based worker wrapper and a new Kubernetes-compatible version.

## Files Overview

- `wrapper.py` - Original Docker-based implementation (requires docker.sock mount)
- `k8s_wrapper.py` - New Kubernetes-compatible implementation
- `factory.py` - Factory pattern for choosing between Docker/K8s backends
- `K8S_MIGRATION_GUIDE.md` - Detailed migration guide
- `k8s_settings_example.py` - Example settings for Kubernetes support

## Quick Start - Kubernetes Migration

### 1. Install Dependencies

Add to your requirements:

```bash
pip install kubernetes>=29.0.0
```

### 2. Update Settings

Add to your `settings.py`:

```python
# Choose worker backend: 'docker' or 'kubernetes'
QFIELDCLOUD_WORKER_BACKEND = os.environ.get("QFIELDCLOUD_WORKER_BACKEND", "docker")

# Kubernetes-specific settings (only needed if using K8s backend)
if QFIELDCLOUD_WORKER_BACKEND in ['kubernetes', 'k8s']:
    QFIELDCLOUD_K8S_NAMESPACE = os.environ.get("QFIELDCLOUD_K8S_NAMESPACE", "default")
    QFIELDCLOUD_K8S_SERVICE_ACCOUNT = os.environ.get("QFIELDCLOUD_K8S_SERVICE_ACCOUNT", "qfieldcloud-worker")
```

### 3. Update Imports (Optional)

For maximum compatibility, use the factory:

```python
# Instead of:
from worker_wrapper.wrapper import JobRun, PackageJobRun

# Use:
from worker_wrapper.factory import JobRun, PackageJobRun
```

Or directly import the K8s version:

```python
from worker_wrapper.k8s_wrapper import JobRun, PackageJobRun
```

### 4. Set Environment Variable

```bash
export QFIELDCLOUD_WORKER_BACKEND=kubernetes
```

### 5. Deploy Kubernetes Resources

Apply the RBAC and service account from `K8S_MIGRATION_GUIDE.md`.

## Key Differences

| Aspect | Docker Version | Kubernetes Version |
|--------|---------------|-------------------|
| **Dependency** | docker.sock mount | Kubernetes API access |
| **Security** | Requires privileged access | RBAC-controlled |
| **Scaling** | Manual container management | Kubernetes job lifecycle |
| **Volumes** | Docker volumes/bind mounts | PVC/ConfigMap/HostPath |
| **Networking** | Docker networks | Kubernetes cluster networking |
| **Cleanup** | Manual container cleanup | Automatic job cleanup |

## Benefits of Kubernetes Version

1. **Security**: No need for Docker socket access
2. **Scalability**: Better resource management and auto-scaling
3. **Monitoring**: Integration with K8s monitoring tools
4. **Reliability**: Kubernetes handles job lifecycle and restarts
5. **Cloud Native**: Better integration with cloud platforms

## Backwards Compatibility

The factory pattern ensures existing code continues to work:

```python
# This works with both Docker and Kubernetes backends
job_run = JobRun(job_id="123")
job_run.run()
```

The backend is chosen automatically based on the `QFIELDCLOUD_WORKER_BACKEND` setting.

## Migration Strategy

1. **Phase 1**: Install dependencies and add settings (backend still 'docker')
2. **Phase 2**: Deploy Kubernetes resources and test with `QFIELDCLOUD_WORKER_BACKEND=kubernetes`
3. **Phase 3**: Switch production to Kubernetes backend
4. **Phase 4**: Remove Docker dependencies (optional)

See `K8S_MIGRATION_GUIDE.md` for detailed migration steps and troubleshooting.
