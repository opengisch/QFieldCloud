from allauth.account.models import EmailAddress
from allauth.core import ratelimit
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _

User = get_user_model()


def redirect_to_referer_or_view(
    request: HttpRequest, view_name: str, *view_args, **view_kwargs
) -> HttpResponseRedirect:
    """
    Redirects a request to a referer provided by a client.

    If no referer provided or the referer is not safe,
    this will create a redirection to a default view.

    Args:
        request: incoming client request.
        view_name: name of the view to redirect to.

    Returns:
        client redirect http response.
    """
    referer = request.headers.get("referer", "")
    if url_has_allowed_host_and_scheme(referer, allowed_hosts=settings.ALLOWED_HOSTS):
        return HttpResponseRedirect(referer)
    else:
        return HttpResponseRedirect(
            reverse(view_name, args=view_args, kwargs=view_kwargs)
        )


def resend_confirmation_email(request: HttpRequest) -> HttpResponse:
    """Resends a confirmation email to a new unverified user."""
    if request.method != "POST":
        return redirect_to_referer_or_view(request, "account_login")

    email_address = request.session.get("account_verified_email")
    if not email_address:
        messages.error(request, _("No email found."))

        return redirect_to_referer_or_view(request, "account_login")

    try:
        email_obj = EmailAddress.objects.get(email=email_address)
    except EmailAddress.DoesNotExist:
        messages.error(
            request,
            # Do not show the email to prevent leaking of email by hijacking a session.
            _("Email not found. Please go through sign-up process again."),
        )

        return redirect_to_referer_or_view(request, "account_login")

    allowed = ratelimit.consume(request, action="confirm_email", key=email_address)
    if not allowed:
        messages.error(
            request, _("Please wait before requesting another verification email.")
        )

        return redirect_to_referer_or_view(request, "account_login")

    email_obj.send_confirmation(request)
    messages.success(
        request,
        _("A new verification email has been sent to {}!").format(email_address),
    )

    return redirect_to_referer_or_view(request, "account_login")
