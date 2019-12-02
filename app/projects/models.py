from django.db import models
from django.conf import settings


class Project(models.Model):
    """Represent a QFieldcluod project (i.e. a directory on the file system
    with at most one QGIS project inside"""

    name = models.CharField(max_length=255)
    description = models.TextField()
    homepage = models.CharField(max_length=512)
    private = models.BooleanField(default=False)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


PERMISSION_ROLE_CHOICES = (
    (settings.PERMISSION_ROLE['admin'], 'admin'),
    (settings.PERMISSION_ROLE['manager'], 'manager'),
    (settings.PERMISSION_ROLE['editor'], 'editor'),
    (settings.PERMISSION_ROLE['reporter'], 'reporter'),
    (settings.PERMISSION_ROLE['reader'], 'reader'),
)


class Collaborator(models.Model):

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    role = models.IntegerField(choices=PERMISSION_ROLE_CHOICES,
                               default=settings.PERMISSION_ROLE['reader'])
