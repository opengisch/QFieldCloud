from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .forms import UserCreationForm, UserChangeForm
from .models import User


class MyUserAdmin(UserAdmin):
    model = User
    add_fieldsets = UserAdmin.add_fieldsets + (
        (None, {'fields': ('type',)}),
    )

    list_display = ['username', 'type', 'email']


admin.site.register(User, MyUserAdmin)
