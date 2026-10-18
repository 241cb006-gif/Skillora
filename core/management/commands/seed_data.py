from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from core.models import Batch, Course, Department, Skill, User


class Command(BaseCommand):
    help = 'Seed Sample Skillora data for development.'

    @transaction.atomic
    def handle(self, *args, **options):
        instructor, instructor_created = User.objects.get_or_create(
            username='skillora-demo-teacher',
            defaults={
                'email': 'raja@skillora.edu',
                'first_name': 'Raja',
                'last_name': 'Sharma',
                'role': User.Role.INSTRUCTOR,
                'instructor_approved': True,
            },
        )
        if instructor_created:
            instructor.set_password('Skillora@123')
            instructor.save(update_fields=('password',))
        elif instructor.role != User.Role.INSTRUCTOR or not instructor.instructor_approved:
            raise CommandError('The existing "skillora-demo-teacher" account is not an approved teacher; no account changes were made.')

        faculty, faculty_created = User.objects.get_or_create(
            username='faculty',
            defaults={
                'email': 'faculty@skillora.edu',
                'first_name': 'Ananya',
                'last_name': 'Patel',
                'role': User.Role.FACULTY,
                'is_staff': True,
                'is_superuser': True,
            },
        )
        if faculty_created:
            faculty.set_password('Skillora@123')
            faculty.save(update_fields=('password',))
        elif not faculty.is_college_admin:
            raise CommandError('The existing "faculty" account is not a college administrator; no account changes were made.')

        student, student_created = User.objects.get_or_create(
            username='student01',
            defaults={
                'email': 'student01@skillora.edu',
                'first_name': 'Meera',
                'last_name': 'Iyer',
                'role': User.Role.STUDENT,
            },
        )
        if student_created:
            student.set_password('Skillora@123')
            student.save(update_fields=('password',))
        elif not student.is_student:
            raise CommandError('The existing "student01" account is not a student; no account changes were made.')

        skill1, _ = Skill.objects.get_or_create(
            title='Python Development',
            defaults={'category': 'Technology', 'description': 'Build backend apps and data workflows using Python.', 'created_by': instructor},
        )
        skill2, _ = Skill.objects.get_or_create(
            title='UI/UX Design',
            defaults={'category': 'Design', 'description': 'Design user-friendly interfaces and visual systems.', 'created_by': instructor},
        )

        departments = {}
        for name, slug in (
            ('Computer Applications', 'computer-applications'),
            ('Computer Science', 'computer-science'),
            ('Information Technology', 'information-technology'),
            ('Commerce', 'commerce'),
            ('Management', 'management'),
        ):
            departments[name], _ = Department.objects.get_or_create(
                slug=slug,
                defaults={'name': name},
            )

        course1, _ = Course.objects.get_or_create(
            slug='python-programming-demo',
            defaults={
                'title': 'Python Programming',
                'description': 'A structured introduction to Python for students who want to build web and automation projects.',
                'skill': skill1,
                'instructor': instructor,
                'department': departments['Computer Science'],
                'learning_objectives': 'Learn Python syntax and logic\nBuild small scripts\nCreate a simple Flask project',
                'prerequisites': 'Basic computer literacy',
                'duration_weeks': 4,
                'mode': Course.Mode.ONLINE,
                'schedule': '11:00 AM to 12:00 PM',
                'meeting_link': 'https://meet.google.com/demo-python',
                'max_learners': 25,
                'status': Course.Status.PUBLISHED,
                'approval_status': Course.ApprovalStatus.APPROVED,
                'materials_link': 'https://example.com/python-resources',
            },
        )
        course2, _ = Course.objects.get_or_create(
            slug='ux-thinking-basics-demo',
            defaults={
                'title': 'UX Thinking Basics',
                'description': 'Explore digital product design, research, and prototyping through student-led workshops.',
                'skill': skill2,
                'instructor': instructor,
                'department': departments['Information Technology'],
                'learning_objectives': 'Map user journeys\nCreate wireframes\nTest simple prototypes',
                'prerequisites': 'No prior design experience required',
                'duration_weeks': 6,
                'mode': Course.Mode.OFFLINE,
                'schedule': 'Sat, 10:00 AM',
                'venue': 'Innovation Lab, Block B',
                'max_learners': 18,
                'status': Course.Status.PUBLISHED,
                'approval_status': Course.ApprovalStatus.APPROVED,
            },
        )
        for course in (course1, course2):
            if course.instructor_id != instructor.pk:
                raise CommandError(f'The demo course URL "{course.slug}" belongs to another teacher; no course changes were made.')

        demo_courses = (
            ('Prompt Engineering', 'prompt-engineering', 'Computer Applications', '10:00 AM to 11:00 AM', 'Prompt Engineering', 'Technology'),
            ('Web Design', 'web-design', 'Information Technology', '1:00 PM to 2:00 PM', 'Web Design', 'Design'),
            ('Data Analytics', 'data-analytics', 'Commerce', '2:00 PM to 3:00 PM', 'Data Analytics', 'Commerce'),
            ('Communication Skills', 'communication-skills', 'Management', '3:00 PM to 4:00 PM', 'Communication Skills', 'Management'),
        )
        for title, slug, department_name, schedule, skill_title, category in demo_courses:
            skill, _ = Skill.objects.get_or_create(
                title=skill_title,
                defaults={
                    'category': category,
                    'description': f'Learn practical {skill_title.lower()} skills.',
                    'created_by': instructor,
                },
            )
            course, _ = Course.objects.get_or_create(
                slug=slug,
                defaults={
                    'title': title,
                    'description': f'A practical introduction to {title.lower()}.',
                    'skill': skill,
                    'department': departments[department_name],
                    'instructor': instructor,
                    'duration_weeks': 4,
                    'mode': Course.Mode.ONLINE,
                    'schedule': schedule,
                    'status': Course.Status.PUBLISHED,
                    'approval_status': Course.ApprovalStatus.APPROVED,
                },
            )
            if course.instructor_id != instructor.pk:
                raise CommandError(f'The demo course URL "{course.slug}" belongs to another teacher; no course changes were made.')
            course.department = departments[department_name]
            course.status = Course.Status.PUBLISHED
            course.approval_status = Course.ApprovalStatus.APPROVED
            course.save(update_fields=['department', 'status', 'approval_status'])
            Batch.objects.get_or_create(
                course=course,
                name='Batch 1',
                defaults={
                    'start_date': timezone.localdate() + timedelta(days=7),
                    'schedule': schedule,
                    'mode': course.mode,
                    'venue': course.venue,
                    'meeting_link': course.meeting_link,
                },
            )

        for course in (course1, course2):
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
        self.stdout.write(self.style.SUCCESS(
            'Skillora sample data created. Demo accounts are "faculty", "skillora-demo-teacher", and "student01"; '
            'the command does not reset passwords on existing accounts. Homepage sample profiles are illustrative only.'
        ))
