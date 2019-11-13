from django.db import models

# Create your models here.


class QgisProject(models.Model):
    file_name = models.CharField(max_length=255)
    project = models.FileField(upload_to='projects/')
    uploaded_at = models.DateTimeField(auto_now_add=True)

    # Create a string representation
    def __str__(self):
        return self.file_name
