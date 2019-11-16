from rest_framework import generics, views
from rest_framework.parsers import FileUploadParser
from rest_framework.response import Response

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


class FileUploadView(views.APIView):
    parser_classes = [FileUploadParser]

    def put(self, request, filename, format=None):
    
        print()
        print(f'{filename} uploaded by {request.user}')
        print()

        #file_obj = request.data['file']

        # TODO: do some stuff with uploaded file

        return Response(status=204)

