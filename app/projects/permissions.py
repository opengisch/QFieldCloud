from rest_framework import permissions


class IsOwner(permissions.BasePermission):

    def has_object_permission(self, request, view, obj):

        # All permissions are only allowed to the uploader of the project
        return obj.uploaded_by == request.user
