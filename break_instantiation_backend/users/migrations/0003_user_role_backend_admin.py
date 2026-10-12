from django.db import migrations
from django.db import models


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0002_user_role"),
    ]

    operations = [
        migrations.AlterField(
            model_name="user",
            name="role",
            field=models.CharField(
                blank=True,
                choices=[
                    ("admin", "Admin"),
                    ("super_admin", "Super Admin"),
                    ("backend_admin", "Backend Admin"),
                ],
                default="",
                max_length=32,
                verbose_name="role",
            ),
        ),
    ]
