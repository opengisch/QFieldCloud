import time

from django.utils.decorators import method_decorator
from django.conf import settings
from django.core.cache import cache

from rest_framework import views, status
from rest_framework.response import Response
from rest_framework.permissions import AllowAny

from drf_yasg.utils import swagger_auto_schema

from qfieldcloud.core import utils


@method_decorator(
    name='get', decorator=swagger_auto_schema(
        operation_description="Get the current status of the APIs",
        operation_id="Get status",))
class APIStatusView(views.APIView):
    permission_classes = [AllowAny]

    def get(self, request):

        # Try to get the status from the cache
        results = cache.get('status_results', {})
        if not results:

            results['redis'] = 'ok'
            # Check if redis is visible
            if not utils.redis_is_running():
                results['redis'] = 'error'

            results['storage'] = 'ok'
            # Check if bucket exists (i.e. the connection works)
            try:
                s3_client = utils.get_s3_client()
                s3_client.head_bucket(Bucket=settings.AWS_STORAGE_BUCKET_NAME)
            except Exception:
                results['storage'] = 'error'

            job = utils.check_orchestrator_status()
            results['orchestrator'] = 'ok'
            # Wait for the worker to finish
            for _ in range(30):
                time.sleep(2)
                if job.get_status() == 'finished':
                    if _ >= 10:
                        results['orchestrator'] = 'slow'
                    else:
                        results['orchestrator'] = 'ok'
                    break
                if job.get_status() == 'failed':
                    break

            if not job.get_status() in ['finished']:
                results['orchestrator'] = 'error'

            # Cache the result for 10 minutes
            cache.set('status_results', results, 600)

        for result in results:
            if not results[result] in ['slow', 'ok']:
                return Response(
                    results, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        return Response(results, status=status.HTTP_200_OK)
