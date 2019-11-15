from rest_framework import generics

from .models import Project
from .serializers import ProjectSerializer


class ProjectList(generics.ListCreateAPIView):
    """Lists user's Projects"""
    serializer_class = ProjectSerializer

    def get_queryset(self):
        return Project.objects.filter(uploaded_by=self.request.user)


class ProjectDetail(generics.RetrieveUpdateDestroyAPIView):
    """Shows and edits Project"""
    serializer_class = ProjectSerializer

    def get_queryset(self):
        return Project.objects.filter(uploaded_by=self.request.user)
