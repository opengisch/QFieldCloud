from django.core.exceptions import ObjectDoesNotExist
from django.db.models import QuerySet
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema, extend_schema_view
from qfieldcloud.core import permissions_utils
from qfieldcloud.core.models import (
    Organization,
    Team,
    TeamMember,
)
from qfieldcloud.core.serializers import (
    TeamMemberSerializer,
    TeamSerializer,
)
from rest_framework import exceptions, generics, permissions
from rest_framework.request import Request
from rest_framework.views import APIView


class TeamMemberDeleteViewPermissions(permissions.BasePermission):
    def has_permission(self, request: Request, view: APIView) -> bool:
        user = request.user
        organization_name = permissions_utils.get_param_from_request(
            request, "organization"
        )

        try:
            organization = Organization.objects.get(username=organization_name)
        except ObjectDoesNotExist:
            return False

        if request.method == "DELETE":
            return permissions_utils.can_delete_members(user, organization)

        return False


class TeamMemberPermission(permissions.BasePermission):
    """
    Permission class to handle CRUD operations for team members.
    """

    def has_permission(self, request: Request, view: APIView) -> bool:
        organization_name = view.kwargs.get("organization_name")
        team_name = view.kwargs.get("team_name")
        team_username = Team.format_team_name(organization_name, team_name)

        try:
            organization = Organization.objects.get(username=organization_name)
            _team = Team.objects.get(
                username=team_username, team_organization=organization
            )

        except (Team.DoesNotExist, Organization.DoesNotExist):
            return False

        if request.method == "GET":
            return permissions_utils.can_read_members(request.user, organization)

        elif request.method == "POST":
            return permissions_utils.can_create_members(request.user, organization)

        elif request.method in ["PUT", "PATCH"]:
            return permissions_utils.can_update_members(request.user, organization)

        elif request.method == "DELETE":
            return permissions_utils.can_delete_members(request.user, organization)

        return False


class TeamPermission(permissions.BasePermission):
    """
    Permission class to handle CRUD operations for teams.
    """

    def has_permission(self, request: Request, view: APIView) -> bool:
        organization_name = view.kwargs.get("organization_name")

        try:
            organization = Organization.objects.get(username=organization_name)
        except Organization.DoesNotExist:
            return False

        if request.method == "GET":
            return permissions_utils.can_read_members(request.user, organization)

        elif request.method in ["PUT", "POST"]:
            return permissions_utils.can_update_members(request.user, organization)

        elif request.method == "DELETE":
            return permissions_utils.can_delete_members(request.user, organization)

        return False


@extend_schema_view(
    get=extend_schema(description="Retrieve details of a team"),
    put=extend_schema(description="Update a team's name"),
    delete=extend_schema(description="Delete a team"),
)
class GetUpdateDestroyTeamDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    Handles GET, PUT, and DELETE for teams under a specific organization.
    """

    permission_classes = [permissions.IsAuthenticated, TeamPermission]
    serializer_class = TeamSerializer

    def get_object(self) -> Team:
        organization_name = self.kwargs.get("organization_name")
        team_name = self.kwargs.get("team_name")

        organization = get_object_or_404(Organization, username=organization_name)
        full_team_name = Team.format_team_name(organization_name, team_name)

        return get_object_or_404(
            Team, team_organization=organization, username=full_team_name
        )

    def perform_update(self, serializer: TeamSerializer) -> None:
        """
        Handle team name updates with validation.
        """
        organization_name = self.kwargs.get("organization_name")

        serializer.is_valid(raise_exception=True)

        new_team_name = serializer.validated_data["username"]

        full_team_name = Team.format_team_name(organization_name, new_team_name)

        if Team.objects.filter(
            team_organization=serializer.instance.team_organization,
            username=full_team_name,
        ).exists():
            raise exceptions.ValidationError(
                {"error": "A team with this name already exists."}
            )

        serializer.save(username=full_team_name)


@extend_schema_view(
    get=extend_schema(description="List all teams under an organization"),
    post=extend_schema(description="Create a new team under an organization"),
)
class TeamListCreateView(generics.ListCreateAPIView):
    """
    Handles GET (list all teams) and POST (create a new team) under an organization.
    """

    permission_classes = [permissions.IsAuthenticated, TeamPermission]
    serializer_class = TeamSerializer

    def get_queryset(self) -> QuerySet[Team]:
        organization_name = self.kwargs.get("organization_name")
        organization = get_object_or_404(Organization, username=organization_name)
        return Team.objects.filter(team_organization=organization)

    def perform_create(self, serializer: TeamSerializer) -> None:
        organization_name = self.kwargs.get("organization_name")
        organization = get_object_or_404(Organization, username=organization_name)

        serializer.is_valid(raise_exception=True)
        team_name = serializer.validated_data["username"]

        full_team_name = Team.format_team_name(organization_name, team_name)

        serializer.save(team_organization=organization, username=full_team_name)


@extend_schema_view(
    get=extend_schema(description="Retrieve, update, or delete a team member"),
    delete=extend_schema(description="Delete a team member"),
)
class DestroyTeamMemberView(generics.DestroyAPIView):
    """
    View to handle adding and listing team members. --> organizations/<str:organization_name>/team/<str:team_name>/members/"
    """

    permission_classes = [permissions.IsAuthenticated, TeamMemberPermission]
    serializer_class = TeamMemberSerializer

    def get_queryset(self) -> QuerySet[TeamMember]:
        organization_name = self.kwargs.get("organization_name")
        team_name = self.kwargs.get("team_name")

        full_team_name = Team.format_team_name(organization_name, team_name)

        return TeamMember.objects.filter(
            team__team_organization__username=organization_name,
            team__username=full_team_name,
        ).select_related("member")

    def get_object(self) -> TeamMember:
        organization_name = self.kwargs.get("organization_name")
        team_name = self.kwargs.get("team_name")
        member_username = self.kwargs.get("member_username")

        full_team_name = Team.format_team_name(organization_name, team_name)

        return get_object_or_404(
            TeamMember,
            team__team_organization__username=organization_name,
            team__username=full_team_name,
            member__username=member_username,
        )

    def get_full_team_name(self) -> str:
        organization_name = self.kwargs.get("organization_name")
        team_name = self.kwargs.get("team_name")

        return Team.format_team_name(organization_name, team_name)


@extend_schema_view(
    get=extend_schema(description="List all members of a team"),
    post=extend_schema(description="Add a new member to a team"),
)
class ListCreateTeamMembersView(generics.ListCreateAPIView):
    permission_classes = [permissions.IsAuthenticated, TeamMemberPermission]
    serializer_class = TeamMemberSerializer

    def get_queryset(self) -> QuerySet[TeamMember]:
        organization_name = self.kwargs.get("organization_name")

        return TeamMember.objects.filter(
            team__team_organization__username=organization_name,
            team__username=self.get_full_team_name(),
        )

    def get_full_team_name(self) -> str:
        organization_name = self.kwargs.get("organization_name")
        team_name = self.kwargs.get("team_name")

        return Team.format_team_name(organization_name, team_name)

    def perform_create(self, serializer: TeamMemberSerializer) -> None:
        team = Team.objects.get(
            team_organization__username=self.kwargs.get("organization_name"),
            username=self.get_full_team_name(),
        )

        serializer.save(
            team=team,
        )
