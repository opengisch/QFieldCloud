from django.db import migrations


def generate_user_account(apps, schema_editor):
    User = apps.get_model("core", "User")
    UserAccount = apps.get_model("core", "UserAccount")

    for user in User.objects.filter(useraccount=None):
        UserAccount.objects.create(user=user)


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0015_auto_20210123_0116"),
    ]

    operations = [
        migrations.RunPython(
            generate_user_account, reverse_code=migrations.RunPython.noop
        ),
    ]
