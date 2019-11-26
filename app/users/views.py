from rest_framework import generics, views, status
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser


class RetrieveUserView(views.APIView):

    def get(self, request, username):
        """Get a single user (publicly information)"""


class ListUsersView(views.APIView):

    def get(self, request):
        """Get all users and organizations"""


class RetrieveUpdateAuthenticatedUserView(views.APIView):

    def get(self, request):
        """Get the authenticated user"""

    def patch(self, request):
        """Update the authenticated user"""
