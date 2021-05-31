from django.urls import include, path
from qfieldcloud.core.views import (
    collaborators_views,
    deltas_views,
    files_views,
    members_views,
    projects_views,
    qfield_files_views,
    status_views,
    users_views,
)
from rest_framework.routers import DefaultRouter

router = DefaultRouter()
router.register(r"projects", projects_views.ProjectViewSet, basename="project")

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
    path("qfield-files/<uuid:projectid>/", qfield_files_views.ListFilesView.as_view()),
    path(
        "qfield-files/<uuid:projectid>/<path:filename>/",
        qfield_files_views.DownloadFileView.as_view(),
    ),
    path(
        "qfield-files/export/<uuid:projectid>/", qfield_files_views.ExportView.as_view()
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
