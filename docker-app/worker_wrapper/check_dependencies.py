"""
Script to check if all required dependencies are available for the selected backend
"""
import sys
import importlib.util

def check_backend_dependencies():
    """Check if dependencies for the configured backend are available"""
    backend = 'docker'  # Default
    
    try:
        from django.conf import settings
        backend = getattr(settings, 'QFIELDCLOUD_WORKER_BACKEND', 'docker')
    except:
        # Not in Django context, check environment
        import os
        backend = os.environ.get('QFIELDCLOUD_WORKER_BACKEND', 'docker')
    
    missing_deps = []
    
    if backend in ['kubernetes', 'k8s']:
        # Check Kubernetes dependencies
        if importlib.util.find_spec('kubernetes') is None:
            missing_deps.append('kubernetes>=29.0.0')
    else:
        # Check Docker dependencies  
        if importlib.util.find_spec('docker') is None:
            missing_deps.append('docker>=7.1.0')
    
    # Common dependencies
    if importlib.util.find_spec('tenacity') is None:
        missing_deps.append('tenacity>=9.1.2')
    
    if missing_deps:
        print(f"Missing dependencies for {backend} backend:")
        for dep in missing_deps:
            print(f"  - {dep}")
        print(f"\nInstall with: pip install {' '.join(missing_deps)}")
        return False
    
    print(f"✅ All dependencies available for {backend} backend")
    return True

if __name__ == "__main__":
    if not check_backend_dependencies():
        sys.exit(1)