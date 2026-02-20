from django.urls import path

from .views import (
    AvatarFileReadView,
    FileCrudView,
    FileListView,
    FileMetadataView,
    ProjectMetaFileReadView,
)

urlpatterns = [
    path(
        "files/<uuid:project_id>/",
        FileListView.as_view(),
        name="filestorage_list_files",
    ),
    path(
        "files/<uuid:project_id>/<path:filename>/",
        FileCrudView.as_view(),
        name="filestorage_crud_file",
    ),
    path(
        "files/metadata/<uuid:project_id>/<path:filename>/",
        FileMetadataView.as_view(),
        name="filestorage_file_metadata",
    ),
    path(
        "files/thumbnails/<uuid:project_id>/",
        ProjectMetaFileReadView.as_view(),
        name="filestorage_project_thumbnails",
    ),
    path(
        "files/avatars/<str:public_id>/",
        AvatarFileReadView.as_view(),
        name="filestorage_avatars",
    ),
    # NOTE The sole purpose of this URL is to keep backwards compatibility with QField/QFieldSync. They expect the URL path to end with filename with file extension.
    path(
        "files/avatars/<str:public_id>/<str:filename>",
        AvatarFileReadView.as_view(),
        name="filestorage_named_avatars",
    ),
]
