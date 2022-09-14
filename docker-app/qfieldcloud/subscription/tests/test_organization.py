import logging

from django.core.exceptions import ValidationError
from qfieldcloud.authentication.models import AuthToken
from qfieldcloud.core.models import (
    Organization,
    OrganizationMember,
    Project,
    ProjectCollaborator,
    ProjectQueryset,
    Team,
    User,
)
from qfieldcloud.core.tests.utils import setup_subscription_plans
from rest_framework.test import APITransactionTestCase

from ..models import Plan

logging.disable(logging.CRITICAL)


class QfcTestCase(APITransactionTestCase):
    def _login(self, user):
        token = AuthToken.objects.get_or_create(user=user)[0]
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token}")

    def setUp(self):
        setup_subscription_plans()

    def assertProjectRole(
        self,
        project,
        user,
        role: ProjectCollaborator.Roles = None,
        origin: ProjectQueryset.RoleOrigins = None,
        is_valid: bool = True,
    ):
        """Asserts that user has give role/origin on project"""
        assert (role is None) == (
            origin is None
        ), "Both role and origin should be either defined or undefined!"

        # Assert user does not have any role
        if role is None:
            with self.assertRaises(User.DoesNotExist):
                User.objects.for_project(project).get(pk=user.pk)

            with self.assertRaises(Project.DoesNotExist):
                Project.objects.for_user(user).get(pk=project.pk)

            return

        # Test on Users
        if origin != ProjectQueryset.RoleOrigins.PUBLIC:
            # The User.objects.for_project queryset is not symetric to Project.objects.for_user
            # because it does not include users that have a role because the project is public.
            u = User.objects.for_project(project).get(pk=user.pk)
            self.assertEqual(u.project_role, role)
            self.assertEqual(u.project_role_origin, origin)
            self.assertEqual(u.project_role_is_valid, is_valid)

        # Test on Project
        p = Project.objects.for_user(user).get(pk=project.pk)
        self.assertEqual(p.user_role, role)
        self.assertEqual(p.user_role_origin, origin)
        self.assertEqual(p.user_role_is_valid, is_valid)

    def test_max_premium_collaborators_per_private_project(self):
        Roles = ProjectCollaborator.Roles
        RoleOrigins = ProjectQueryset.RoleOrigins

        u1 = User.objects.create(username="u1")
        u2 = User.objects.create(username="u2")
        u3 = User.objects.create(username="u3")
        u4 = User.objects.create(username="u4")
        u5 = User.objects.create(username="u5")
        u6 = User.objects.create(username="u6")
        u7 = User.objects.create(username="u7")
        u8 = User.objects.create(username="u8")

        org01 = Organization.objects.create(username="org01", organization_owner=u1)
        org01.useraccount.plan = Plan.objects.create(
            code="test_plan",
            user_type=User.Type.ORGANIZATION,
            is_premium=True,
        )
        org01.useraccount.save()
        org01.members.create(member=u2, role=OrganizationMember.Roles.ADMIN)
        org01.members.create(member=u3, role=OrganizationMember.Roles.MEMBER)
        org01.members.create(member=u4, role=OrganizationMember.Roles.MEMBER)
        org01.members.create(member=u5, role=OrganizationMember.Roles.MEMBER)
        org01.members.create(member=u6, role=OrganizationMember.Roles.MEMBER)
        org01.members.create(member=u7, role=OrganizationMember.Roles.MEMBER)
        org01.members.create(member=u8, role=OrganizationMember.Roles.MEMBER)

        p1 = Project.objects.create(name="p1", owner=org01)

        self.assertProjectRole(p1, u1, Roles.ADMIN, RoleOrigins.ORGANIZATIONOWNER)
        self.assertProjectRole(p1, u2, Roles.ADMIN, RoleOrigins.ORGANIZATIONADMIN)
        self.assertProjectRole(p1, u3, None, None)
        self.assertProjectRole(p1, u4, None, None)
        self.assertProjectRole(p1, u5, None, None)
        self.assertProjectRole(p1, u6, None, None)
        self.assertProjectRole(p1, u7, None, None)
        self.assertProjectRole(p1, u8, None, None)

        # plan.max_premium_collaborators_per_private_project=-1 => add unlimited collaborators
        org01.useraccount.plan.max_premium_collaborators_per_private_project = -1
        org01.useraccount.plan.save()

        # adding an org admin user as project reader collaborator should not affect their admin rights
        p1.collaborators.create(collaborator=u2, role=Roles.READER)

        self.assertProjectRole(p1, u1, Roles.ADMIN, RoleOrigins.ORGANIZATIONOWNER)
        self.assertProjectRole(p1, u2, Roles.ADMIN, RoleOrigins.ORGANIZATIONADMIN)
        self.assertProjectRole(p1, u3, None, None)
        self.assertProjectRole(p1, u4, None, None)
        self.assertProjectRole(p1, u5, None, None)
        self.assertProjectRole(p1, u6, None, None)
        self.assertProjectRole(p1, u7, None, None)
        self.assertProjectRole(p1, u8, None, None)

        # add collaborators via teams
        t_01 = Team.objects.create(username="@org01/t_01", team_organization=org01)
        t_02 = Team.objects.create(username="@org01/t_02", team_organization=org01)
        t_03 = Team.objects.create(username="@org01/t_03", team_organization=org01)
        t_04 = Team.objects.create(username="@org01/t_04", team_organization=org01)
        t_05 = Team.objects.create(username="@org01/t_05", team_organization=org01)

        t_01.members.create(member=u1)
        t_01.members.create(member=u2)
        t_01.members.create(member=u3)
        t_02.members.create(member=u4)
        t_03.members.create(member=u5)
        t_04.members.create(member=u6)
        t_05.members.create(member=u7)

        p1.collaborators.create(collaborator=t_01, role=Roles.READER)
        p1.collaborators.create(collaborator=t_02, role=Roles.REPORTER)
        p1.collaborators.create(collaborator=t_03, role=Roles.EDITOR)
        p1.collaborators.create(collaborator=t_04, role=Roles.MANAGER)
        p1.collaborators.create(collaborator=t_05, role=Roles.ADMIN)

        self.assertProjectRole(p1, u1, Roles.ADMIN, RoleOrigins.ORGANIZATIONOWNER)
        self.assertProjectRole(p1, u2, Roles.ADMIN, RoleOrigins.ORGANIZATIONADMIN)
        self.assertProjectRole(p1, u3, Roles.READER, RoleOrigins.TEAMMEMBER)
        self.assertProjectRole(p1, u4, Roles.REPORTER, RoleOrigins.TEAMMEMBER)
        self.assertProjectRole(p1, u5, Roles.EDITOR, RoleOrigins.TEAMMEMBER)
        self.assertProjectRole(p1, u6, Roles.MANAGER, RoleOrigins.TEAMMEMBER)
        self.assertProjectRole(p1, u7, Roles.ADMIN, RoleOrigins.TEAMMEMBER)
        self.assertProjectRole(p1, u8, None, None)

        # add more collaborators
        p1.collaborators.create(collaborator=u3, role=Roles.READER)
        p1.collaborators.create(collaborator=u4, role=Roles.REPORTER)
        p1.collaborators.create(collaborator=u5, role=Roles.EDITOR)
        p1.collaborators.create(collaborator=u6, role=Roles.MANAGER)
        p1.collaborators.create(collaborator=u7, role=Roles.ADMIN)

        self.assertProjectRole(p1, u1, Roles.ADMIN, RoleOrigins.ORGANIZATIONOWNER)
        self.assertProjectRole(p1, u2, Roles.ADMIN, RoleOrigins.ORGANIZATIONADMIN)
        self.assertProjectRole(p1, u3, Roles.READER, RoleOrigins.COLLABORATOR)
        self.assertProjectRole(p1, u4, Roles.REPORTER, RoleOrigins.COLLABORATOR)
        self.assertProjectRole(p1, u5, Roles.EDITOR, RoleOrigins.COLLABORATOR)
        self.assertProjectRole(p1, u6, Roles.MANAGER, RoleOrigins.COLLABORATOR)
        self.assertProjectRole(p1, u7, Roles.ADMIN, RoleOrigins.COLLABORATOR)
        self.assertProjectRole(p1, u8, None, None)

        # plan.max_premium_collaborators_per_private_project=0
        org01.useraccount.plan.max_premium_collaborators_per_private_project = 0
        org01.useraccount.plan.save()
        self.assertProjectRole(
            p1, u1, Roles.ADMIN, RoleOrigins.ORGANIZATIONOWNER, False
        )
        self.assertProjectRole(
            p1, u2, Roles.ADMIN, RoleOrigins.ORGANIZATIONADMIN, False
        )
        self.assertProjectRole(p1, u3, Roles.READER, RoleOrigins.COLLABORATOR, False)
        self.assertProjectRole(p1, u4, Roles.REPORTER, RoleOrigins.COLLABORATOR, False)
        self.assertProjectRole(p1, u5, Roles.EDITOR, RoleOrigins.COLLABORATOR, False)
        self.assertProjectRole(p1, u6, Roles.MANAGER, RoleOrigins.COLLABORATOR, False)
        self.assertProjectRole(p1, u7, Roles.ADMIN, RoleOrigins.COLLABORATOR, False)
        self.assertProjectRole(p1, u8, None, None)

        # plan.max_premium_collaborators_per_private_project=6
        org01.useraccount.plan.max_premium_collaborators_per_private_project = 6
        org01.useraccount.plan.save()
        self.assertProjectRole(p1, u1, Roles.ADMIN, RoleOrigins.ORGANIZATIONOWNER, True)
        self.assertProjectRole(p1, u2, Roles.ADMIN, RoleOrigins.ORGANIZATIONADMIN, True)
        self.assertProjectRole(p1, u3, Roles.READER, RoleOrigins.COLLABORATOR, True)
        self.assertProjectRole(p1, u4, Roles.REPORTER, RoleOrigins.COLLABORATOR, True)
        self.assertProjectRole(p1, u5, Roles.EDITOR, RoleOrigins.COLLABORATOR, True)
        self.assertProjectRole(p1, u6, Roles.MANAGER, RoleOrigins.COLLABORATOR, True)
        self.assertProjectRole(p1, u7, Roles.ADMIN, RoleOrigins.COLLABORATOR, True)
        self.assertProjectRole(p1, u8, None, None)

        # plan.max_premium_collaborators_per_private_project=6 and is_public=True
        org01.useraccount.plan.max_premium_collaborators_per_private_project = 0
        org01.useraccount.plan.save()
        self.assertProjectRole(
            p1, u1, Roles.ADMIN, RoleOrigins.ORGANIZATIONOWNER, False
        )
        self.assertProjectRole(
            p1, u2, Roles.ADMIN, RoleOrigins.ORGANIZATIONADMIN, False
        )
        self.assertProjectRole(p1, u3, Roles.READER, RoleOrigins.COLLABORATOR, False)
        self.assertProjectRole(p1, u4, Roles.REPORTER, RoleOrigins.COLLABORATOR, False)
        self.assertProjectRole(p1, u5, Roles.EDITOR, RoleOrigins.COLLABORATOR, False)
        self.assertProjectRole(p1, u6, Roles.MANAGER, RoleOrigins.COLLABORATOR, False)
        self.assertProjectRole(p1, u7, Roles.ADMIN, RoleOrigins.COLLABORATOR, False)
        self.assertProjectRole(p1, u8, None, None)
        p1.is_public = True
        p1.save()
        self.assertProjectRole(p1, u1, Roles.ADMIN, RoleOrigins.ORGANIZATIONOWNER, True)
        self.assertProjectRole(p1, u2, Roles.ADMIN, RoleOrigins.ORGANIZATIONADMIN, True)
        self.assertProjectRole(p1, u3, Roles.READER, RoleOrigins.COLLABORATOR, True)
        self.assertProjectRole(p1, u4, Roles.REPORTER, RoleOrigins.COLLABORATOR, True)
        self.assertProjectRole(p1, u5, Roles.EDITOR, RoleOrigins.COLLABORATOR, True)
        self.assertProjectRole(p1, u6, Roles.MANAGER, RoleOrigins.COLLABORATOR, True)
        self.assertProjectRole(p1, u7, Roles.ADMIN, RoleOrigins.COLLABORATOR, True)
        self.assertProjectRole(p1, u8, Roles.READER, RoleOrigins.PUBLIC, True)

    def test_max_organization_members(self):
        """This tests quotas"""

        u1 = User.objects.create(username="u1")
        u2 = User.objects.create(username="u2")
        u3 = User.objects.create(username="u3")
        u4 = User.objects.create(username="u4")
        self._login(u1)

        o1 = Organization.objects.create(username="o1", organization_owner=u1)
        unlimited_plan = Plan.objects.create(
            code="max_organization_members_minus1",
            user_type=User.Type.ORGANIZATION,
            max_organization_members=-1,
        )
        limited_plan = Plan.objects.create(
            code="max_organization_members_plus1",
            user_type=User.Type.ORGANIZATION,
            max_organization_members=1,
        )

        o1.useraccount.plan = unlimited_plan
        o1.useraccount.save()

        OrganizationMember.objects.create(member=u2, organization=o1)
        OrganizationMember.objects.create(member=u3, organization=o1)

        o1.useraccount.plan = limited_plan
        o1.useraccount.save()

        with self.assertRaises(ValidationError):
            OrganizationMember.objects.create(member=u4, organization=o1)

        o2 = Organization.objects.create(username="o2", organization_owner=u1)
        o2.useraccount.plan = limited_plan
        o2.useraccount.save()

        OrganizationMember.objects.create(member=u2, organization=o2)

        with self.assertRaises(ValidationError):
            OrganizationMember.objects.create(member=u3, organization=o2)
