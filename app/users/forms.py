from django.contrib.auth.forms import UserCreationForm, UserChangeForm
from .models import User


class UserCreationForm(UserCreationForm):

    class Meta:
        model = User
        fields = ('username', 'email', 'type')


class UserChangeForm(UserChangeForm):

    class Meta:
        model = User
        fields = ('username', 'email', 'type')
