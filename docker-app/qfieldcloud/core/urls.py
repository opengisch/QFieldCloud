from django.urls import include, path
from qfieldcloud.core.views import (
    collaborators_views,
    deltas_views,
    files_views,
    jobs_views,
    members_views,
    package_views,
    projects_views,
    qfield_files_views,
    status_views,
    users_views,
)
from rest_framework.routers import DefaultRouter

router = DefaultRouter()
router.register(r"projects", projects_views.ProjectViewSet, basename="project")
router.register(r"jobs", jobs_views.JobViewSet, basename="jobs")

"""
TODO future URL refactor
projects/
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
organizations/
organizations/<str:organization_name>/
organizations/<str:organization_name>/members/
organizations/<str:organization_name>/teams/
organizations/<str:organization_name>/teams/<str:team_name>/members/
"""

urlpatterns = [
    path("projects/public/", projects_views.PublicProjectsListView.as_view()),
    path("", include(router.urls)),
    path("users/", users_views.ListUsersView.as_view()),
    path(
        "users/<str:username>/organizations/",
        users_views.ListUserOrganizationsView.as_view(),
    ),
    path("users/<str:username>/", users_views.RetrieveUpdateUserView.as_view()),
    path(
        "collaborators/<uuid:projectid>/",
        collaborators_views.ListCreateCollaboratorsView.as_view(),
    ),
    path(
        "collaborators/<uuid:projectid>/<str:username>/",
        collaborators_views.GetUpdateDestroyCollaboratorView.as_view(),
    ),
    path("files/<uuid:projectid>/", files_views.ListFilesView.as_view()),
    path(
        "files/<uuid:projectid>/<path:filename>/",
        files_views.DownloadPushDeleteFileView.as_view(),
        name="project_file_download",
    ),
    path(
        "files/meta/<uuid:projectid>/<path:filename>",
        files_views.ProjectMetafilesView.as_view(),
        name="project_metafiles",
    ),
    path(
        "files/public/<path:filename>",
        files_views.PublicFilesView.as_view(),
        name="public_files",
    ),
    path(
        "packages/<uuid:project_id>/latest/",
        package_views.LatestPackageView.as_view(),
    ),
    path(
        "packages/<uuid:project_id>/latest/files/<path:filename>",
        package_views.LatestPackageDownloadFilesView.as_view(),
    ),
    path("qfield-files/<uuid:projectid>/", qfield_files_views.ListFilesView.as_view()),
    path(
        "qfield-files/<uuid:projectid>/<path:filename>/",
        qfield_files_views.DownloadFileView.as_view(),
    ),
    path(
        "qfield-files/export/<uuid:projectid>/",
        qfield_files_views.PackageView.as_view(),
    ),
    path("members/<str:organization>/", members_views.ListCreateMembersView.as_view()),
    path(
        "members/<str:organization>/<str:username>/",
        members_views.GetUpdateDestroyMemberView.as_view(),
    ),
    path("status/", status_views.APIStatusView.as_view()),
    path("deltas/<uuid:projectid>/", deltas_views.ListCreateDeltasView.as_view()),
    path(
        "deltas/<uuid:projectid>/<uuid:deltafileid>/",
        deltas_views.ListDeltasByDeltafileView.as_view(),
    ),
    path("deltas/apply/<uuid:projectid>/", deltas_views.ApplyView.as_view()),
]
