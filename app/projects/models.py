from django.db import models
from django.contrib.auth.models import User


class Project(models.Model):
    """ Represent a QGIS Project """
    name = models.CharField(max_length=255)
    file_name = models.CharField(max_length=255)
    uploaded_by = models.ForeignKey(User, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name
