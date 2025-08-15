import logging

from rest_framework.test import APITransactionTestCase

from qfieldcloud.authentication.models import AuthToken
from qfieldcloud.core.models import (
    Organization,
    OrganizationMember,
    Person,
    Project,
    ProjectCollaborator,
    ProjectQueryset,
    Team,
)
from qfieldcloud.core.tests.utils import set_subscription, setup_subscription_plans
from qfieldcloud.subscription.exceptions import ReachedMaxOrganizationMembersError

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

    def test_max_premium_collaborators_per_private_project(self):
        Roles = ProjectCollaborator.Roles
        RoleOrigins = ProjectQueryset.RoleOrigins

        u1 = Person.objects.create(username="u1")
        u2 = Person.objects.create(username="u2")
        u3 = Person.objects.create(username="u3")
        u4 = Person.objects.create(username="u4")
        u5 = Person.objects.create(username="u5")
        u6 = Person.objects.create(username="u6")
        u7 = Person.objects.create(username="u7")
        u8 = Person.objects.create(username="u8")

        org01 = Organization.objects.create(username="org01", organization_owner=u1)
        subscription = org01.useraccount.current_subscription
        set_subscription(org01, is_premium=True)
        subscription.save()
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
        subscription.plan.max_premium_collaborators_per_private_project = -1
        subscription.plan.save()

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
        subscription.plan.max_premium_collaborators_per_private_project = 0
        subscription.plan.save()
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
        subscription.plan.max_premium_collaborators_per_private_project = 6
        subscription.plan.save()
        self.assertProjectRole(p1, u1, Roles.ADMIN, RoleOrigins.ORGANIZATIONOWNER, True)
        self.assertProjectRole(p1, u2, Roles.ADMIN, RoleOrigins.ORGANIZATIONADMIN, True)
        self.assertProjectRole(p1, u3, Roles.READER, RoleOrigins.COLLABORATOR, True)
        self.assertProjectRole(p1, u4, Roles.REPORTER, RoleOrigins.COLLABORATOR, True)
        self.assertProjectRole(p1, u5, Roles.EDITOR, RoleOrigins.COLLABORATOR, True)
        self.assertProjectRole(p1, u6, Roles.MANAGER, RoleOrigins.COLLABORATOR, True)
        self.assertProjectRole(p1, u7, Roles.ADMIN, RoleOrigins.COLLABORATOR, True)
        self.assertProjectRole(p1, u8, None, None)

        # plan.max_premium_collaborators_per_private_project=6 and is_public=True
        subscription.plan.max_premium_collaborators_per_private_project = 0
        subscription.plan.save()
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

        u1 = Person.objects.create(username="u1")
        u2 = Person.objects.create(username="u2")
        u3 = Person.objects.create(username="u3")
        u4 = Person.objects.create(username="u4")
        self._login(u1)

        o = Organization.objects.create(username="o1", organization_owner=u1)

        # the unlimited plan, we can add as much members as we want
        set_subscription(o, "minus1", max_organization_members=-1)
        OrganizationMember.objects.create(member=u2, organization=o)
        OrganizationMember.objects.create(member=u3, organization=o)

        # the limited plan allows maximum of 1 member, but there are 2 already
        set_subscription(o, "plus1", max_organization_members=1)

        # cannot add a new member
        with self.assertRaises(ReachedMaxOrganizationMembersError):
            OrganizationMember.objects.create(member=u4, organization=o)

    def test_max_organization_members_raises_when_adding_new_member_over_limit(self):
        u1 = Person.objects.create(username="u1")
        u2 = Person.objects.create(username="u2")
        u3 = Person.objects.create(username="u3")
        o = Organization.objects.create(username="o2", organization_owner=u1)

        set_subscription(o, max_organization_members=1)

        OrganizationMember.objects.create(member=u2, organization=o)

        with self.assertRaises(ReachedMaxOrganizationMembersError):
            OrganizationMember.objects.create(member=u3, organization=o)
