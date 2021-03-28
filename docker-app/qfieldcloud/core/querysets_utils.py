from django.db.models import Count, Q
from django.db.models.expressions import Case, Value, When
from django.db.models.fields import CharField
from django.db.models.manager import BaseManager
from django.db.models.query import QuerySet
from qfieldcloud.core.models import (
    Delta,
    Organization,
    OrganizationMember,
    Project,
    ProjectCollaborator,
    User,
)


def get_available_projects(
    user,
    owner,
    ownerships=False,
    collaborations=False,
    memberships=False,
    public=False,
):
    """Return a queryset with all projects that are available to the `user`.
    The param `user` is meant to be the user that did the request and the `owner`
    is the user that has access to them.
    - owned `owner` or organization he belongs to and collaborated with `user`
    """

    # just a hacky way to get always false where clause. This allows all the conditions below to be `where |=`
    where = Q(pk=None)
    when = []

    if ownerships:
        # 1) owned by `owner` (public only if user!=owner)
        where_owner = {
            "owner": owner,
        }

        if user != owner:
            where_owner["private"] = False

        where |= Q(**where_owner)
        when.append(
            When(**where_owner, then=Value("owner", output_field=CharField())),
        )

    if collaborations:
        # 2.1) owned by anyone, but `user` is a collaborator
        where |= Q(
            collaborators__in=ProjectCollaborator.objects.filter(collaborator=user)
        )

        # 2.2) owned by anyone, but `owner` is a collaborator (public only if user!=owner)
        where_collaborator = {
            "collaborators__in": ProjectCollaborator.objects.filter(collaborator=owner),
        }

        if user != owner:
            where_collaborator["private"] = False

        where |= Q(**where_collaborator)

    if memberships:
        if owner.is_organization:
            organization_filters = {}

            if (
                # has no `user` as an admin, then include also private projects
                not OrganizationMember.objects.filter(
                    organization=owner,
                    member=user,
                    role=OrganizationMember.ROLE_ADMIN,
                ).exists()
                # has `user` as an owner, then include also private projects
                and not Organization.objects.filter(
                    id=owner.id, organization_owner=user
                ).exists()
            ):
                organization_filters["private"] = False

            # 3) owned by `owner` which is an organization
            where |= Q(
                owner=owner,
                **organization_filters,
            )

            # 4) owned by `owner` which is an organization and has `user` as a collanorator
            where |= Q(
                owner=owner,
                collaborators__in=ProjectCollaborator.objects.filter(collaborator=user),
            )
        else:
            # 5) owned by organizations where `owner` is a member (public only if user!=owner)
            membership_organizations = OrganizationMember.objects.filter(
                member=owner,
                role=OrganizationMember.ROLE_ADMIN,
            ).values("organization")
            where_org_admin_condition = {"owner__in": membership_organizations}

            if user != owner:
                where_org_admin_condition["private"] = False

            where |= Q(**where_org_admin_condition)
            when.append(
                When(
                    **where_org_admin_condition,
                    then=Value("organization_admin", output_field=CharField()),
                ),
            )

            # 6) owned by organizations where `owner` is the owner (public only if user!=owner)
            owned_organizations = Organization.objects.filter(organization_owner=owner)
            where_org_owner = {"owner__in": owned_organizations}

            if user != owner:
                where_org_owner["private"] = False

            where |= Q(**where_org_owner)
            when.append(
                When(
                    **where_org_owner,
                    then=Value("organization_owner", output_field=CharField()),
                ),
            )

    if public:
        where_public_condition = {"private": False}
        where |= Q(**where_public_condition)
        when.append(
            When(
                **where_public_condition, then=Value("public", output_field=CharField())
            ),
        )

    queryset = Project.objects.filter(where).distinct()
    queryset = queryset.annotate(collaborators__count=Count("collaborators"))
    queryset = queryset.annotate(deltas__count=Count("deltas"))
    queryset = queryset.annotate(
        user_role=Case(
            When(
                collaborators__role=ProjectCollaborator.ROLE_ADMIN,
                then=Value("admin", output_field=CharField()),
            ),
            When(
                collaborators__role=ProjectCollaborator.ROLE_MANAGER,
                then=Value("manager", output_field=CharField()),
            ),
            When(
                collaborators__role=ProjectCollaborator.ROLE_EDITOR,
                then=Value("editor", output_field=CharField()),
            ),
            When(
                collaborators__role=ProjectCollaborator.ROLE_REPORTER,
                then=Value("reporter", output_field=CharField()),
            ),
            When(
                collaborators__role=ProjectCollaborator.ROLE_READER,
                then=Value("reader", output_field=CharField()),
            ),
            *when,
        )
    )

    queryset = queryset.order_by("owner__username", "name")

    return queryset


def get_user_organizations(user: User, administered_only: bool = False) -> QuerySet:
    owned_organizations = Organization.objects.filter(
        organization_owner=user
    ).distinct()
    memberships = OrganizationMember.objects.filter(member=user)

    if administered_only:
        memberships = memberships.filter(role=OrganizationMember.ROLE_ADMIN)

    membership_organizations = Organization.objects.filter(members__in=memberships)
    organizations = owned_organizations.union(membership_organizations)

    return organizations


def get_organization_members(organization):
    return OrganizationMember.objects.filter(organization=organization)


def get_project_deltas(project):
    """Return a queryset of all available deltas of a specific project."""
    return Delta.objects.filter(project=project)


def get_collaborators_of_project(project):
    """Return a queryset of all available collaborators of a specific project."""
    return ProjectCollaborator.objects.filter(project=project)


def get_users(
    username: str,
    project: Project = None,
    organization: Organization = None,
    exclude_organizations: bool = False,
) -> BaseManager:
    assert (
        project is None or organization is None
    ), "Cannot have the project and organization filters set simultaneously"

    if username:
        users = User.objects.filter(
            Q(username__icontains=username) | Q(email__icontains=username)
        )
    else:
        users = User.objects.all()

    if exclude_organizations:
        users = users.filter(user_type=User.TYPE_USER)

    # exclude the already existing collaborators and the project owner
    if project:
        collaborator_ids = ProjectCollaborator.objects.filter(
            project=project
        ).values_list("collaborator", flat=True)
        users = users.exclude(pk__in=collaborator_ids)
        users = users.exclude(pk=project.owner.pk)

    # exclude the already existing members, the organization owner and the organization itself from the returned users
    if organization:
        member_ids = OrganizationMember.objects.filter(
            organization=organization
        ).values_list("member", flat=True)
        users = users.exclude(pk__in=member_ids)
        users = users.exclude(pk=organization.organization_owner.pk)
        users = users.exclude(pk=organization.user_ptr.pk)

    return users.order_by("-username")
