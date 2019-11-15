from rest_framework import generics

from .models import Project
from .serializers import ProjectSerializer


class ProjectList(generics.ListCreateAPIView):
    queryset = Project.objects.all()  # TODO: filter only user's projects
    serializer_class = ProjectSerializer


class ProjectDetail(generics.RetrieveUpdateDestroyAPIView):
    queryset = Project.objects.all()  # TODO: filter only user's projects
    serializer_class = ProjectSerializer
