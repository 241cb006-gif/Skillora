from django.db import migrations


def remove_legacy_instructor_staff_access(apps, schema_editor):
    user_model = apps.get_model('core', 'User')
    user_model.objects.filter(
        role='instructor',
        is_staff=True,
        is_superuser=False,
    ).update(is_staff=False)


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0003_alter_attendancerecord_unique_together'),
    ]

    operations = [
        migrations.RunPython(
            remove_legacy_instructor_staff_access,
            migrations.RunPython.noop,
        ),
    ]
