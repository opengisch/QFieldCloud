from django.contrib import admin
from qfieldcloud.core.models import (
    User, Organization, OrganizationMember, Project, ProjectCollaborator)


admin.site.register(User)
admin.site.register(Organization)
admin.site.register(OrganizationMember)
admin.site.register(Project)
admin.site.register(ProjectCollaborator)
