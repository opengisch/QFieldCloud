from django.http.request import HttpRequest
from django.http.response import (
    Http404,
    HttpResponsePermanentRedirect,
    HttpResponseRedirect,
)
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.http import urlencode
from qfieldcloud.core.models import Project


def redirect_to_admin_project_view(
    request: HttpRequest, username: str, project_name: str
) -> HttpResponseRedirect | HttpResponsePermanentRedirect:
    try:
        project = Project.objects.only("id").get(
            name=project_name,
            owner__username=username,
        )
    except Exception:
        raise Http404()

    return redirect(reverse("admin:core_project_change", args=(project.id,)))


def drf_login_redirect(request: HttpRequest) -> HttpResponseRedirect:
    """
    Redirects to the login page with the next URL.

    Args:
        request: incoming client request.

    Returns:
        A redirect to the login page with the next URL.
    """
    next_url = request.GET.get("next", request.get_full_path())
    login_url = reverse("account_login")
    return redirect(f"{login_url}?{urlencode({'next': next_url})}")
