from rest_framework import generics, views
from rest_framework.parsers import FileUploadParser
from rest_framework.response import Response

from .models import Repository, GenericFile
from .serializers import RepositorySerializer


class RepositoryList(generics.ListCreateAPIView):
    """Creates (POST) or Lists (GET) user's Repositories"""
    # TODO: list only public repositories and / owner's private ones?
    serializer_class = RepositorySerializer

    def get_queryset(self):
        return Repository.objects.filter(owner=self.request.user)

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)


class RepositoryDetail(generics.RetrieveUpdateDestroyAPIView):
    """Retrieves (GET), Updates (PUT, PATCH) or Deletes (DELETE) a Repository"""
    serializer_class = RepositorySerializer

    def get_queryset(self):
        return Repository.objects.filter(owner=self.request.user)

    
class FileUploadView(views.APIView):
    parser_classes = [FileUploadParser]

    def put(self, request, filename, format=None):

        if 'file' not in request.data:
            raise ParseError("Empty content")

        f = request.data['file']

        generic_file = GenericFile(
            filename=filename,
            #upload=request.data['file'],
            user=request.user
        )

        generic_file.upload.save(f.name, f, save=True)
        #return Response(status=status.HTTP_201_CREATED)

        
        print()
        print(f'{filename} uploaded by {request.user}')
        print(request.data)
        print(request.FILES.get('file'))

        #up_file = request.FILES['file']
        #destination = open('/Users/Username/' + up_file.name, 'wb+')
        
        #for chunk in up_file.chunks():
        #    destination.write(chunk)
        #    destination.close()

        #generic_file = GenericFile(
        #    filename=filename,
        #    upload=request.data['file'],
        #    user=request.user
        #)
        #generic_file.save()
        #file_obj = request.data['file']

        # TODO: do some stuff with uploaded file

        return Response(status=204)

