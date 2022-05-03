import logging

from qfieldcloud.authentication.models import AuthToken
from qfieldcloud.core import querysets_utils
from qfieldcloud.core.models import (
    Organization,
    OrganizationMember,
    Project,
    ProjectCollaborator,
    ProjectQueryset,
    Team,
    TeamMember,
    User,
)
from rest_framework.test import APITestCase

logging.disable(logging.CRITICAL)


class QfcTestCase(APITestCase):
    def setUp(self):
        # user1 owns p1 and p2
        # user1 owns o1
        # user1 collaborates on p7
        self.user1 = User.objects.create_user(username="user1", password="abc123")
        self.token1 = AuthToken.objects.get_or_create(user=self.user1)[0]

        # user2 owns p3 and p4
        # user2 admins o1
        self.user2 = User.objects.create_user(username="user2", password="abc123")
        self.token2 = AuthToken.objects.get_or_create(user=self.user2)[0]

        # user2 owns p7 and p8
        # user2 is member of o1
        self.user3 = User.objects.create_user(username="user3", password="abc123")
        self.token3 = AuthToken.objects.get_or_create(user=self.user3)[0]

        # organization1 owns p4 and p5
        self.organization1 = Organization.objects.create(
            username="organization1",
            password="abc123",
            user_type=2,
            organization_owner=self.user1,
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

        self.team1 = Team.objects.create(
            username="team1",
            password="abc123",
            user_type=User.TYPE_TEAM,
            team_organization=self.organization1,
        )

        self.teammembership1 = TeamMember.objects.create(
            team=self.team1,
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
            collaborator=self.team1,
            role=ProjectCollaborator.Roles.EDITOR,
        )

    def test_get_users(self):
        # should get all the available users
        queryset = querysets_utils.get_users("")
        self.assertEqual(len(queryset), 5)
        self.assertTrue(self.user1 in queryset)
        self.assertTrue(self.user2 in queryset)
        self.assertTrue(self.user3 in queryset)
        self.assertTrue(self.organization1.user_ptr in queryset)
        self.assertTrue(self.team1.user_ptr in queryset)

        # should get all the available users
        queryset = querysets_utils.get_users("user3")
        self.assertEqual(len(queryset), 1)
        self.assertTrue(self.user3 in queryset)

        # should get only the users that are not an organization
        queryset = querysets_utils.get_users("", exclude_organizations=True)
        self.assertEqual(len(queryset), 4)
        self.assertTrue(self.user1 in queryset)
        self.assertTrue(self.user2 in queryset)
        self.assertTrue(self.user3 in queryset)
        self.assertTrue(self.team1.user_ptr in queryset)

        # should get only the users that are not a team
        queryset = querysets_utils.get_users("", exclude_teams=True)
        self.assertEqual(len(queryset), 4)
        self.assertTrue(self.user1 in queryset)
        self.assertTrue(self.user2 in queryset)
        self.assertTrue(self.user3 in queryset)
        self.assertTrue(self.organization1.user_ptr in queryset)

        # should get all the users, that are not members or owners of an organization
        queryset = querysets_utils.get_users("", organization=self.organization1)
        self.assertEqual(len(queryset), 1)

        # should get all the users, that are not members or owner of a project
        queryset = querysets_utils.get_users("", project=self.project1)
        self.assertEqual(len(queryset), 3)
        self.assertTrue(self.user2 in queryset)
        self.assertTrue(self.user3 in queryset)
        self.assertTrue(self.organization1.user_ptr in queryset)

        # should get all the users, that are not members or owner of a project
        queryset = querysets_utils.get_users("", project=self.project5)
        self.assertEqual(len(queryset), 4)
        self.assertTrue(self.user1 in queryset)
        self.assertTrue(self.user2 in queryset)
        self.assertTrue(self.user3 in queryset)
        self.assertTrue(self.team1.user_ptr in queryset)

        # should get all the users, that are not members or owner of a project and are not an organization
        queryset = querysets_utils.get_users(
            "", project=self.project1, exclude_organizations=True
        )
        self.assertEqual(len(queryset), 2)
        self.assertTrue(self.user2 in queryset)
        self.assertTrue(self.user3 in queryset)

    def test_projects_roles_and_role_origins(self):
        """
        Checks user_role and user_role_origin are correctly defined
        """

        def p(proj, user):
            return Project.objects.for_user(user).get(pk=proj.pk)

        # fmt: off
        self.assertEqual(p(self.project1, self.user1).user_role, ProjectCollaborator.Roles.ADMIN)
        self.assertEqual(p(self.project1, self.user1).user_role_origin, ProjectQueryset.RoleOrigins.PROJECTOWNER.value)
        self.assertEqual(p(self.project2, self.user1).user_role, ProjectCollaborator.Roles.ADMIN)
        self.assertEqual(p(self.project2, self.user1).user_role_origin, ProjectQueryset.RoleOrigins.PROJECTOWNER.value)
        with self.assertRaises(Project.DoesNotExist):
            p(self.project3, self.user1)
        self.assertEqual(p(self.project4, self.user1).user_role, ProjectCollaborator.Roles.READER)
        self.assertEqual(p(self.project4, self.user1).user_role_origin, ProjectQueryset.RoleOrigins.PUBLIC.value)
        self.assertEqual(p(self.project5, self.user1).user_role, ProjectCollaborator.Roles.ADMIN)
        self.assertEqual(p(self.project5, self.user1).user_role_origin, ProjectQueryset.RoleOrigins.ORGANIZATIONOWNER.value)
        self.assertEqual(p(self.project6, self.user1).user_role, ProjectCollaborator.Roles.ADMIN)
        self.assertEqual(p(self.project6, self.user1).user_role_origin, ProjectQueryset.RoleOrigins.ORGANIZATIONOWNER.value)
        with self.assertRaises(Project.DoesNotExist):
            p(self.project7, self.user1)
        self.assertEqual(p(self.project8, self.user1).user_role, ProjectCollaborator.Roles.READER)
        self.assertEqual(p(self.project8, self.user1).user_role_origin, ProjectQueryset.RoleOrigins.PUBLIC.value)
        self.assertEqual(p(self.project9, self.user1).user_role, ProjectCollaborator.Roles.ADMIN)
        self.assertEqual(p(self.project9, self.user1).user_role_origin, ProjectQueryset.RoleOrigins.ORGANIZATIONOWNER.value)

        with self.assertRaises(Project.DoesNotExist):
            p(self.project1, self.user2)
        self.assertEqual(p(self.project2, self.user2).user_role, ProjectCollaborator.Roles.READER)
        self.assertEqual(p(self.project2, self.user2).user_role_origin, ProjectQueryset.RoleOrigins.PUBLIC.value)
        self.assertEqual(p(self.project3, self.user2).user_role, ProjectCollaborator.Roles.ADMIN)
        self.assertEqual(p(self.project3, self.user2).user_role_origin, ProjectQueryset.RoleOrigins.PROJECTOWNER.value)
        self.assertEqual(p(self.project4, self.user2).user_role, ProjectCollaborator.Roles.ADMIN)
        self.assertEqual(p(self.project4, self.user2).user_role_origin, ProjectQueryset.RoleOrigins.PROJECTOWNER.value)
        self.assertEqual(p(self.project5, self.user2).user_role, ProjectCollaborator.Roles.ADMIN)
        self.assertEqual(p(self.project5, self.user2).user_role_origin, ProjectQueryset.RoleOrigins.ORGANIZATIONADMIN.value)
        self.assertEqual(p(self.project6, self.user2).user_role, ProjectCollaborator.Roles.ADMIN)
        self.assertEqual(p(self.project6, self.user2).user_role_origin, ProjectQueryset.RoleOrigins.ORGANIZATIONADMIN.value)
        with self.assertRaises(Project.DoesNotExist):
            p(self.project7, self.user2)
        self.assertEqual(p(self.project8, self.user2).user_role, ProjectCollaborator.Roles.READER)
        self.assertEqual(p(self.project8, self.user2).user_role_origin, ProjectQueryset.RoleOrigins.PUBLIC.value)
        self.assertEqual(p(self.project9, self.user2).user_role, ProjectCollaborator.Roles.ADMIN)
        self.assertEqual(p(self.project9, self.user2).user_role_origin, ProjectQueryset.RoleOrigins.ORGANIZATIONADMIN.value)

        with self.assertRaises(Project.DoesNotExist):
            p(self.project1, self.user3)
        self.assertEqual(p(self.project2, self.user3).user_role, ProjectCollaborator.Roles.READER)
        self.assertEqual(p(self.project2, self.user3).user_role_origin, ProjectQueryset.RoleOrigins.PUBLIC.value)
        with self.assertRaises(Project.DoesNotExist):
            p(self.project3, self.user3)
        self.assertEqual(p(self.project4, self.user3).user_role, ProjectCollaborator.Roles.READER)
        self.assertEqual(p(self.project4, self.user3).user_role_origin, ProjectQueryset.RoleOrigins.PUBLIC.value)
        with self.assertRaises(Project.DoesNotExist):
            p(self.project5, self.user3)
        self.assertEqual(p(self.project6, self.user3).user_role, ProjectCollaborator.Roles.READER)
        self.assertEqual(p(self.project6, self.user3).user_role_origin, ProjectQueryset.RoleOrigins.PUBLIC.value)
        self.assertEqual(p(self.project7, self.user3).user_role, ProjectCollaborator.Roles.ADMIN)
        self.assertEqual(p(self.project7, self.user3).user_role_origin, ProjectQueryset.RoleOrigins.PROJECTOWNER.value)
        self.assertEqual(p(self.project8, self.user3).user_role, ProjectCollaborator.Roles.ADMIN)
        self.assertEqual(p(self.project8, self.user3).user_role_origin, ProjectQueryset.RoleOrigins.PROJECTOWNER.value)
        self.assertEqual(p(self.project9, self.user3).user_role, ProjectCollaborator.Roles.EDITOR)
        self.assertEqual(p(self.project9, self.user3).user_role_origin, ProjectQueryset.RoleOrigins.TEAMMEMBER.value)
        # fmt: on

    def test_user_roles_and_role_origins(self):
        """
        Checks project_role and project_role_origin are correctly defined
        """

        def p(proj, user):
            return User.objects.for_project(proj).get(pk=user.pk)

        # fmt: off
        self.assertEqual(p(self.project1, self.user1).project_role, ProjectCollaborator.Roles.ADMIN)
        self.assertEqual(p(self.project1, self.user1).project_role_origin, ProjectQueryset.RoleOrigins.PROJECTOWNER.value)
        self.assertEqual(p(self.project2, self.user1).project_role, ProjectCollaborator.Roles.ADMIN)
        self.assertEqual(p(self.project2, self.user1).project_role_origin, ProjectQueryset.RoleOrigins.PROJECTOWNER.value)
        with self.assertRaises(User.DoesNotExist):
            p(self.project3, self.user1)
        with self.assertRaises(User.DoesNotExist):
            p(self.project4, self.user1)
        self.assertEqual(p(self.project5, self.user1).project_role, ProjectCollaborator.Roles.ADMIN)
        self.assertEqual(p(self.project5, self.user1).project_role_origin, ProjectQueryset.RoleOrigins.ORGANIZATIONOWNER.value)
        self.assertEqual(p(self.project6, self.user1).project_role, ProjectCollaborator.Roles.ADMIN)
        self.assertEqual(p(self.project6, self.user1).project_role_origin, ProjectQueryset.RoleOrigins.ORGANIZATIONOWNER.value)
        with self.assertRaises(User.DoesNotExist):
            p(self.project7, self.user1)
        with self.assertRaises(User.DoesNotExist):
            p(self.project8, self.user1)
        self.assertEqual(p(self.project9, self.user1).project_role, ProjectCollaborator.Roles.ADMIN)
        self.assertEqual(p(self.project9, self.user1).project_role_origin, ProjectQueryset.RoleOrigins.ORGANIZATIONOWNER.value)

        with self.assertRaises(User.DoesNotExist):
            p(self.project1, self.user2)
        with self.assertRaises(User.DoesNotExist):
            p(self.project2, self.user2)
        self.assertEqual(p(self.project3, self.user2).project_role, ProjectCollaborator.Roles.ADMIN)
        self.assertEqual(p(self.project3, self.user2).project_role_origin, ProjectQueryset.RoleOrigins.PROJECTOWNER.value)
        self.assertEqual(p(self.project4, self.user2).project_role, ProjectCollaborator.Roles.ADMIN)
        self.assertEqual(p(self.project4, self.user2).project_role_origin, ProjectQueryset.RoleOrigins.PROJECTOWNER.value)
        self.assertEqual(p(self.project5, self.user2).project_role, ProjectCollaborator.Roles.ADMIN)
        self.assertEqual(p(self.project5, self.user2).project_role_origin, ProjectQueryset.RoleOrigins.ORGANIZATIONADMIN.value)
        self.assertEqual(p(self.project6, self.user2).project_role, ProjectCollaborator.Roles.ADMIN)
        self.assertEqual(p(self.project6, self.user2).project_role_origin, ProjectQueryset.RoleOrigins.ORGANIZATIONADMIN.value)
        with self.assertRaises(User.DoesNotExist):
            p(self.project7, self.user2)
        with self.assertRaises(User.DoesNotExist):
            p(self.project8, self.user2)
        self.assertEqual(p(self.project9, self.user2).project_role, ProjectCollaborator.Roles.ADMIN)
        self.assertEqual(p(self.project9, self.user2).project_role_origin, ProjectQueryset.RoleOrigins.ORGANIZATIONADMIN.value)

        with self.assertRaises(User.DoesNotExist):
            p(self.project1, self.user3)
        with self.assertRaises(User.DoesNotExist):
            p(self.project2, self.user3)
        with self.assertRaises(User.DoesNotExist):
            p(self.project3, self.user3)
        with self.assertRaises(User.DoesNotExist):
            p(self.project4, self.user3)
        with self.assertRaises(User.DoesNotExist):
            p(self.project5, self.user3)
        with self.assertRaises(User.DoesNotExist):
            p(self.project6, self.user3)
        self.assertEqual(p(self.project7, self.user3).project_role, ProjectCollaborator.Roles.ADMIN)
        self.assertEqual(p(self.project7, self.user3).project_role_origin, ProjectQueryset.RoleOrigins.PROJECTOWNER.value)
        self.assertEqual(p(self.project8, self.user3).project_role, ProjectCollaborator.Roles.ADMIN)
        self.assertEqual(p(self.project8, self.user3).project_role_origin, ProjectQueryset.RoleOrigins.PROJECTOWNER.value)
        self.assertEqual(p(self.project9, self.user3).project_role, ProjectCollaborator.Roles.EDITOR)
        self.assertEqual(p(self.project9, self.user3).project_role_origin, ProjectQueryset.RoleOrigins.TEAMMEMBER.value)
        # fmt: on

    def test_private_project_memberships(self):
        """Tests for QF-1553 - limit collaboration on private projects"""

        def assert_no_role(p, u):
            """Asserts that user has no role on project"""
            # Test on Users
            with self.assertRaises(User.DoesNotExist):
                User.objects.for_project(p).get(pk=u.pk)

            # Test on Project
            with self.assertRaises(Project.DoesNotExist):
                Project.objects.for_user(u).get(pk=p.pk)

        def assert_role(p, u, expected_role, expected_origin):
            """Asserts that user has give role/origin on project"""
            # Test on Users
            if expected_origin != origins.PUBLIC:
                # The User.objects.for_project queryset is not symetric to Project.objects.for_user
                # because it does not include users that have a role because the project is public.
                user = User.objects.for_project(p).get(pk=u.pk)
                self.assertEqual(user.project_role, expected_role)
                self.assertEqual(user.project_role_origin, expected_origin.value)

            # Test on Project
            project = Project.objects.for_user(u).get(pk=p.pk)
            self.assertEqual(project.user_role, expected_role)
            self.assertEqual(project.user_role_origin, expected_origin.value)

        # Shorthands
        roles = ProjectCollaborator.Roles
        origins = ProjectQueryset.RoleOrigins

        # Initial user setup
        u = User.objects.create(username="u")
        o = Organization.objects.create(username="o", organization_owner=u)
        p = Project.objects.create(name="p", owner=u, is_public=True)

        u1 = User.objects.create(username="u1")

        # A public project is readable
        assert_role(p, u1, roles.READER, origins.PUBLIC)

        # Normal collaboration works on a public project
        ProjectCollaborator.objects.create(
            project=p, collaborator=u1, role=roles.MANAGER
        )
        assert_role(p, u1, roles.MANAGER, origins.COLLABORATOR)

        # If project is made private, the collaboration is invalid
        p.is_public = False
        p.save()
        assert_no_role(p, u1)

        # Making the owner an organisation is not enough as user is not member of that org
        p.owner = o
        p.save()
        assert_no_role(p, u1)

        # As the user must be member of the organisation
        OrganizationMember.objects.create(organization=o, member=u1)
        assert_role(p, u1, roles.MANAGER, origins.COLLABORATOR)
