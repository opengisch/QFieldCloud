from django.contrib import admin
from django.contrib.sites.models import Site
from django.contrib.auth.models import Group
from qfieldcloud.core.models import (
    User, Organization, OrganizationMember, Project, ProjectCollaborator,
    UserAccount, Delta)
from allauth.socialaccount.models import SocialAccount, SocialApp, SocialToken


class UserAdmin(admin.ModelAdmin):
    list_display = (
        'username', 'first_name', 'last_name', 'email',
        'is_superuser', 'is_staff', 'is_active', 'date_joined',
        'user_type', 'useraccount')
    list_filter = (
        'user_type', 'useraccount')


class ProjectAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'name', 'owner', 'private', 'description',
        'created_at', 'updated_at')
    list_filter = (
        'private',)
    fields = (
        'name', 'description', 'private', 'owner', 'storage_size')
    readonly_fields = ('storage_size',)


class DeltaAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'project', 'status', 'created_at', 'updated_at')
    list_filter = (
        'status',)
    actions = None
    readonly_fields = ('project', 'content', 'output')

    # This will disable add functionality
    def has_add_permission(self, request):
        return False

    # TODO: add a custom action to re-apply the deltafile


class UserAccountAdmin(admin.ModelAdmin):
    list_display = (
        'user', 'account_type', 'storage_limit_mb', 'db_limit_mb',
        'synchronizations_per_months'
    )
    list_filter = (
        'account_type',)


admin.site.register(User, UserAdmin)
admin.site.register(Project, ProjectAdmin)
admin.site.register(Delta, DeltaAdmin)
admin.site.register(UserAccount, UserAccountAdmin)

admin.site.register(Organization)
admin.site.register(OrganizationMember)
admin.site.register(ProjectCollaborator)

admin.site.unregister(Group)
admin.site.unregister(SocialAccount)
admin.site.unregister(SocialApp)
admin.site.unregister(SocialToken)
