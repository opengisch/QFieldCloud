from django.core.exceptions import ObjectDoesNotExist
from drf_spectacular.utils import extend_schema, extend_schema_view


from qfieldcloud.core import pagination, permissions_utils, querysets_utils
from qfieldcloud.core.models import (
    Organization,
    Project,
    TeamMember,
    Team,
)
from qfieldcloud.core.serializers import (
    CompleteUserSerializer,
    OrganizationSerializer,
    PublicInfoUserSerializer,
    TeamMemberSerializer,
    TeamSerializer,
)

from rest_framework import generics, permissions
from rest_framework.response import Response

from django.contrib.auth.models import User
from django.shortcuts import get_object_or_404


class ListUsersViewPermissions(permissions.BasePermission):
    def has_permission(self, request, view):
        return permissions_utils.can_list_users_organizations(request.user)


@extend_schema_view(
    get=extend_schema(description="List users and/or organizations"),
)
class ListUsersView(generics.ListAPIView):
    serializer_class = PublicInfoUserSerializer
    permission_classes = [permissions.IsAuthenticated, ListUsersViewPermissions]
    pagination_class = pagination.QfcLimitOffsetPagination()

    def get_queryset(self):
        params = self.request.GET
        query = params.get("q", "")

        project = None
        if params.get("project"):
            try:
                project = Project.objects.get(id=params.get("project"))
            except Project.DoesNotExist:
                pass

        organization = None
        if params.get("organization"):
            try:
                organization = Organization.objects.get(
                    username=params.get("organization")
                )
            except Project.DoesNotExist:
                pass

        # TODO : are these GET paremters documented somewhere ? Shouldn't we use something
        # like django_filters.rest_framework.DjangoFilterBackend so they get auto-documented
        # in DRF's views, or is that supposedly done with swagger ?
        exclude_organizations = bool(int(params.get("exclude_organizations") or 0))
        exclude_teams = bool(int(params.get("exclude_teams") or 0))
        invert = bool(int(params.get("invert") or 0))
        return querysets_utils.get_users(
            query,
            project=project,
            organization=organization,
            exclude_organizations=exclude_organizations,
            exclude_teams=exclude_teams,
            invert=invert,
        )


class RetrieveUpdateUserViewPermissions(permissions.BasePermission):
    def has_permission(self, request, view):
        username = permissions_utils.get_param_from_request(request, "username")

        try:
            user = User.objects.get(username=username)
        except ObjectDoesNotExist:
            return False

        if request.method == "GET":
            # The queryset is already filtered by what the user can see
            return True
        if request.method in ["PUT", "PATCH"]:
            return permissions_utils.can_update_user(request.user, user)
        return False


@extend_schema_view(
    retrieve=extend_schema(
        """Retrieve a single user's (or organization) publicly
        information or complete info if the request is done by the user
        himself"""
    ),
    put=extend_schema("Update a user"),
    patch=extend_schema("Partially update a user"),
)
class RetrieveUpdateUserView(generics.RetrieveUpdateAPIView):
    """Get or Update the authenticated user"""

    permission_classes = [
        permissions.IsAuthenticated,
        RetrieveUpdateUserViewPermissions,
    ]
    serializer_class = CompleteUserSerializer

    def get_object(self):
        username = self.request.parser_context["kwargs"]["username"]
        return User.objects.get(username=username)

    def get(self, request, username):
        user = User.objects.get(username=username)

        if user.type == User.Type.ORGANIZATION:
            organization = Organization.objects.of_user(request.user).get(
                username=username
            )
            serializer = OrganizationSerializer(organization)
        else:
            if request.user == user:
                serializer = CompleteUserSerializer(user)
            else:
                serializer = PublicInfoUserSerializer(user)

        return Response(serializer.data)


class ListUserOrganizationsViewPermissions(permissions.BasePermission):
    def has_permission(self, request, view):
        username = permissions_utils.get_param_from_request(request, "username")

        if request.user.username != username:
            return False

        if request.method == "GET":
            return True

        return False


@extend_schema_view(
    get=extend_schema(description="Get a user's organization"),
)
class ListUserOrganizationsView(generics.ListAPIView):
    """Get user's organizations"""

    permission_classes = [
        permissions.IsAuthenticated,
        ListUserOrganizationsViewPermissions,
    ]
    serializer_class = OrganizationSerializer

    def get_queryset(self):
        return Organization.objects.of_user(self.request.user)


class TeamMemberDeleteViewPermissions(permissions.BasePermission):
    def has_permission(self, request, view):
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


# @extend_schema_view(
#     delete=extend_schema(description="Remove a member from a team"),
# )
# class TeamMemberDeleteView(generics.DestroyAPIView):
#     permission_classes = [
#         permissions.IsAuthenticated,
#         TeamMemberDeleteViewPermissions,
#     ]
#     serializer_class = TeamMemberSerializer

#     def get_queryset(self):
#         """
#         Define the queryset used for the view, ensuring objects are filtered
#         based on URL parameters.
#         """
#         organization_name = self.kwargs.get("organization_name")
#         team_name = self.kwargs.get("team_name")
#         member_username = self.kwargs.get("member_username")

#         return TeamMember.objects.filter(
#             team__organization__username=organization_name,
#             team__username=Team.format_team_name(organization_name, team_name),
#             member__username=member_username,
#         )


class TeamMemberPermission(permissions.BasePermission):
    """
    Permission class to handle CRUD operations for team members.
    """

    def has_permission(self, request, view):
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

    def has_permission(self, request, view):
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
class TeamDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    Handles GET, PUT, and DELETE for teams under a specific organization.
    """

    permission_classes = [permissions.IsAuthenticated, TeamPermission]
    serializer_class = TeamSerializer

    def get_object(self):
        organization_name = self.kwargs.get("organization_name")
        team_name = self.kwargs.get("team_name")

        organization = get_object_or_404(Organization, username=organization_name)
        full_team_name = Team.format_team_name(organization_name, team_name)

        return get_object_or_404(
            Team, team_organization=organization, username=full_team_name
        )

    def perform_update(self, serializer):
        """
        Handle team name updates with validation.
        """
        organization_name = self.kwargs.get("organization_name")
        new_team_name = self.request.data.get("username")

        if not new_team_name:
            raise permissions.ValidationError({"error": "New team name is required."})

        full_team_name = Team.format_team_name(organization_name, new_team_name)

        if Team.objects.filter(
            team_organization=serializer.instance.team_organization,
            username=full_team_name,
        ).exists():
            raise permissions.ValidationError(
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

    def get_queryset(self):
        organization_name = self.kwargs.get("organization_name")
        organization = get_object_or_404(Organization, username=organization_name)
        return Team.objects.filter(team_organization=organization)

    def perform_create(self, serializer):
        organization_name = self.kwargs.get("organization_name")
        organization = get_object_or_404(Organization, username=organization_name)

        team_name = self.request.data.get("username")

        if not team_name:
            raise ValueError({"Empty Value Error": "Team name is required."})

        full_team_name = Team.format_team_name(organization_name, team_name)

        serializer.save(team_organization=organization, username=full_team_name)


@extend_schema_view(
    get=extend_schema(description="List all members of a team"),
    post=extend_schema(description="Add a new member to a team"),
)
class GetUpdateDestroyTeamMemberView(generics.RetrieveUpdateDestroyAPIView):
    """
    View to handle adding and listing team members. --> organizations/<str:organization_name>/team/<str:team_name>/members/"
    """

    permission_classes = [permissions.IsAuthenticated, TeamMemberPermission]
    serializer_class = TeamMemberSerializer

    def get_queryset(self):
        organization_name = self.kwargs.get("organization_name")
        team_name = self.kwargs.get("team_name")

        full_team_name = Team.format_team_name(organization_name, team_name)

        return TeamMember.objects.filter(
            team__team_organization__username=organization_name,
            team__username=full_team_name,
        ).select_related("member")


class ListCreateTeamMembersView(generics.ListCreateAPIView):
    permission_classes = [permissions.IsAuthenticated, TeamMemberPermission]
    serializer_class = TeamMemberSerializer

    def get_queryset(self):
        organization_name = self.request.parser_context["kwargs"]["organization_name"]
        team_name = self.request.parser_context["kwargs"]["team_name"]
        full_team_name = Team.format_team_name(organization_name, team_name)

        return TeamMember.objects.filter(
            team__team_organization__username=organization_name,
            team__username=full_team_name,
        )

    def post(self, request, organization_name, team_name):
        print(101, request.data, organization_name, team_name)
        data = {**request.data, "team": team_name}

        print(102, data, organization_name, team_name)
        serializer = self.get_serializer(data=data)
        print(111)
        try:
            if serializer.is_valid(raise_exception=True):
                print(112)
                team = serializer.validated_data["team"]
                print(113)
                member_obj = serializer.validated_data["member"]
                print(114)
                serializer.save(team=team, member=member_obj)
                print(115)
            print(116)
        except Exception as e:
            print(117)
            print(e)
