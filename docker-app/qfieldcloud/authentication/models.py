import re
from datetime import datetime, timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import models
from django.utils import timezone
from django.utils.crypto import get_random_string
from django.utils.translation import gettext as _


def generate_token_key() -> str:
    return get_random_string(settings.AUTH_TOKEN_LENGTH)


def generate_token_expires_at() -> datetime:
    return timezone.now() + timedelta(hours=settings.AUTH_TOKEN_EXPIRATION_HOURS)


class AuthToken(models.Model):
    class ClientType(models.TextChoices):
        BROWSER = "browser", _("Browser")
        CLI = "cli", _("Command line interface")
        SDK = "sdk", _("SDK")
        QFIELD = "qfield", _("QField")
        QFIELDSYNC = "qfieldsync", _("QFieldSync")
        WORKER = "worker", _("Worker")
        UNKNOWN = "unknown", _("Unknown")

    @staticmethod
    def guess_client_type(user_agent: str) -> ClientType:
        if not user_agent:
            return AuthToken.ClientType.UNKNOWN

        if user_agent.startswith("qfield|"):
            return AuthToken.ClientType.QFIELD

        if user_agent.startswith("sdk|"):
            return AuthToken.ClientType.SDK

        if user_agent.startswith("cli|"):
            return AuthToken.ClientType.CLI

        if re.search(r" QGIS/[34]\d{4}(\/.*)?$", user_agent):
            return AuthToken.ClientType.QFIELDSYNC

        if re.search(
            r"^Mozilla\/5.0 .+?(AppleWebKit\/\d{1,5}.\d{1,5} \(KHTML, like Gecko\)|Firefox\/[\d\.]{1,5})",
            user_agent,
        ):
            return AuthToken.ClientType.BROWSER

        return AuthToken.ClientType.UNKNOWN

    single_token_clients = [
        ClientType.QFIELD,
        ClientType.QFIELDSYNC,
        ClientType.UNKNOWN,
    ]

    user = models.ForeignKey(
        get_user_model(),
        verbose_name=_("User"),
        related_name="auth_tokens",
        on_delete=models.CASCADE,
    )
    key = models.CharField(
        _("Token"),
        max_length=300,
        db_index=True,
        unique=True,
        default=generate_token_key,
    )
    created_at = models.DateTimeField(_("Created at"), auto_now_add=True)
    expires_at = models.DateTimeField(
        _("Expires at"), default=generate_token_expires_at
    )
    updated_at = models.DateTimeField(_("Updated at"), auto_now=True)
    last_used_at = models.DateTimeField(_("Last used at"), null=True)
    user_agent = models.TextField(_("User-Agent"), blank=True)
    client_type = models.CharField(
        max_length=32, choices=ClientType.choices, default=ClientType.UNKNOWN
    )

    @property
    def is_active(self) -> bool:
        return self.expires_at > timezone.now()

    class Meta:
        verbose_name = _("Token")
        verbose_name_plural = _("Tokens")
        ordering = ("-created_at",)
        indexes = (models.Index(fields=["created_at"]),)

    def __str__(self):
        return self.key

    def save(self, *args, **kwargs) -> None:
        if self.client_type in self.single_token_clients:
            # expire all other tokens
            now = timezone.now()

            AuthToken.objects.filter(
                user=self.user,
                client_type=self.client_type,
                expires_at__gt=now,
            ).exclude(pk=self.pk).update(expires_at=now)

        return super().save(*args, **kwargs)
