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


PROJECT_ROLE_CHOICES = (
    (settings.PROJECT_ROLE['admin'], 'admin'),
    (settings.PROJECT_ROLE['manager'], 'manager'),
    (settings.PROJECT_ROLE['editor'], 'editor'),
    (settings.PROJECT_ROLE['reporter'], 'reporter'),
    (settings.PROJECT_ROLE['reader'], 'reader'),
)


ORGANIZATION_ROLE_CHOICES = (
    (settings.ORGANIZATION_ROLE['admin'], 'admin'),
    (settings.ORGANIZATION_ROLE['member'], 'member'),
)


class ProjectRole(models.Model):

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    role = models.IntegerField(choices=PROJECT_ROLE_CHOICES,
                               default=settings.PROJECT_ROLE['reader'])


class OrganizationRole(models.Model):

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='user')
    organization = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='organization')
    role = models.IntegerField(
        choices=ORGANIZATION_ROLE_CHOICES,
        default=settings.ORGANIZATION_ROLE['member'])
