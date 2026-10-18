from datetime import timedelta

from django.db import migrations
from django.utils import timezone


DEPARTMENTS = (
    ('Computer Applications', 'computer-applications'),
    ('Computer Science', 'computer-science'),
    ('Information Technology', 'information-technology'),
    ('Commerce', 'commerce'),
    ('Management', 'management'),
)


def seed_departments_and_batches(apps, schema_editor):
    Department = apps.get_model('core', 'Department')
    Course = apps.get_model('core', 'Course')
    Batch = apps.get_model('core', 'Batch')
    departments = {
        name: Department.objects.get_or_create(name=name, defaults={'slug': slug})[0]
        for name, slug in DEPARTMENTS
    }
    assignments = {
        'python-for-beginners': 'Computer Science',
        'ux-thinking-basics': 'Information Technology',
        'prompt-engineering': 'Computer Applications',
        'web-design': 'Information Technology',
        'data-analytics': 'Commerce',
        'communication-skills': 'Management',
    }
    for course in Course.objects.all():
        department_name = assignments.get(course.slug, 'Computer Science')
        if course.department_id is None:
            course.department = departments[department_name]
            course.save(update_fields=('department',))
        if course.approval_status == 'approved' and course.status == 'published':
            Batch.objects.get_or_create(
                course=course,
                name='Batch 1',
                defaults={
                    'start_date': timezone.localdate() + timedelta(days=7),
                    'schedule': course.schedule,
                    'mode': course.mode,
                    'venue': course.venue,
                    'meeting_link': course.meeting_link,
                },
            )


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0005_department_certificaterequest_completion_date_batch_and_more'),
    ]

    operations = [
        migrations.RunPython(seed_departments_and_batches, migrations.RunPython.noop),
    ]
