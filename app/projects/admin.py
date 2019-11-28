from django.contrib import admin

from .models import Project, Collaborator


admin.site.register(Project)
admin.site.register(Collaborator)
