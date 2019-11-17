from django.contrib import admin

from .models import Repository, GenericFile


admin.site.register(Repository)
admin.site.register(GenericFile)
