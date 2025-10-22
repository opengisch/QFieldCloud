"""
Worker factory for choosing between Docker and Kubernetes implementations
"""
import os
from django.conf import settings


def get_worker_backend():
    """Get the configured worker backend"""
    return getattr(settings, 'QFIELDCLOUD_WORKER_BACKEND', 'docker')


def create_job_run(job_id: str):
    """Factory function to create the appropriate JobRun instance"""
    backend = get_worker_backend()
    
    if backend == 'kubernetes' or backend == 'k8s':
        from .k8s_wrapper import K8sJobRun
        return K8sJobRun(job_id)
    else:
        from .wrapper import JobRun
        return JobRun(job_id)


def create_package_job_run(job_id: str):
    """Factory function to create the appropriate PackageJobRun instance"""
    backend = get_worker_backend()
    
    if backend == 'kubernetes' or backend == 'k8s':
        from .k8s_wrapper import K8sPackageJobRun
        return K8sPackageJobRun(job_id)
    else:
        from .wrapper import PackageJobRun
        return PackageJobRun(job_id)


def create_apply_delta_job_run(job_id: str):
    """Factory function to create the appropriate ApplyDeltaJobRun instance"""
    backend = get_worker_backend()
    
    if backend == 'kubernetes' or backend == 'k8s':
        from .k8s_wrapper import K8sApplyDeltaJobRun
        return K8sApplyDeltaJobRun(job_id)
    else:
        from .wrapper import ApplyDeltaJobRun
        return ApplyDeltaJobRun(job_id)


def create_process_projectfile_job_run(job_id: str):
    """Factory function to create the appropriate ProcessProjectfileJobRun instance"""
    backend = get_worker_backend()
    
    if backend == 'kubernetes' or backend == 'k8s':
        from .k8s_wrapper import K8sProcessProjectfileJobRun
        return K8sProcessProjectfileJobRun(job_id)
    else:
        from .wrapper import ProcessProjectfileJobRun
        return ProcessProjectfileJobRun(job_id)


def cancel_orphaned_workers():
    """Cancel orphaned workers using the appropriate backend"""
    backend = get_worker_backend()
    
    if backend == 'kubernetes' or backend == 'k8s':
        from .k8s_wrapper import cancel_orphaned_k8s_workers
        return cancel_orphaned_k8s_workers()
    else:
        from .wrapper import cancel_orphaned_workers as cancel_docker_workers
        return cancel_docker_workers()


# For backwards compatibility, expose the factory functions as classes
class JobRun:
    def __new__(cls, job_id: str):
        return create_job_run(job_id)


class PackageJobRun:
    def __new__(cls, job_id: str):
        return create_package_job_run(job_id)


class ApplyDeltaJobRun:
    def __new__(cls, job_id: str):
        return create_apply_delta_job_run(job_id)


class ProcessProjectfileJobRun:
    def __new__(cls, job_id: str):
        return create_process_projectfile_job_run(job_id)