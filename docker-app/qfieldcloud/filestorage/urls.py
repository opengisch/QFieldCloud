from django.urls import path

from .views import compatibility_file_crud_view, compatibility_file_list_view

urlpatterns = [
    path(
        "files/<uuid:project_id>/",
        compatibility_file_list_view,
        name="filestorage_list_files",
    ),
    path(
        "files/<uuid:project_id>/<path:filename>/",
        compatibility_file_crud_view,
        name="filestorage_crud_file",
    ),
    # path(
    #     "files/meta/<uuid:projectid>/<path:filename>",
    #     files_views.ProjectMetafilesView.as_view(),
    #     name="project_metafiles",
    # ),
    # path(
    #     "files/public/<path:filename>",
    #     files_views.PublicFilesView.as_view(),
    #     name="public_files",
    # ),
]
