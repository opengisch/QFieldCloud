from django.urls import path
from rest_framework.routers import DefaultRouter

from qfieldcloud.project.views import ProjectViewSet, PublicProjectsListView

router = DefaultRouter()
router.register(r"projects", ProjectViewSet, basename="project")

"""
TODO future URL refactor
projects/
projects/<uuid:project_id>/
projects/<uuid:project_id>/files/
projects/<uuid:project_id>/files/<path:filename>/
projects/<uuid:project_id>/jobs/
projects/<uuid:project_id>/jobs/<uuid:job_id>/
projects/<uuid:project_id>/packages/
projects/<uuid:project_id>/packages/latest/files/
projects/<uuid:project_id>/packages/latest/files/<path:filename>/
projects/<uuid:project_id>/deltas/
projects/<uuid:project_id>/deltas/<uuid:delta_id>/
projects/<uuid:project_id>/collaborators/
"""

urlpatterns = [
    path("projects/public/", PublicProjectsListView.as_view()),
    *router.urls,
]
