from rest_framework import serializers

from .models import Repository


class RepositorySerializer(serializers.ModelSerializer):
    class Meta:
        fields = ('id', 'name', 'created_at', 'is_public')
        model = Repository
