from allauth.account.adapter import DefaultAccountAdapter
from invitations.adapters import BaseInvitationsAdapter
from qfieldcloud.core.models import Person


class AccountAdapter(DefaultAccountAdapter, BaseInvitationsAdapter):
    """Custom account adapter, inheriting the invitations adapter.

    NOTE Unfortunately there is no way to setup the User model for allauth,
    except changing it globally for everyone. Therefore this adapter tries
    to overcome this limitation by providing custom `new_user` method.
    """

    def new_user(self, request):
        """
        Instantiates a new User instance.
        """
        user = Person()
        return user
