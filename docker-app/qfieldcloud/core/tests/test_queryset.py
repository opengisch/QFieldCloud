import logging

from rest_framework.test import APITransactionTestCase

from qfieldcloud.authentication.models import AuthToken
from qfieldcloud.core import querysets_utils
from qfieldcloud.core.models import (
    Organization,
    OrganizationMember,
    Person,
    Project,
    ProjectCollaborator,
    ProjectQueryset,
    Team,
    TeamMember,
    User,
)

from .utils import set_subscription, setup_subscription_plans

logging.disable(logging.CRITICAL)


class QfcTestCase(APITransactionTestCase):
    def setUp(self):
        setup_subscription_plans()

        # user1 owns p1 and p2
        # user1 owns o1
        # user1 collaborates on p7
        self.user1 = Person.objects.create_user(username="user1", password="abc123")
        self.token1 = AuthToken.objects.get_or_create(user=self.user1)[0]

        # user2 owns p3 and p4
        # user2 admins o1
        self.user2 = Person.objects.create_user(username="user2", password="abc123")
        self.token2 = AuthToken.objects.get_or_create(user=self.user2)[0]

        # user2 owns p7 and p8
        # user2 is member of o1
        self.user3 = Person.objects.create_user(username="user3", password="abc123")
        self.token3 = AuthToken.objects.get_or_create(user=self.user3)[0]

        # user2 owns no projects
        # user2 is member of o2
        self.user4 = Person.objects.create_user(username="user4", password="abc123")
        self.token4 = AuthToken.objects.get_or_create(user=self.user4)[0]

        # organization1 owns p4 and p5
        self.organization1 = Organization.objects.create(
            username="organization1",
            password="abc123",
            type=User.Type.ORGANIZATION,
            organization_owner=self.user1,
        )

        # organization2 exists just for confusion
        self.organization2 = Organization.objects.create(
            username="organization2",
            password="abc123",
            type=User.Type.ORGANIZATION,
            organization_owner=self.user4,
        )

        self.membership1 = OrganizationMember.objects.create(
            organization=self.organization1,
            member=self.user2,
            role=OrganizationMember.Roles.ADMIN,
        )

        self.membership2 = OrganizationMember.objects.create(
            organization=self.organization1,
            member=self.user3,
            role=OrganizationMember.Roles.MEMBER,
        )

        self.team1_1 = Team.objects.create(
            username="team1_1",
            password="abc123",
            type=User.Type.TEAM,
            team_organization=self.organization1,
        )

        self.team2_1 = Team.objects.create(
            username="team2_1",
            password="abc123",
            type=User.Type.TEAM,
            team_organization=self.organization2,
        )

        self.teammembership1 = TeamMember.objects.create(
            team=self.team1_1,
            member=self.user3,
        )

        self.project1 = Project.objects.create(
            name="project1", is_public=False, owner=self.user1
        )

        self.project2 = Project.objects.create(
            name="project2", is_public=True, owner=self.user1
        )

        self.project3 = Project.objects.create(
            name="project3", is_public=False, owner=self.user2
        )

        self.project4 = Project.objects.create(
            name="project4", is_public=True, owner=self.user2
        )

        self.project5 = Project.objects.create(
            name="project5", is_public=False, owner=self.organization1
        )

        self.project6 = Project.objects.create(
            name="project6", is_public=True, owner=self.organization1
        )

        self.project7 = Project.objects.create(
            name="project7", is_public=False, owner=self.user3
        )

        self.project8 = Project.objects.create(
            name="project8", is_public=True, owner=self.user3
        )

        self.project9 = Project.objects.create(
            name="project9", is_public=False, owner=self.organization1
        )

        self.collaborator1 = ProjectCollaborator.objects.create(
            project=self.project7,
            collaborator=self.user1,
            role=ProjectCollaborator.Roles.REPORTER,
        )

        self.collaborator2 = ProjectCollaborator.objects.create(
            project=self.project9,
            collaborator=self.team1_1,
            role=ProjectCollaborator.Roles.EDITOR,
        )

        # update user default plan to disable collaborations
        set_subscription(
            [
                self.user1,
                self.user2,
                self.user3,
                self.user4,
            ],
            max_premium_collaborators_per_private_project=0,
        )

    def assertProjectRole(
        self,
        project,
        user,
        role: ProjectCollaborator.Roles | None = None,
        origin: ProjectQueryset.RoleOrigins | None = None,
        is_valid: bool = True,
    ):
        """Asserts that user has give role/origin on project"""
        assert (role is None) == (origin is None), (
            "Both role and origin should be either defined or undefined!"
        )

        # Assert user does not have any role
        if role is None:
            with self.assertRaises(Person.DoesNotExist):
                Person.objects.for_project(project).select_related(None).get(pk=user.pk)

            with self.assertRaises(Project.DoesNotExist):
                Project.objects.for_user(user).select_related(None).get(pk=project.pk)

            return

        # Test on Users
        if origin != ProjectQueryset.RoleOrigins.PUBLIC:
            # The Person.objects.for_project queryset is not symetric to Project.objects.for_user
            # because it does not include users that have a role because the project is public.
            u = Person.objects.for_project(project).get(pk=user.pk)
            self.assertEqual(u.project_role, role)
            self.assertEqual(u.project_role_origin, origin)
            self.assertEqual(u.project_role_is_valid, is_valid)

        # Test on Project
        p = Project.objects.for_user(user).get(pk=project.pk)
        self.assertEqual(p.user_role, role)
        self.assertEqual(p.user_role_origin, origin)
        self.assertEqual(p.user_role_is_valid, is_valid)

    def test_get_users(self):
        # should get all the available users
        queryset_ids = querysets_utils.get_users("").values_list("id", flat=True)
        self.assertEqual(len(queryset_ids), 8)
        self.assertTrue(self.user1.id in queryset_ids)
        self.assertTrue(self.user2.id in queryset_ids)
        self.assertTrue(self.user3.id in queryset_ids)
        self.assertTrue(self.organization1.user_ptr_id in queryset_ids)
        self.assertTrue(self.organization2.user_ptr_id in queryset_ids)
        self.assertTrue(self.team1_1.user_ptr_id in queryset_ids)
        self.assertTrue(self.team2_1.user_ptr_id in queryset_ids)

        # should get all the available users
        queryset_ids = querysets_utils.get_users("user3").values_list("id", flat=True)
        self.assertEqual(len(queryset_ids), 1)
        self.assertTrue(self.user3.id in queryset_ids)

        # should get only the users that are not an organization
        queryset_ids = querysets_utils.get_users(
            "", exclude_organizations=True
        ).values_list("id", flat=True)
        self.assertEqual(len(queryset_ids), 6)
        self.assertTrue(self.user1.id in queryset_ids)
        self.assertTrue(self.user2.id in queryset_ids)
        self.assertTrue(self.user3.id in queryset_ids)
        self.assertTrue(self.user4.id in queryset_ids)
        self.assertTrue(self.team1_1.user_ptr_id in queryset_ids)
        self.assertTrue(self.team2_1.user_ptr_id in queryset_ids)

        # should get only the users that are not a team
        queryset_ids = querysets_utils.get_users("", exclude_teams=True).values_list(
            "id", flat=True
        )
        self.assertEqual(len(queryset_ids), 6)
        self.assertTrue(self.user1.id in queryset_ids)
        self.assertTrue(self.user2.id in queryset_ids)
        self.assertTrue(self.user3.id in queryset_ids)
        self.assertTrue(self.user4.id in queryset_ids)
        self.assertTrue(self.organization1.user_ptr_id in queryset_ids)
        self.assertTrue(self.organization2.user_ptr_id in queryset_ids)

        # should get all the users, that are not members or owners of an organization, or teams within the organization
        queryset_ids = querysets_utils.get_users(
            "", organization=self.organization1
        ).values_list("id", flat=True)
        self.assertEqual(len(queryset_ids), 3)
        self.assertTrue(self.user4.id in queryset_ids)
        self.assertTrue(self.organization2.user_ptr_id in queryset_ids)
        self.assertTrue(self.team1_1.user_ptr_id in queryset_ids)

        # should get all the users, that are not members or owner of a project
        queryset_ids = querysets_utils.get_users("", project=self.project1).values_list(
            "id", flat=True
        )
        self.assertEqual(len(queryset_ids), 5)
        self.assertTrue(self.user2.id in queryset_ids)
        self.assertTrue(self.user3.id in queryset_ids)
        self.assertTrue(self.user4.id in queryset_ids)
        self.assertTrue(self.organization1.user_ptr_id in queryset_ids)
        self.assertTrue(self.organization2.user_ptr_id in queryset_ids)

        # should get all the users, that are not members or owner of a project
        queryset_ids = querysets_utils.get_users("", project=self.project5).values_list(
            "id", flat=True
        )
        self.assertEqual(len(queryset_ids), 6)
        self.assertTrue(self.user1.id in queryset_ids)
        self.assertTrue(self.user2.id in queryset_ids)
        self.assertTrue(self.user3.id in queryset_ids)
        self.assertTrue(self.user4.id in queryset_ids)
        self.assertTrue(self.team1_1.user_ptr_id in queryset_ids)
        self.assertTrue(self.organization2.user_ptr_id in queryset_ids)

        # should get all the users, that are not members or owner of a project and are not an organization
        queryset_ids = querysets_utils.get_users(
            "", project=self.project1, exclude_organizations=True
        ).values_list("id", flat=True)
        self.assertEqual(len(queryset_ids), 3)
        self.assertTrue(self.user2.id in queryset_ids)
        self.assertTrue(self.user3.id in queryset_ids)
        self.assertTrue(self.user4.id in queryset_ids)

    def test_projects_roles_and_role_origins(self):
        """
        Checks user_role and user_role_origin are correctly defined
        """

        roles = ProjectCollaborator.Roles
        role_origins = ProjectQueryset.RoleOrigins

        # fmt: off
        self.assertProjectRole(self.project1, self.user1, roles.ADMIN, role_origins.PROJECTOWNER, True)
        self.assertProjectRole(self.project2, self.user1, roles.ADMIN, role_origins.PROJECTOWNER, True)
        self.assertProjectRole(self.project3, self.user1, None, None, False)
        self.assertProjectRole(self.project4, self.user1, roles.READER, role_origins.PUBLIC, True)
        self.assertProjectRole(self.project5, self.user1, roles.ADMIN, role_origins.ORGANIZATIONOWNER, True)
        self.assertProjectRole(self.project6, self.user1, roles.ADMIN, role_origins.ORGANIZATIONOWNER, True)
        self.assertProjectRole(self.project7, self.user1, roles.REPORTER, role_origins.COLLABORATOR, False)
        self.assertProjectRole(self.project8, self.user1, roles.READER, role_origins.PUBLIC, True)
        self.assertProjectRole(self.project9, self.user1, roles.ADMIN, role_origins.ORGANIZATIONOWNER, True)

        self.assertProjectRole(self.project1, self.user2, None, None, False)
        self.assertProjectRole(self.project2, self.user2, roles.READER, role_origins.PUBLIC, True)
        self.assertProjectRole(self.project3, self.user2, roles.ADMIN, role_origins.PROJECTOWNER, True)
        self.assertProjectRole(self.project4, self.user2, roles.ADMIN, role_origins.PROJECTOWNER, True)
        self.assertProjectRole(self.project5, self.user2, roles.ADMIN, role_origins.ORGANIZATIONADMIN, True)
        self.assertProjectRole(self.project6, self.user2, roles.ADMIN, role_origins.ORGANIZATIONADMIN, True)
        self.assertProjectRole(self.project7, self.user2, None, None, False)
        self.assertProjectRole(self.project8, self.user2, roles.READER, role_origins.PUBLIC, True)
        self.assertProjectRole(self.project9, self.user2, roles.ADMIN, role_origins.ORGANIZATIONADMIN, True)

        self.assertProjectRole(self.project1, self.user3, None, None, False)
        self.assertProjectRole(self.project2, self.user3, roles.READER, role_origins.PUBLIC, True)
        self.assertProjectRole(self.project3, self.user3, None, None, False)
        self.assertProjectRole(self.project4, self.user3, roles.READER, role_origins.PUBLIC, True)
        self.assertProjectRole(self.project5, self.user3, None, None, False)
        self.assertProjectRole(self.project6, self.user3, roles.READER, role_origins.PUBLIC, True)
        self.assertProjectRole(self.project7, self.user3, roles.ADMIN, role_origins.PROJECTOWNER, False)
        self.assertProjectRole(self.project8, self.user3, roles.ADMIN, role_origins.PROJECTOWNER, True)
        self.assertProjectRole(self.project9, self.user3, roles.EDITOR, role_origins.TEAMMEMBER, True)
        # fmt: on

    def test_private_project_memberships(self):
        """Tests for QF-1553 - limit collaboration on private projects"""
        # Shorthands
        roles = ProjectCollaborator.Roles
        role_origins = ProjectQueryset.RoleOrigins

        # Initial user setup
        u = Person.objects.create(username="u")
        o = Organization.objects.create(username="o", organization_owner=u)
        p = Project.objects.create(name="p", owner=u, is_public=True)

        set_subscription(
            u,
            max_premium_collaborators_per_private_project=0,
        )

        u1 = Person.objects.create(username="u1")

        # A public project is readable
        self.assertProjectRole(p, u1, roles.READER, role_origins.PUBLIC, True)

        # Normal collaboration works on a public project
        ProjectCollaborator.objects.create(
            project=p, collaborator=u1, role=roles.MANAGER
        )
        self.assertProjectRole(p, u1, roles.MANAGER, role_origins.COLLABORATOR, True)

        # If project is made private, the collaboration is invalid
        p.is_public = False
        p.save()
        self.assertProjectRole(p, u1, roles.MANAGER, role_origins.COLLABORATOR, False)

        # Making the owner an organization is not enough as user is not member of that org
        p.owner = o
        p.save()
        self.assertProjectRole(p, u1, roles.MANAGER, role_origins.COLLABORATOR, False)

        # As the user must be member of the organization
        OrganizationMember.objects.create(organization=o, member=u1)
        self.assertProjectRole(p, u1, roles.MANAGER, role_origins.COLLABORATOR, True)
