from django.contrib.gis.db import models
from django.utils.translation import gettext as _


class ProjectRoleOrigins(models.TextChoices):
    PROJECTOWNER = "project_owner", _("Project owner")
    ORGANIZATIONOWNER = "organization_owner", _("Organization owner")
    ORGANIZATIONADMIN = "organization_admin", _("Organization admin")
    COLLABORATOR = "collaborator", _("Collaborator")
    TEAMMEMBER = "team_member", _("Team member")
    PUBLIC = "public", _("Public")
