from django.contrib import admin

from .models import Project, GenericFile


admin.site.register(Project)
admin.site.register(GenericFile)
