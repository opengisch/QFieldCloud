from rest_framework import generics, views, status
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser

from .models import Project, GenericFile
from .serializers import ProjectSerializer, GenericFileSerializer


class ProjectView(generics.ListCreateAPIView):
    """Creates (POST) or Lists (GET) user's Projects"""
    serializer_class = ProjectSerializer

    def get_queryset(self):
        return Project.objects.filter(owner=self.request.user)

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)


class ProjectFileView(generics.ListAPIView):
    """Lists files of project"""
    serializer_class = GenericFileSerializer

    def get_queryset(self):
        project_name = self.request.parser_context['kwargs']['project_name']

        return GenericFile.objects.filter(
            owner=self.request.user,
            project=Project.objects.get(name=project_name)
        )


class PushView(generics.CreateAPIView):
    """Push one or more files"""

    queryset = GenericFile.objects.all()
    serializer_class = GenericFileSerializer
    parser_classes = (MultiPartParser, FormParser,)

    def post(self, request, project_name):
        for afile in request.FILES.getlist('datafile'):

            g = GenericFile(
                owner=self.request.user,
                project=Project.objects.get(name=project_name),
                filename=str(afile),
                datafile=afile
            )
            g.save()

        return Response(status=status.HTTP_201_CREATED)


class PullView(views.APIView):
    """Pull project"""

    def get(self, request, project_name):
        return Response(status=status.HTTP_501_NOT_IMPLEMENTED)
