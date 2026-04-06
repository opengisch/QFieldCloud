import logging

from django.contrib.gis.geos import Polygon
from django.db import transaction
from django.db.models import Q
from django.utils.translation import gettext as _

from qfieldcloud.core import invitations_utils as invitation
from qfieldcloud.core import permissions_utils as perms
from qfieldcloud.core.models import (
    Job,
    Person,
    Project,
    ProjectCollaborator,
    ProjectSeed,
    Secret,
    Team,
    User,
)
from qfieldcloud.core.utils2 import project_seed

logger = logging.getLogger(__name__)


def create_collaborator(
    project: Project, user: Person | Team, created_by: Person
) -> tuple[bool, str]:
    """Creates a new collaborator (qfieldcloud.core.ProjectCollaborator) if possible

    Args:
        project: the project to add collaborator to
        user: the user to be added as collaborator
        created_by: the user that initiated the collaborator creation

    Returns:
        success, message - whether the collaborator creation was success and explanation message of the outcome
    """
    success, message = False, ""

    if isinstance(user, Team):
        user_type_name = "Team"
    else:
        user_type_name = "User"

    try:
        perms.check_can_become_collaborator(user, project)

        # TODO actual invitation, not insertion of already existing user (see TODO about inviting
        # users to create accounts above)
        ProjectCollaborator.objects.create(
            project=project,
            collaborator=user,
            created_by=created_by,
            updated_by=created_by,
        )
        success = True
        message = _(
            f'{user_type_name} "{user.username}" has been invited to the project.'
        )
    except perms.UserOrganizationRoleError:
        message = _(
            f"{user_type_name} '{user.username}' is not a member of the organization that owns the project. "
            f"Please add this {user_type_name.lower()} to the organization first."
        )
    except (
        perms.AlreadyCollaboratorError,
        perms.ReachedCollaboratorLimitError,
        perms.ExpectedPremiumUserError,
    ) as err:
        message = str(err)

    return success, message


def create_collaborator_by_username_or_email(
    project: Project, username: str, created_by: Person
) -> tuple[bool, str]:
    """Creates a new collaborator (qfieldcloud.core.ProjectCollaborator) if possible

    Args:
        project: the project to add collaborator to
        user: the username or email to be added as collaborator or invited to join QFieldCloud
        created_by: the user that initiated the collaborator creation

    Returns:
        success, message - whether the collaborator creation was success and explanation message of the outcome
    """
    success, message = False, ""
    users = list(
        Person.objects.filter(Q(username=username) | Q(email=username))
    ) + list(Team.objects.filter(username=username, team_organization=project.owner))

    if len(users) == 0:
        # No user found, if string is an email address, we try to send a link
        if invitation.is_valid_email(username):
            success, message = invitation.invite_user_by_email(username, created_by)
        else:
            message = _('User "{}" does not exist.').format(username)
    elif len(users) > 1:
        # TODO support invitation of multiple users
        message = _("Adding multiple collaborators at once is not supported.").format(
            username
        )
    elif users[0].is_organization:
        message = _(
            'Organization "{}" cannot be added. Only users and teams can be collaborators.'
        ).format(username)
    else:
        success, message = create_collaborator(project, users[0], created_by)

    return success, message


def clone_project_secrets(source_project: Project, dest_project: Project) -> None:
    """Copy project-level secrets from the source project to the destination project.

    Only copies secrets that belong directly to the project (not user-assigned
    or organization-level secrets).
    """
    project_secrets = source_project.secrets.filter(
        assigned_to__isnull=True,
        organization__isnull=True,
    )

    for secret in project_secrets:
        Secret.objects.create(
            name=secret.name,
            type=secret.type,
            project=dest_project,
            value=secret.value,
            created_by=secret.created_by,
        )


@transaction.atomic
def clone_project(
    source_project: Project,
    new_name: str,
    owner: User,
    created_by: User,
    extent_bbox: tuple[float, float, float, float] | None = None,
    clone_secrets: bool = False,
    # clone_collaborators: bool = False,
) -> tuple[Project, Job]:
    """Clone a project: create a new Project, ProjectSeed, Secrets, and a CLONE_PROJECT job.

    Args:
        source_project: the project to clone from
        new_name: the name for the new project
        owner: the owner of the new project
        created_by: the user initiating the clone
        extent_bbox: optional (xmin, ymin, xmax, ymax) in EPSG:3857; defaults to a global extent
        clone_secrets: whether to clone the project secrets
        # clone_collaborators: whether to clone the project collaborators

    Returns:
        (new_project, clone_job) tuple
    """
    new_project = Project.objects.create(
        name=new_name,
        owner=owner,
        description=source_project.description,
        is_public=source_project.is_public,
        overwrite_conflicts=source_project.overwrite_conflicts,
        has_restricted_projectfiles=source_project.has_restricted_projectfiles,
    )

    if extent_bbox is None:
        extent_bbox = project_seed.DEFAULT_PROJECT_EXTENT

    extent_polygon = Polygon.from_bbox(extent_bbox)

    ProjectSeed.objects.create(
        project=new_project,
        copy_from_project=source_project,
        extent=extent_polygon,
        settings={
            "schemaId": ProjectSeed.SETTINGS_SCHEMA_ID,
            "basemaps": [],
            "xlsform": None,
        },
    )

    if clone_secrets:
        clone_project_secrets(source_project, new_project)

    # if clone_collaborators:
    #     clone_project_collaborators(source_project, new_project)

    clone_job = Job.objects.create(
        project=new_project,
        type=Job.Type.CLONE_PROJECT,
        created_by=created_by,
        triggered_by=created_by,
    )

    logger.info(
        f"Clone job {clone_job.id} created for new project {new_project.id} "
        f"(cloned from {source_project.id})."
    )

    return new_project, clone_job
