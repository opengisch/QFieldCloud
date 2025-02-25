from django.urls import path

from .views import (
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
]
