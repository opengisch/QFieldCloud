from django.urls import path

from .views import (
    AvatarFileReadView,
    compatibility_file_crud_view,
    compatibility_file_list_view,
    compatibility_project_meta_file_read_view,
)

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
    path(
        "files/thumbnails/<uuid:project_id>/",
        compatibility_project_meta_file_read_view,
        name="filestorage_project_thumbnails",
    ),
    path(
        "files/avatars/<str:username>/",
        AvatarFileReadView.as_view(),
        name="filestorage_avatars",
    ),
    # NOTE The sole purpose of this URL is to keep backwards compatibility with QField/QFieldSync. They expect the URL path to end with filename with file extension.
    path(
        "files/avatars/<str:username>/<str:filename>",
        AvatarFileReadView.as_view(),
        name="filestorage_named_avatars",
    ),
]
