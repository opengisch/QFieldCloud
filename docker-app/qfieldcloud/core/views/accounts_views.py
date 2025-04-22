from allauth.account.models import EmailAddress
from django.conf import settings
from django.contrib import messages
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _


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
        return HttpResponseRedirect(view_name)


def resend_confirmation_email(request: HttpRequest) -> HttpResponse:
    """
    Resends a confirmation email to a new unverified user.
    """
    if request.method != "POST":
        return redirect_to_referer_or_view(request, "account_login")

    if "account_verified_email" not in request.session:
        messages.error(request, _("No email found."))
        return redirect_to_referer_or_view(request, "account_login")

    email_address = request.session["account_verified_email"]

    if email_address:
        try:
            email_obj = EmailAddress.objects.get(email=email_address)
            email_obj.send_confirmation(request)
            messages.success(
                request,
                _("A new verification email has been sent to {}!").format(
                    email_address
                ),
            )
        except EmailAddress.DoesNotExist:
            messages.error(
                request,
                _("Email {} not found. Please register again.").format(email_address),
            )

    else:
        messages.error(request, _("No email found."))

    return redirect_to_referer_or_view(request, "account_login")
