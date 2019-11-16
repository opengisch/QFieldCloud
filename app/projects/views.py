from rest_framework import generics

from .models import Project
from .serializers import ProjectSerializer


class ProjectList(generics.ListCreateAPIView):
    """Creates (POST) or Lists (GET) user's Projects"""
    serializer_class = ProjectSerializer

    def get_queryset(self):
        return Project.objects.filter(uploaded_by=self.request.user)

    def perform_create(self, serializer):
        serializer.save(uploaded_by=self.request.user)


class ProjectDetail(generics.RetrieveUpdateDestroyAPIView):
    """Retrieves (GET), Updates (PUT, PATCH) or Deletes (DELETE) a Project"""
    serializer_class = ProjectSerializer

    def get_queryset(self):
        return Project.objects.filter(uploaded_by=self.request.user)
