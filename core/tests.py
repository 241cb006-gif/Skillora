from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .forms import CustomUserCreationForm
from .models import AttendanceRecord, Batch, CertificateRequest, Course, CourseApplication, Department, Enrollment, SessionRequest, Skill, StudentNotification


User = get_user_model()


class SkilloraHomepageTests(TestCase):
    def test_homepage_uses_official_college_identity_without_fake_testimonials(self):
        response = self.client.get(reverse('home'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'core/srcw-logo.svg')
        self.assertContains(response, 'core/srcw-home-banner.png')
        self.assertContains(response, 'core/srcw-approved-classroom.png')
        self.assertNotContains(response, 'core/srcw-student-learning.jpg')
        self.assertContains(response, 'Ask Skillora')
        self.assertContains(response, 'Sri Ramakrishna College of Arts and Science for Women')
        self.assertContains(response, 'Student-to-Student Learning')
        self.assertContains(response, 'Learn from students. Share what you know.')
        self.assertContains(response, 'Become a Student Mentor')
        self.assertContains(response, 'Teach a Skill')
        self.assertContains(response, 'Explore Courses')
        self.assertNotContains(response, 'Approved campus photograph pending')
        self.assertNotContains(response, 'Sample testimonial')
        for sample_name in ('Charishma P.', 'Nisha R.', 'Priya S.', 'Divya K.', 'Harini M.'):
            self.assertContains(response, sample_name)
        self.assertContains(response, 'Sample student records')


class SkilloraGuideTests(TestCase):
    def setUp(self):
        self.teacher = User.objects.create_user(
            username='guide-teacher',
            first_name='Guide',
            last_name='Teacher',
            password='test-password-123',
            role=User.Role.INSTRUCTOR,
            instructor_approved=True,
        )
        self.department = Department.objects.create(name='Guide Department', slug='guide-department')
        skill = Skill.objects.create(
            title='Guide Python',
            category='Technology',
            description='Learn Python.',
            created_by=self.teacher,
        )
        self.course = Course.objects.create(
            title='Guide Python Basics',
            slug='guide-python',
            description='A guide course.',
            skill=skill,
            instructor=self.teacher,
            department=self.department,
            schedule='Tuesday, 10:00 AM',
            status=Course.Status.PUBLISHED,
            approval_status=Course.ApprovalStatus.APPROVED,
        )
        self.batch = Batch.objects.create(
            course=self.course,
            name='Guide batch',
            start_date=timezone.localdate() + timedelta(days=7),
            schedule='Tuesday, 10:00 AM',
            mode=Course.Mode.ONLINE,
        )

    def test_guest_chatbot_is_on_public_pages_and_answers_course_questions(self):
        homepage = self.client.get(reverse('home'))
        self.assertContains(homepage, 'Skillora Guide')
        self.assertContains(homepage, 'skillora-chat-window')
        self.assertContains(homepage, 'New chat')
        self.assertContains(homepage, 'Thinking')
        with patch('core.assistant.call_openai', return_value='Guide Python Basics meets Tuesday at 10:00 AM.') as call:
            with override_settings(OPENAI_API_KEY='test-openai-key'):
                response = self.client.post(reverse('assistant_chat'), {'message': 'What are the class timings?'})

        self.assertEqual(response.status_code, 200)
        self.assertIn('Tuesday at 10:00 AM', response.json()['reply'])
        self.assertIn('Guide Python Basics', call.call_args.args[0][0]['content'])

    def test_guest_chatbot_answers_department_application_attendance_and_certificate_questions(self):
        for question in (
            'What departments are available?',
            'How do I apply for a class?',
            'How is attendance recorded?',
            'How do certificates work?',
        ):
            with self.subTest(question=question):
                with patch('core.assistant.call_openai', return_value=f'Answer about {question}.'):
                    with override_settings(OPENAI_API_KEY='test-openai-key'):
                        response = self.client.post(reverse('assistant_chat'), {'message': question})
                self.assertEqual(response.status_code, 200)
                self.assertIn(question, response.json()['reply'])

    def test_student_receives_only_their_application_status(self):
        student = User.objects.create_user(
            username='guide-student',
            email='guide-student@example.edu',
            password='test-password-123',
        )
        CourseApplication.objects.create(
            student=student,
            course=self.course,
            batch=self.batch,
            department=self.department,
            applicant_name='Guide Student',
            college_email=student.email,
            preferred_mode=Course.Mode.ONLINE,
        )
        other_student = User.objects.create_user(username='other-guide-student', password='test-password-123')
        CourseApplication.objects.create(
            student=other_student,
            course=self.course,
            batch=self.batch,
            department=self.department,
            applicant_name='Private Application Record',
            college_email='private-other@example.edu',
            preferred_mode=Course.Mode.ONLINE,
        )
        self.client.force_login(student)
        self.client.force_login(student)
        with patch('core.assistant.call_openai', return_value='Your Python application is pending.') as call:
            with override_settings(OPENAI_API_KEY='test-openai-key'):
                response = self.client.post(reverse('assistant_chat'), {'message': 'What is my application status?'})

        self.assertEqual(response.status_code, 200)
        prompt = call.call_args.args[0][0]['content']
        self.assertIn('Guide Python Basics | Guide Department | Tuesday, 10:00 AM | Pending', prompt)
        self.assertNotIn('Private Application Record', prompt)

    def test_chatbot_validates_empty_and_oversized_questions(self):
        empty = self.client.post(reverse('assistant_chat'), {'message': '   '})
        too_long = self.client.post(reverse('assistant_chat'), {'message': 'x' * 1501})

        self.assertEqual(empty.status_code, 400)
        self.assertEqual(too_long.status_code, 400)

    def test_chatbot_uses_local_guide_when_ai_is_not_configured(self):
        with patch('core.assistant.call_openai') as call:
            response = self.client.post(reverse('assistant_chat'), {'message': 'What courses can I take?'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['mode'], 'local')
        self.assertIn('Guide Python Basics', response.json()['reply'])
        call.assert_not_called()

    def test_chatbot_reports_ai_outage_instead_of_returning_a_fallback_answer(self):
        from .assistant import AssistantServiceError

        with patch('core.assistant.call_openai', side_effect=AssistantServiceError('AI service is unavailable.')):
            with override_settings(OPENAI_API_KEY='test-openai-key'):
                response = self.client.post(reverse('assistant_chat'), {'message': 'Give me career advice.'})

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()['error'], 'AI service is unavailable.')
        self.assertEqual(self.client.get(reverse('assistant_chat')).json()['history'], [])

    def test_chatbot_remembers_follow_up_messages_and_new_chat_clears_history(self):
        with patch(
            'core.assistant.call_openai',
            side_effect=('Python is a programming language.', 'It is a popular first language.'),
        ) as call:
            with override_settings(OPENAI_API_KEY='test-openai-key'):
                first = self.client.post(reverse('assistant_chat'), {'message': 'What is Python?'})
                second = self.client.post(reverse('assistant_chat'), {'message': 'Is it good for beginners?'})
                reset = self.client.post(reverse('assistant_chat'), {'action': 'new_chat'})
                history = self.client.get(reverse('assistant_chat'))

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertIn('What is Python?', str(call.call_args_list[1].args[0]))
        self.assertEqual(reset.json()['history'], [])
        self.assertEqual(history.json()['history'], [])

    def test_chatbot_returns_saved_conversation_on_get(self):
        with patch('core.assistant.call_openai', return_value='Python is a programming language.'):
            with override_settings(OPENAI_API_KEY='test-openai-key'):
                self.client.post(reverse('assistant_chat'), {'message': 'What is Python?'})
                response = self.client.get(reverse('assistant_chat'))

        self.assertTrue(response.json()['configured'])
        self.assertEqual(response.json()['history'][0], {'role': 'user', 'content': 'What is Python?'})
        self.assertEqual(response.json()['history'][1]['role'], 'assistant')

    def test_college_questions_use_official_site_retrieval_and_return_citation(self):
        source = 'https://srcw.ac.in/contact'
        with patch('core.assistant.fetch_college_context', return_value=('Official address context.', [source])) as fetch:
            with patch('core.assistant.call_openai', return_value='The official page lists the address.') as call:
                with override_settings(OPENAI_API_KEY='test-openai-key'):
                    response = self.client.post(reverse('assistant_chat'), {'message': 'What is the college address?'})

        self.assertEqual(response.status_code, 200)
        self.assertIn(source, call.call_args.args[0][0]['content'])
        self.assertEqual(response.json()['sources'][0]['url'], source)
        fetch.assert_called_once()

    def test_college_website_outage_is_reported_without_calling_ai_for_a_guess(self):
        from .assistant import AssistantServiceError

        with patch(
            'core.assistant.fetch_college_context',
            side_effect=AssistantServiceError('Official college information is unavailable.'),
        ):
            with patch('core.assistant.call_openai') as call:
                with override_settings(OPENAI_API_KEY='test-openai-key'):
                    response = self.client.post(reverse('assistant_chat'), {'message': 'Where is the college campus?'})

        self.assertEqual(response.status_code, 503)
        self.assertIn('unavailable', response.json()['error'])
        call.assert_not_called()

    def test_openai_request_uses_server_side_key_and_chat_completions_api(self):
        import json

        fake_response = MagicMock()
        fake_response.__enter__.return_value = fake_response
        fake_response.read.return_value = json.dumps({
            'choices': [{'message': {'content': 'Here is a clear answer.'}}],
        }).encode('utf-8')
        with patch('core.assistant.urlopen', return_value=fake_response) as open_url:
            with override_settings(
                OPENAI_API_KEY='server-only-test-key',
                OPENAI_MODEL='gpt-test-model',
                OPENAI_BASE_URL='https://api.openai.com/v1',
            ):
                from .assistant import call_openai

                answer = call_openai([{'role': 'user', 'content': 'Explain loops.'}])

        request = open_url.call_args.args[0]
        self.assertEqual(answer, 'Here is a clear answer.')
        self.assertEqual(request.full_url, 'https://api.openai.com/v1/chat/completions')
        self.assertEqual(request.get_header('Authorization'), 'Bearer server-only-test-key')
        self.assertEqual(json.loads(request.data)['model'], 'gpt-test-model')


class SkilloraAssistantTests(TestCase):
    def setUp(self):
        self.student = User.objects.create_user(username='student-test', password='test-password-123')
        self.client.force_login(self.student)

    def test_certificate_answer_uses_the_students_recorded_status(self):
        with patch('core.assistant.call_openai', return_value='I do not see any certificate requests yet.') as call:
            with override_settings(OPENAI_API_KEY='test-openai-key'):
                response = self.client.post(
                    reverse('assistant_chat'),
                    {'message': 'Check my certificate status'},
                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['mode'], 'openai')
        self.assertIn('No certificate requests recorded.', call.call_args.args[0][0]['content'])
        self.assertEqual(
            response.json()['actions'][0]['url'],
            f"{reverse('dashboard')}#certificate-status",
        )


class CertificateWorkflowTests(TestCase):
    def setUp(self):
        self.student = User.objects.create_user(username='certificate-student', password='test-password-123')
        self.instructor = User.objects.create_user(
            username='certificate-instructor',
            password='test-password-123',
            role=User.Role.INSTRUCTOR,
        )
        self.faculty = User.objects.create_user(
            username='certificate-faculty',
            password='test-password-123',
            role=User.Role.FACULTY,
        )
        self.course = Course.objects.create(
            title='Verified course',
            slug='verified-course',
            description='A test course.',
            instructor=self.instructor,
            schedule='Schedule to be confirmed',
        )
        self.enrollment = Enrollment.objects.create(
            student=self.student,
            course=self.course,
            completed=True,
            completion_date=timezone.localdate() - timedelta(days=1),
        )
        self.certificate = CertificateRequest.objects.create(
            student=self.student,
            course=self.course,
        )
        self.client.force_login(self.faculty)

    def test_faculty_cannot_approve_without_instructor_completion_verification(self):
        self.client.post(
            reverse('review_certificate', args=(self.certificate.pk,)),
            {'status': CertificateRequest.Status.APPROVED},
        )

        self.certificate.refresh_from_db()
        self.assertEqual(self.certificate.status, CertificateRequest.Status.PENDING)

    def test_verified_completion_can_be_approved_and_publicly_verified(self):
        self.enrollment.completion_verified_by = self.instructor
        self.enrollment.save(update_fields=['completion_verified_by'])

        self.client.post(
            reverse('review_certificate', args=(self.certificate.pk,)),
            {'status': CertificateRequest.Status.APPROVED},
        )

        self.certificate.refresh_from_db()
        self.assertEqual(self.certificate.status, CertificateRequest.Status.APPROVED)
        self.assertTrue(self.certificate.certificate_number)
        self.assertEqual(self.certificate.completion_date, self.enrollment.completion_date)

        response = self.client.get(reverse('verify_certificate', args=(self.certificate.pk,)))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Certificate is valid')
        self.assertContains(response, self.certificate.certificate_number)

        self.client.force_login(self.student)
        view_response = self.client.get(reverse('view_certificate', args=(self.certificate.pk,)))
        self.assertEqual(view_response.status_code, 200)
        self.assertContains(view_response, 'Certificate of Completion')
        self.assertContains(view_response, self.certificate.certificate_number)
        self.assertContains(view_response, 'signature not recorded')
        self.assertContains(view_response, 'not a college-issued credential')

        qr_response = self.client.get(reverse('certificate_qr', args=(self.certificate.pk,)))
        self.assertEqual(qr_response.status_code, 200)
        self.assertEqual(qr_response['Content-Type'], 'image/svg+xml')
        self.assertIn(b'<svg', qr_response.content)

        pdf_response = self.client.get(reverse('download_certificate', args=(self.certificate.pk,)))
        self.assertEqual(pdf_response.status_code, 200)
        self.assertEqual(pdf_response['Content-Type'], 'application/pdf')
        self.assertTrue(pdf_response.content.startswith(b'%PDF'))
        self.assertIn(b'841.8898', pdf_response.content)
        self.assertIn(b'595.2756', pdf_response.content)

    def test_certificate_preview_is_not_available_before_authorized_approval(self):
        self.certificate.status = CertificateRequest.Status.PENDING
        self.certificate.save(update_fields=('status',))

        self.client.force_login(self.student)
        response = self.client.get(reverse('view_certificate', args=(self.certificate.pk,)))

        self.assertEqual(response.status_code, 404)

    def test_certificate_qr_encodes_the_real_verification_url(self):
        self.enrollment.completion_verified_by = self.instructor
        self.enrollment.save(update_fields=('completion_verified_by',))
        self.client.post(
            reverse('review_certificate', args=(self.certificate.pk,)),
            {'status': CertificateRequest.Status.APPROVED},
        )
        verification_path = reverse('verify_certificate', args=(self.certificate.pk,))
        with (
            patch('core.views.QrCodeWidget') as qr_widget,
            patch('core.views.Drawing'),
            patch('core.views.renderSVG.drawToString', return_value='<svg></svg>'),
        ):
            response = self.client.get(reverse('certificate_qr', args=(self.certificate.pk,)))

        self.assertEqual(response.status_code, 200)
        qr_widget.assert_called_once_with(f'http://testserver{verification_path}')


class RoleDashboardTests(TestCase):
    def setUp(self):
        self.student = User.objects.create_user(username='role-student', password='test-password-123')
        self.teacher = User.objects.create_user(
            username='role-teacher',
            password='test-password-123',
            role=User.Role.INSTRUCTOR,
            is_staff=True,
        )
        self.admin = User.objects.create_user(
            username='role-admin',
            password='test-password-123',
            is_staff=True,
        )

    def test_public_signup_cannot_assign_faculty_or_admin_role(self):
        form = CustomUserCreationForm(data={
            'username': 'public-admin',
            'email': 'public@example.edu',
            'role': User.Role.FACULTY,
            'password1': 'Safe-Password-8421!',
            'password2': 'Safe-Password-8421!',
        })

        self.assertFalse(form.is_valid())
        self.assertFalse(User.objects.filter(username='public-admin').exists())

    def test_role_dashboards_reject_users_from_other_roles(self):
        self.client.force_login(self.student)

        admin_response = self.client.get(reverse('college_admin_dashboard'))
        teacher_response = self.client.get(reverse('teacher_dashboard'))
        student_response = self.client.get(reverse('student_dashboard'))

        self.assertEqual(admin_response.status_code, 403)
        self.assertEqual(teacher_response.status_code, 403)
        self.assertEqual(student_response.status_code, 200)

    def test_unapproved_teacher_is_sent_to_application_status(self):
        self.assertFalse(self.teacher.is_college_admin)
        self.client.force_login(self.teacher)

        response = self.client.get(reverse('dashboard'))

        self.assertRedirects(response, reverse('teacher_pending'))
        self.assertEqual(self.client.get(reverse('teacher_pending')).status_code, 200)

    def test_teacher_and_administrator_dashboard_pages_render_for_their_roles(self):
        self.teacher.instructor_approved = True
        self.teacher.save(update_fields=['instructor_approved'])

        self.client.force_login(self.teacher)
        self.assertEqual(self.client.get(reverse('teacher_dashboard')).status_code, 200)
        self.assertEqual(self.client.get(reverse('create_course')).status_code, 200)

        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse('college_admin_dashboard')).status_code, 200)

    def test_logout_button_ends_the_session_and_get_does_not_change_session_state(self):
        self.client.force_login(self.student)
        home_response = self.client.get(reverse('home'))
        self.assertContains(home_response, 'Logout')

        get_response = self.client.get(reverse('logout'))
        self.assertEqual(get_response.status_code, 405)
        self.assertTrue(self.client.session.get('_auth_user_id'))

        logout_response = self.client.post(reverse('logout'))
        self.assertRedirects(logout_response, reverse('home'))
        self.assertNotIn('_auth_user_id', self.client.session)


class ApprovalAndAccessTests(TestCase):
    def setUp(self):
        self.student = User.objects.create_user(username='approval-student', password='test-password-123')
        self.teacher = User.objects.create_user(
            username='approval-teacher',
            password='test-password-123',
            role=User.Role.INSTRUCTOR,
            instructor_approved=True,
        )
        self.waiting_teacher = User.objects.create_user(
            username='waiting-teacher',
            password='test-password-123',
            role=User.Role.INSTRUCTOR,
        )
        self.admin = User.objects.create_user(
            username='approval-admin',
            password='test-password-123',
            is_staff=True,
        )
        self.department = Department.objects.create(name='Test Department', slug='test-department')
        self.course = Course.objects.create(
            title='Pending course',
            slug='pending-course',
            description='Awaiting review.',
            instructor=self.teacher,
            department=self.department,
            schedule='To be confirmed',
            status=Course.Status.DRAFT,
        )

    def test_only_approved_courses_are_public_until_admin_approval(self):
        response = self.client.get(reverse('course_detail', args=(self.course.slug,)))
        self.assertEqual(response.status_code, 404)

        self.client.force_login(self.admin)
        review_response = self.client.post(
            reverse('review_course', args=(self.course.pk,)),
            {'decision': Course.ApprovalStatus.APPROVED},
        )
        self.assertEqual(review_response.status_code, 302)
        self.course.refresh_from_db()
        self.assertEqual(self.course.approval_status, Course.ApprovalStatus.APPROVED)
        self.assertEqual(self.course.status, Course.Status.PUBLISHED)

        self.client.force_login(self.student)
        detail_response = self.client.get(reverse('course_detail', args=(self.course.slug,)))
        self.assertEqual(detail_response.status_code, 200)

    def test_session_request_rejects_unapproved_teacher_recipient(self):
        self.client.force_login(self.student)

        response = self.client.post(reverse('request_session'), {
            'to_user': self.waiting_teacher.pk,
            'title': 'Learn a skill',
            'preferred_slot': 'Friday afternoon',
            'mode': 'online',
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(SessionRequest.objects.count(), 0)

    def test_only_the_session_recipient_can_accept_a_request(self):
        session = SessionRequest.objects.create(
            from_user=self.teacher,
            to_user=self.student,
            title='Study session',
            preferred_slot='Friday afternoon',
        )

        self.client.force_login(self.teacher)
        denied_response = self.client.post(reverse('decide_session', args=(session.pk,)), {
            'decision': SessionRequest.Status.ACCEPTED,
        })
        self.assertEqual(denied_response.status_code, 403)

        self.client.force_login(self.student)
        accepted_response = self.client.post(reverse('decide_session', args=(session.pk,)), {
            'decision': SessionRequest.Status.ACCEPTED,
        })
        session.refresh_from_db()
        self.assertEqual(accepted_response.status_code, 302)
        self.assertEqual(session.status, SessionRequest.Status.ACCEPTED)

    def test_attendance_does_not_automatically_verify_course_completion(self):
        batch = Batch.objects.create(
            course=self.course,
            name='Attendance batch',
            start_date=timezone.localdate() + timedelta(days=7),
            schedule='Tuesday, 10 AM',
            mode=Course.Mode.ONLINE,
        )
        application = CourseApplication.objects.create(
            student=self.student,
            course=self.course,
            batch=batch,
            department=Department.objects.create(name='Attendance department', slug='attendance-department'),
            applicant_name='Approval Student',
            college_email='approval-student@example.edu',
            preferred_mode=Course.Mode.ONLINE,
            status=CourseApplication.Status.ACCEPTED,
        )
        enrollment = Enrollment.objects.create(student=self.student, course=self.course, batch=batch)
        self.client.force_login(self.teacher)
        url = reverse('batch_attendance', args=(batch.pk,))

        attendance_response = self.client.post(url, {
            'session_date': '2026-10-20',
            f'present_{application.pk}': 'on',
        })
        enrollment.refresh_from_db()
        self.assertEqual(attendance_response.status_code, 302)
        self.assertTrue(AttendanceRecord.objects.get(course=self.course, student=self.student).present)
        self.assertFalse(enrollment.completed)
        self.assertIsNone(enrollment.completion_verified_by)

        self.client.post(url, {
            'session_date': '2026-10-20',
            f'present_{application.pk}': 'on',
            f'complete_{application.pk}': 'on',
        })
        enrollment.refresh_from_db()
        self.assertTrue(enrollment.completed)
        self.assertEqual(enrollment.completion_verified_by, self.teacher)
        self.assertEqual(enrollment.status, Enrollment.Status.COMPLETED)
        self.assertEqual(enrollment.completion_date.isoformat(), '2026-10-20')
        self.assertTrue(CertificateRequest.objects.filter(student=self.student, course=self.course).exists())


class TeacherApplicationWorkflowTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='workflow-admin',
            password='test-password-123',
            is_staff=True,
        )
        self.student = User.objects.create_user(
            username='workflow-student',
            email='workflow-student@example.edu',
            password='test-password-123',
        )
        self.department = Department.objects.create(name='Workflow Department', slug='workflow-department')

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_teacher_application_course_approval_and_student_enrollment(self):
        response = self.client.post(reverse('register'), {
            'username': 'new-teacher',
            'email': 'new-teacher@example.edu',
            'role': User.Role.INSTRUCTOR,
            'password1': 'Strong-Example-Password-739!',
            'password2': 'Strong-Example-Password-739!',
        }, follow=True)

        teacher = User.objects.get(username='new-teacher')
        teacher.first_name = 'Raja'
        teacher.last_name = 'Sharma'
        teacher.save(update_fields=('first_name', 'last_name'))
        self.assertContains(response, 'awaiting college approval')
        self.assertFalse(teacher.instructor_approved)

        self.client.force_login(self.admin)
        self.client.post(reverse('approve_teacher', args=(teacher.pk,)))
        teacher.refresh_from_db()
        self.assertTrue(teacher.instructor_approved)

        self.client.force_login(teacher)
        course_response = self.client.post(reverse('create_course'), {
            'title': 'Communication Skills',
            'slug': 'communication-skills',
            'description': 'Practice clear communication.',
            'department': self.department.pk,
            'duration_weeks': '4',
            'mode': Course.Mode.ONLINE,
            'schedule': 'Weekly',
        })
        self.assertEqual(course_response.status_code, 302)
        course = Course.objects.get(slug='communication-skills')
        self.assertEqual(course.approval_status, Course.ApprovalStatus.PENDING)
        self.assertEqual(course.status, Course.Status.DRAFT)

        self.client.force_login(self.admin)
        self.client.post(
            reverse('review_course', args=(course.pk,)),
            {'decision': Course.ApprovalStatus.APPROVED},
        )
        batch = Batch.objects.create(
            course=course,
            name='Batch 1',
            start_date=timezone.localdate() + timedelta(days=7),
            schedule='Wednesday, 3 PM',
            mode=Course.Mode.ONLINE,
            meeting_link='https://meet.example.edu/skillora',
        )
        self.client.force_login(self.student)
        application_data = {
            'applicant_name': 'Student One',
            'college_email': self.student.email,
            'department': self.department.pk,
            'batch': batch.pk,
            'preferred_mode': Course.Mode.ONLINE,
        }
        application_response = self.client.post(
            reverse('apply_course', args=(course.slug,)),
            application_data,
        )
        self.assertEqual(application_response.status_code, 302)
        application = CourseApplication.objects.get(student=self.student, course=course)
        self.assertEqual(application.status, CourseApplication.Status.PENDING)
        self.assertFalse(Enrollment.objects.filter(student=self.student, course=course).exists())

        self.client.force_login(teacher)
        review_response = self.client.post(
            reverse('review_application', args=(application.pk,)),
            {'decision': CourseApplication.Status.ACCEPTED},
        )
        application.refresh_from_db()
        self.assertEqual(review_response.status_code, 302)
        self.assertEqual(application.status, CourseApplication.Status.ACCEPTED)
        self.assertTrue(Enrollment.objects.filter(student=self.student, course=course).exists())
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('Wednesday, 3 PM', mail.outbox[0].body)
        self.assertIn('Teacher: Raja Sharma', mail.outbox[0].body)
        self.assertTrue(StudentNotification.objects.filter(student=self.student).exists())


class BatchCapacityTests(TestCase):
    def setUp(self):
        self.teacher = User.objects.create_user(
            username='capacity-teacher',
            first_name='Tara',
            last_name='Teacher',
            password='test-password-123',
            role=User.Role.INSTRUCTOR,
            instructor_approved=True,
        )
        self.department = Department.objects.create(name='Capacity Department', slug='capacity-department')
        self.course = Course.objects.create(
            title='Capacity course',
            slug='capacity-course',
            description='Small class.',
            instructor=self.teacher,
            department=self.department,
            schedule='10 AM',
            status=Course.Status.PUBLISHED,
            approval_status=Course.ApprovalStatus.APPROVED,
        )
        self.batch = Batch.objects.create(
            course=self.course,
            name='Batch 1',
            start_date=timezone.localdate() + timedelta(days=7),
            schedule='10 AM',
            mode=Course.Mode.ONLINE,
        )

    def test_course_application_stays_pending_until_teacher_review(self):
        student = User.objects.create_user(
            username='applicant',
            email='applicant@example.edu',
            first_name='Asha',
            last_name='Student',
            password='test-password-123',
        )
        self.client.force_login(student)
        response = self.client.post(reverse('apply_course', args=(self.course.slug,)), {
            'applicant_name': 'Asha Student',
            'college_email': 'applicant@example.edu',
            'department': self.department.pk,
            'batch': self.batch.pk,
            'preferred_mode': Course.Mode.ONLINE,
        })

        application = CourseApplication.objects.get(student=student, course=self.course)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(application.status, CourseApplication.Status.PENDING)
        self.assertFalse(Enrollment.objects.filter(student=student, course=self.course).exists())

    def test_student_dashboard_exposes_only_the_current_students_applications(self):
        student = User.objects.create_user(username='private-student', password='test-password-123')
        other_student = User.objects.create_user(username='other-private-student', password='test-password-123')
        CourseApplication.objects.create(
            student=student,
            course=self.course,
            batch=self.batch,
            department=self.department,
            applicant_name='Private Student Name',
            college_email='private@example.edu',
            preferred_mode=Course.Mode.ONLINE,
        )
        CourseApplication.objects.create(
            student=other_student,
            course=self.course,
            batch=self.batch,
            department=self.department,
            applicant_name='Other Student Secret',
            college_email='other@example.edu',
            preferred_mode=Course.Mode.ONLINE,
        )

        self.client.force_login(student)
        response = self.client.get(reverse('student_dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="dashboard-welcome"')
        self.assertContains(response, 'core/srcw-home-banner.png')
        application_rows = response.context['application_progress']
        self.assertEqual(len(application_rows), 1)
        self.assertEqual(application_rows[0]['application'].student_id, student.pk)

    def test_certificate_preview_is_locked_until_teacher_verifies_course_completion(self):
        student = User.objects.create_user(
            username='certificate-preview-student',
            first_name='Asha',
            last_name='Learner',
            password='test-password-123',
        )
        Enrollment.objects.create(student=student, course=self.course, batch=self.batch)
        self.client.force_login(student)

        locked = self.client.get(reverse('student_dashboard'))
        self.assertContains(locked, 'Certificate of Completion')
        self.assertContains(locked, 'Preview locked')
        self.assertContains(locked, 'PREVIEW · NOT ISSUED')

        enrollment = Enrollment.objects.get(student=student, course=self.course)
        enrollment.completed = True
        enrollment.completion_verified_by = self.teacher
        enrollment.completion_date = timezone.localdate()
        enrollment.save(update_fields=('completed', 'completion_verified_by', 'completion_date'))
        unlocked = self.client.get(reverse('student_dashboard'))

        self.assertContains(unlocked, 'Preview unlocked')
        self.assertContains(unlocked, 'Capacity course')
        self.assertContains(unlocked, 'official certificate requires authorized approval')

    def test_unassigned_teacher_cannot_review_an_application(self):
        other_teacher = User.objects.create_user(
            username='unassigned-teacher',
            password='test-password-123',
            role=User.Role.INSTRUCTOR,
            instructor_approved=True,
        )
        applicant = User.objects.create_user(
            username='unassigned-applicant',
            email='unassigned@example.edu',
            password='test-password-123',
        )
        application = CourseApplication.objects.create(
            student=applicant,
            course=self.course,
            batch=self.batch,
            department=self.department,
            applicant_name='Unassigned Applicant',
            college_email=applicant.email,
            preferred_mode=Course.Mode.ONLINE,
        )

        self.client.force_login(other_teacher)
        response = self.client.post(reverse('review_application', args=(application.pk,)), {
            'decision': CourseApplication.Status.ACCEPTED,
        })

        application.refresh_from_db()
        self.assertEqual(response.status_code, 403)
        self.assertEqual(application.status, CourseApplication.Status.PENDING)
        self.assertFalse(Enrollment.objects.filter(student=applicant, course=self.course).exists())

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_teacher_rejection_notifies_student_without_creating_enrollment(self):
        applicant = User.objects.create_user(
            username='rejected-applicant',
            email='rejected@example.edu',
            password='test-password-123',
        )
        application = CourseApplication.objects.create(
            student=applicant,
            course=self.course,
            batch=self.batch,
            department=self.department,
            applicant_name='Rejected Applicant',
            college_email=applicant.email,
            preferred_mode=Course.Mode.ONLINE,
        )

        self.client.force_login(self.teacher)
        response = self.client.post(reverse('review_application', args=(application.pk,)), {
            'decision': CourseApplication.Status.REJECTED,
        })

        application.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(application.status, CourseApplication.Status.REJECTED)
        self.assertFalse(Enrollment.objects.filter(student=applicant, course=self.course).exists())
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('was not accepted', mail.outbox[0].body)

    def test_full_batch_offers_a_later_batch_without_overbooking(self):
        for index in range(10):
            student = User.objects.create_user(
                username=f'accepted-{index}',
                email=f'accepted-{index}@example.edu',
                password='test-password-123',
            )
            app = CourseApplication.objects.create(
                student=student,
                course=self.course,
                batch=self.batch,
                department=self.department,
                applicant_name=f'Accepted {index}',
                college_email=student.email,
                preferred_mode=Course.Mode.ONLINE,
                status=CourseApplication.Status.ACCEPTED,
            )
            Enrollment.objects.create(student=student, course=self.course, batch=self.batch)
        applicant = User.objects.create_user(
            username='pending-eleventh',
            email='pending@example.edu',
            password='test-password-123',
        )
        pending = CourseApplication.objects.create(
            student=applicant,
            course=self.course,
            batch=self.batch,
            department=self.department,
            applicant_name='Eleventh Applicant',
            college_email=applicant.email,
            preferred_mode=Course.Mode.ONLINE,
        )

        self.client.force_login(self.teacher)
        response = self.client.post(reverse('review_application', args=(pending.pk,)), {
            'decision': CourseApplication.Status.ACCEPTED,
        })

        pending.refresh_from_db()
        next_batch = pending.batch
        self.assertEqual(response.status_code, 302)
        self.assertEqual(pending.status, CourseApplication.Status.PENDING)
        self.assertNotEqual(next_batch.pk, self.batch.pk)
        self.assertEqual(next_batch.available_seats, 10)
        self.assertEqual(next_batch.schedule, self.batch.schedule)
        self.assertFalse(Enrollment.objects.filter(student=applicant, course=self.course).exists())
        self.assertTrue(StudentNotification.objects.filter(student=applicant, title='A later batch is available').exists())


class SeedDataTests(TestCase):
    def test_seeding_is_safe_for_existing_accounts_and_does_not_bypass_approval(self):
        teacher = User.objects.create_user(
            username='skillora-demo-teacher',
            password='Existing-Password-123!',
            role=User.Role.INSTRUCTOR,
            instructor_approved=True,
        )

        call_command('seed_data', verbosity=0)
        call_command('seed_data', verbosity=0)

        teacher.refresh_from_db()
        self.assertTrue(teacher.check_password('Existing-Password-123!'))
        self.assertEqual(Department.objects.count(), 5)
        self.assertEqual(Course.objects.filter(approval_status=Course.ApprovalStatus.APPROVED).count(), 6)
        self.assertFalse(Enrollment.objects.exists())
