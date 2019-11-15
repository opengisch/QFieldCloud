from rest_framework import generics

from .models import Project
from .serializers import ProjectSerializer
from .permissions import IsOwner


class ProjectList(generics.ListCreateAPIView):
    serializer_class = ProjectSerializer

    def get_queryset(self):
        return Project.objects.filter(uploaded_by=self.request.user)


class ProjectDetail(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = (IsOwner,)
    queryset = Project.objects.all()
    serializer_class = ProjectSerializer
