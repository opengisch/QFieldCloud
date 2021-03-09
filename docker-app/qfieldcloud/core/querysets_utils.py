from django.db.models import Count, Q
from django.db.models.expressions import Case, F, Value, When
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
    user, owner, include_public=False, include_memberships=False
):
    """Return a queryset with all projects that are available to the `user`.
    The param `user` is meant to be the user that did the request and the `owner`
    is the user that has access to them.
    - owned `owner` or organization he belongs to and collaborated with `user`
    """

    filters = {}
    if user != owner:
        filters["private"] = False

    # 1) owned by `owner` (public only if user!=owner)
    queryset = Project.objects.filter(owner=owner, **filters).distinct()

    if not owner.is_organization:
        # 2) owned by anyone, but `owner` is a collaborator (public only if user!=owner)
        queryset |= Project.objects.filter(
            collaborators__in=ProjectCollaborator.objects.filter(collaborator=owner),
            **filters
        ).distinct()

    if include_memberships:
        if owner.is_organization:
            organization_filters = {**filters}

            # has `user` as a member, then include also private projects
            if OrganizationMember.objects.filter(
                organization=owner, member=user
            ).exists():
                organization_filters.pop("private", None)
            # has `user` as an owner, then include also private projects
            elif Organization.objects.filter(
                id=owner.id, organization_owner=user
            ).exists():
                organization_filters.pop("private", None)

            # 3) owned by `owner` which is an organization
            queryset |= Project.objects.filter(
                owner=owner, **organization_filters
            ).distinct()

            # 4) owned by `owner` which is an organization and has `user` as a collanorator
            queryset |= Project.objects.filter(
                owner=owner,
                collaborators__in=ProjectCollaborator.objects.filter(collaborator=user),
            ).distinct()
        else:
            # 5) owned by organizations where `owner` is a member (public only if user!=owner)
            membership_organizations = OrganizationMember.objects.filter(
                member=owner
            ).values("organization")
            queryset |= Project.objects.filter(
                owner__in=membership_organizations
            ).distinct()

            # 6) owned by organizations where `owner` is the owner (public only if user!=owner)
            owned_organizations = Organization.objects.filter(
                organization_owner=owner
            ).distinct()
            queryset |= Project.objects.filter(owner__in=owned_organizations).distinct()

    if include_public:
        queryset |= Project.objects.filter(private=False).distinct()

    # Add all the projects of the organizations where `user` is admin
    queryset = queryset.annotate(collaborators__count=Count("collaborators"))
    queryset = queryset.annotate(deltas__count=Count("deltas"))
    queryset = queryset.annotate(
        collaborators__role=Case(
            When(collaborators__collaborator=user, then=F("collaborators__role"))
        )
    )
    queryset = queryset.annotate(
        collaborators__role=Case(
            When(collaborators__role=1, then=Value("admin", output_field=CharField())),
            When(
                collaborators__role=2, then=Value("manager", output_field=CharField())
            ),
            When(collaborators__role=3, then=Value("editor", output_field=CharField())),
            When(
                collaborators__role=4, then=Value("reporter", output_field=CharField())
            ),
            When(collaborators__role=5, then=Value("reader", output_field=CharField())),
        )
    )

    queryset.order_by("owner__username", "name")

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


def get_all_public_projects():
    """Return all public projects."""
    return Project.objects.filter(private=False)


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
