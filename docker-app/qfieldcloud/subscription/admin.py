from datetime import timedelta
from typing import Iterable

from django import forms
from django.contrib import admin
from django.http import HttpRequest
from django.utils import timezone
from django.utils.translation import gettext as _

from qfieldcloud.core.admin import (
    QFieldCloudModelAdmin,
    model_admin_url,
    qfc_admin_site,
)
from qfieldcloud.subscription.models import PackageType, Plan, Subscription


class PlanAdmin(admin.ModelAdmin):
    list_display = [
        "code",
        "is_default",
        "is_public",
        "display_name",
        "storage_mb",
        "job_minutes",
    ]


class PackageTypeAdmin(admin.ModelAdmin):
    list_display = [
        "code",
        "is_public",
        "display_name",
        "type",
        "unit_amount",
        "unit_label",
    ]


class SubscriptionPeriodFilter(admin.SimpleListFilter):
    title = _("Period")

    parameter_name = "period"

    def lookups(self, request, model_admin):
        return (
            ("current", _("Current")),
            # TODO implement past period filter
            # ('past', _('Past')),
        )

    def queryset(self, request, queryset):
        if self.value() == "current":
            return queryset.current()

        return queryset


class ActiveUntilFilter(admin.SimpleListFilter):
    title = _("expiration date")
    parameter_name = "active_until"

    def lookups(self, request, model_admin):
        return [
            ("1", _("Next week")),
            ("2", _("Next 2 weeks")),
            ("4", _("Next 4 weeks")),
        ]

    def queryset(self, request, queryset):
        if self.value():
            now = timezone.now()
            future_date = now + timedelta(weeks=int(self.value()))
            return queryset.filter(active_until__range=(now, future_date))


class SubscriptionModelForm(forms.ModelForm):
    class Meta:
        model = Subscription
        fields = "__all__"

    additional_storage_quantity = forms.IntegerField(
        help_text=_("Current additional storage quantity."),
        min_value=0,
        initial=0,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        instance = kwargs.get("instance", None)
        if instance:
            subscription = Subscription.objects.get(pk=instance.pk)

            active_storage_field = self.fields["additional_storage_quantity"]
            active_storage_field.initial = subscription.active_storage_package_quantity

    def save(self, commit=True):
        """
        Adds an extra field, 'aditional_storage_quantity' allowing, from the `SubscriptionAdmin` view, to increase
        the plan's storage capacity.
        """
        additional_storage_quantity = self.cleaned_data.get(
            "additional_storage_quantity", None
        )

        if (
            not hasattr(self.instance, "active_storage_package_quantity")
            or additional_storage_quantity
            == self.instance.active_storage_package_quantity
        ):
            return super().save(commit=commit)
        else:
            self.instance.set_package_quantity(
                package_type=PackageType.get_storage_package_type(),
                quantity=additional_storage_quantity,
            )
            return super().save(commit=commit)


class SubscriptionAdmin(QFieldCloudModelAdmin):
    form = SubscriptionModelForm

    fields = (
        "plan",
        "account",
        "status",
        "active_since",
        "active_until",
        "billing_cycle_anchor_at",
        "current_period_since",
        "current_period_until",
        "notes",
        "created_at",
        "created_by",
        "updated_at",
        "requested_cancel_at",
    )

    list_display = (
        "id",
        "account__link",
        "account__user__email",
        "plan__link",
        "active_since",
        "active_until",
        "is_active",
        "status",
    )

    list_filter = (
        SubscriptionPeriodFilter,
        "status",
        "plan",
        ActiveUntilFilter,
    )

    readonly_fields = (
        "created_by",
        "created_at",
        "updated_at",
        "requested_cancel_at",
    )

    autocomplete_fields = ("account",)

    search_fields = (
        "id",
        "account__user__email__iexact",
        "account__user__username__iexact",
    )

    def get_fields(
        self, request: HttpRequest, obj: Subscription | None = None
    ) -> Iterable[str]:
        if obj is not None:
            return (
                "plan__link",
                "account__link",
                "promotion__link",
                *self.fields[3:],
            )

        return self.fields

    def get_readonly_fields(
        self, request: HttpRequest, obj: Subscription | None = None
    ) -> Iterable[str]:
        if obj is not None:
            return (
                *self.readonly_fields,
                "plan",
                "account",
                "plan__link",
                "account__link",
                "promotion__link",
            )

        return self.readonly_fields

    @admin.display(description=_("Account"))
    def account__link(self, instance):
        return model_admin_url(
            instance.account.user, instance.account.user.username_with_full_name
        )

    # NOTE if the property is computed property, it cannot be `list_display`/`readonly_fields`
    @admin.display(description=_("Active"), boolean=True)
    def is_active(self, instance):
        return instance.is_active

    @admin.display(description=_("Plan"))
    def plan__link(self, instance):
        return model_admin_url(instance.plan, str(instance.plan))

    @admin.display(description=_("Promotion"))
    def promotion__link(self, instance):
        return model_admin_url(instance.promotion, str(instance.promotion))

    def get_queryset(self, request: HttpRequest):
        return super().get_queryset(request).select_related("account__user", "plan")

    @admin.display(description=_("Subscriber email"))
    def account__user__email(self, instance):
        return instance.account.user.email

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by_id = obj.created_by_id or request.user.id

        return super().save_model(request, obj, form, change)


qfc_admin_site.register(Plan, PlanAdmin)
qfc_admin_site.register(PackageType, PackageTypeAdmin)
qfc_admin_site.register(Subscription, SubscriptionAdmin)
