from django.urls import include, path
from rest_framework.routers import DefaultRouter

from qfieldcloud.core.views import (
    collaborators_views,
    deltas_views,
    jobs_views,
    members_views,
    package_views,
    projects_views,
    status_views,
    teams_views,
    users_views,
)
from qfieldcloud.core.views.accounts_views import resend_confirmation_email
from qfieldcloud.filestorage.urls import urlpatterns as filestorage_urlpatterns

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
    *filestorage_urlpatterns,
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
    path(
        "packages/<uuid:project_id>/latest/",
        package_views.compatibility_latest_package_view,
    ),
    path(
        "packages/<uuid:project_id>/latest/files/<path:filename>/",
        package_views.compatibility_package_download_files_view,
    ),
    path(
        "packages/<uuid:project_id>/<uuid:job_id>/files/<path:filename>/",
        package_views.compatibility_package_upload_files_view,
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
    path(
        "organizations/<str:organization_name>/teams/",
        teams_views.TeamListCreateView.as_view(),
        name="team_list_create",
    ),
    path(
        "organizations/<str:organization_name>/teams/<str:team_name>/",
        teams_views.GetUpdateDestroyTeamDetailView.as_view(),
        name="team_detail",
    ),
    path(
        "organizations/<str:organization_name>/teams/<str:team_name>/members/",
        teams_views.ListCreateTeamMembersView.as_view(),
        name="team_member_list_create",
    ),
    path(
        "organizations/<str:organization_name>/teams/<str:team_name>/members/<str:member_username>/",
        teams_views.DestroyTeamMemberView.as_view(),
        name="team_member_destroy",
    ),
    path("resend-confirmation/", resend_confirmation_email, name="resend_confirmation"),
]
