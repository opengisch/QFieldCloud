"""
Additional settings for Kubernetes worker wrapper support

Add these settings to your settings.py file to enable Kubernetes worker support.
"""

import os

# Worker backend configuration
# Options: 'docker' (default), 'kubernetes', 'k8s'
QFIELDCLOUD_WORKER_BACKEND = os.environ.get("QFIELDCLOUD_WORKER_BACKEND", "docker")

# Kubernetes-specific settings
if QFIELDCLOUD_WORKER_BACKEND in ["kubernetes", "k8s"]:
    # Kubernetes namespace for worker jobs
    QFIELDCLOUD_K8S_NAMESPACE = os.environ.get("QFIELDCLOUD_K8S_NAMESPACE", "default")

    # Kubernetes service account for worker jobs (must have permissions to create/delete jobs)
    QFIELDCLOUD_K8S_SERVICE_ACCOUNT = os.environ.get(
        "QFIELDCLOUD_K8S_SERVICE_ACCOUNT", "qfieldcloud-worker"
    )

    # For K8s, transformation grids volume should be a PVC name
    # QFIELDCLOUD_TRANSFORMATION_GRIDS_VOLUME_NAME should point to a PVC

    # Docker-specific settings are not needed for K8s
    # QFIELDCLOUD_DEFAULT_NETWORK is ignored in K8s mode
