import csv
from datetime import timedelta
from io import BytesIO
from smtplib import SMTPException

from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.conf import settings
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Count, Prefetch, Q
from django.core.mail import send_mail
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.dateparse import parse_date
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils import timezone

from .assistant import (
    AssistantServiceError,
    CHAT_HISTORY_LIMIT,
    CHAT_HISTORY_SESSION_KEY,
    generate_assistant_reply,
)
from .forms import BatchForm, CertificateStatusForm, CourseApplicationForm, CourseForm, CustomUserCreationForm, ProfileForm, SessionRequestForm
from .models import AttendanceRecord, Batch, CertificateRequest, Course, CourseApplication, Department, Enrollment, SessionRequest, Skill, StudentNotification, User
from .personalization import ABOUT_SKILLORA, COLLEGE_CONTACT, COLLEGE_NAME, FACULTY_COORDINATOR, PROJECT_TEAM, SKILL_TAGS

try:
    from reportlab.lib.colors import HexColor
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.pdfgen import canvas
    from reportlab.graphics.barcode.qr import QrCodeWidget
    from reportlab.graphics.shapes import Drawing
    from reportlab.graphics import renderPDF, renderSVG
except Exception:  # pragma: no cover
    canvas = None
    HexColor = None
    A4 = None
    landscape = None
    QrCodeWidget = None
    Drawing = None
    renderPDF = None
    renderSVG = None


def _public_courses():
    return Course.objects.filter(
        status=Course.Status.PUBLISHED,
        approval_status=Course.ApprovalStatus.APPROVED,
        instructor__is_active=True,
    ).filter(
        Q(instructor__role=User.Role.FACULTY)
        | Q(instructor__role=User.Role.INSTRUCTOR, instructor__instructor_approved=True)
    )


def _create_next_batch(course, previous_batch=None):
    existing_batches = course.batches.order_by('-start_date', '-pk')
    latest = existing_batches.first()
    template_batch = previous_batch or latest
    if template_batch is None:
        schedule = course.schedule
        mode = course.mode
        venue = course.venue
        meeting_link = course.meeting_link
        next_date = timezone.localdate() + timedelta(days=7)
    else:
        schedule = template_batch.schedule
        mode = template_batch.mode
        venue = template_batch.venue
        meeting_link = template_batch.meeting_link
        next_date = max(template_batch.start_date, timezone.localdate()) + timedelta(days=7)
    next_number = 1
    while course.batches.filter(name=f'Batch {next_number}').exists():
        next_number += 1
    return Batch.objects.create(
        course=course,
        name=f'Batch {next_number}',
        start_date=next_date,
        schedule=schedule,
        mode=mode,
        venue=venue,
        meeting_link=meeting_link,
    )


def _next_open_batch(course):
    for batch in course.batches.filter(is_open=True).order_by('start_date', 'schedule', 'pk'):
        if batch.available_seats:
            return batch
    return _create_next_batch(course)


def _notify_student(application, title, message):
    StudentNotification.objects.create(
        student=application.student,
        title=title,
        message=message,
        url=reverse('student_dashboard'),
    )


def _send_application_email(application):
    accepted = application.status == CourseApplication.Status.ACCEPTED
    subject = (
        f'Skillora application accepted: {application.course.title}'
        if accepted
        else f'Skillora application update: {application.course.title}'
    )
    batch = application.batch
    teacher = application.course.instructor.get_full_name() or application.course.instructor.username
    if accepted:
        location = (
            f'Venue: {batch.venue}'
            if batch.mode == Course.Mode.OFFLINE and batch.venue
            else f'Online meeting: {batch.meeting_link}'
            if batch.meeting_link
            else 'The teacher will share the session access details.'
        )
        body = (
            f'Hello {application.applicant_name},\n\n'
            f'Your application for {application.course.title} in {application.department.name} has been accepted.\n'
            f'Class date: {batch.start_date:%B %d, %Y}\n'
            f'Class timing: {batch.schedule}\n'
            f'Mode: {batch.get_mode_display()}\n'
            f'{location}\n'
            f'Teacher: {teacher}\n\n'
            'You can see your application and attendance details in your Skillora dashboard.'
        )
    else:
        body = (
            f'Hello {application.applicant_name},\n\n'
            f'Thank you for applying for {application.course.title}. '
            'Your application was not accepted for this batch. You may apply for another open batch if available.\n\n'
            'You can check your Skillora dashboard for application details.'
        )
    sent = send_mail(
        subject,
        body,
        settings.DEFAULT_FROM_EMAIL,
        [application.college_email],
        fail_silently=False,
    )
    return sent


def home(request):
    featured_courses = _public_courses().select_related('instructor', 'skill', 'department').prefetch_related('batches')[:6]
    categories = Skill.objects.values('category').annotate(count=Count('id')).order_by('-count')[:6]
    return render(request, 'home.html', {
        'featured_courses': featured_courses,
        'categories': categories,
        'departments': Department.objects.prefetch_related(
            Prefetch('courses', queryset=_public_courses().select_related('instructor').prefetch_related('batches'))
        ),
        'sample_students': (
            ('Charishma P.', 'Computer Applications', 'Prompt Engineering', '10:00 AM to 11:00 AM', 'CP'),
            ('Nisha R.', 'Computer Science', 'Python Programming', '11:00 AM to 12:00 PM', 'NR'),
            ('Priya S.', 'Information Technology', 'Web Design', '1:00 PM to 2:00 PM', 'PS'),
            ('Divya K.', 'Commerce', 'Data Analytics', '2:00 PM to 3:00 PM', 'DK'),
            ('Harini M.', 'Management', 'Communication Skills', '3:00 PM to 4:00 PM', 'HM'),
        ),
    })


def register(request):
    if request.method == 'POST':
        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, 'Your Skillora account has been created.')
            return redirect('dashboard')
    else:
        form = CustomUserCreationForm()
    return render(request, 'register.html', {'form': form})


def custom_login(request):
    form = AuthenticationForm(request, data=request.POST or None)
    if request.method == 'POST' and form.is_valid():
        login(request, form.get_user())
        next_url = request.POST.get('next') or request.GET.get('next', '')
        if next_url and url_has_allowed_host_and_scheme(
            next_url,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure(),
        ):
            return redirect(next_url)
        return redirect('dashboard')
    return render(request, 'login.html', {'form': form})


def logout_user(request):
    if request.method != 'POST':
        return HttpResponse(status=405)
    logout(request)
    messages.success(request, 'You have been logged out.')
    return redirect('home')


@login_required
def profile(request):
    if request.method == 'POST':
        form = ProfileForm(request.POST, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, 'Your profile has been updated.')
            return redirect('profile')
    else:
        form = ProfileForm(instance=request.user)
    return render(request, 'profile.html', {'form': form})


@login_required
def dashboard(request):
    user = request.user
    if user.is_college_admin:
        return redirect('college_admin_dashboard')
    if user.role == User.Role.INSTRUCTOR:
        if not user.instructor_approved:
            return redirect('teacher_pending')
        return redirect('teacher_dashboard')
    if user.is_faculty:
        return redirect('teacher_dashboard')
    return redirect('student_dashboard')


@login_required
def student_dashboard(request):
    if not request.user.is_student:
        return HttpResponse('Student dashboard access is required.', status=403)

    user = request.user
    enrollments = Enrollment.objects.filter(student=user).select_related('course', 'course__instructor').order_by('-enrolled_at')[:6]
    upcoming_sessions = SessionRequest.objects.filter(Q(from_user=user) | Q(to_user=user), status=SessionRequest.Status.ACCEPTED).order_by('preferred_slot')[:5]
    recent_requests = SessionRequest.objects.filter(Q(from_user=user) | Q(to_user=user)).order_by('-created_at')[:4]
    incoming_requests = SessionRequest.objects.filter(
        to_user=user,
        status=SessionRequest.Status.PENDING,
    ).select_related('from_user')[:6]
    certificates = CertificateRequest.objects.filter(student=user).order_by('-requested_at')[:4]
    applications = CourseApplication.objects.filter(student=user).select_related(
        'course', 'course__instructor', 'course__department', 'batch', 'department',
    )
    application_progress = []
    for application in applications:
        sessions = AttendanceRecord.objects.filter(
            course=application.course,
            batch=application.batch,
            student=user,
        )
        total_sessions = AttendanceRecord.objects.filter(batch=application.batch).values('session_date').distinct().count()
        present_sessions = sessions.filter(present=True).count()
        application_progress.append({
            'application': application,
            'present_sessions': present_sessions,
            'total_sessions': total_sessions,
            'attendance_percent': round(present_sessions * 100 / total_sessions) if total_sessions else 0,
        })
    notifications = StudentNotification.objects.filter(student=user)[:8]
    certificate_course_ids = set(
        CertificateRequest.objects.filter(student=user).values_list('course_id', flat=True)
    )
    recommended_courses = _public_courses().select_related('skill')[:3]

    return render(request, 'dashboard.html', {
        'enrollments': enrollments,
        'upcoming_sessions': upcoming_sessions,
        'recent_requests': recent_requests,
        'incoming_requests': incoming_requests,
        'certificates': certificates,
        'application_progress': application_progress,
        'notifications': notifications,
        'certificate_course_ids': certificate_course_ids,
        'recommended_courses': recommended_courses,
        'about_skillora': ABOUT_SKILLORA,
        'college_name': COLLEGE_NAME,
        'faculty_coordinator': FACULTY_COORDINATOR,
        'project_team': PROJECT_TEAM,
        'skill_tags': SKILL_TAGS,
        'college_contact': COLLEGE_CONTACT,
    })


@login_required
def teacher_pending(request):
    if request.user.role != User.Role.INSTRUCTOR or request.user.instructor_approved:
        return redirect('dashboard')
    return render(request, 'teacher_pending.html')


def assistant_chat(request):
    if request.method == 'GET':
        response = JsonResponse({
            'configured': True,
            'mode': 'openai' if getattr(settings, 'OPENAI_API_KEY', '') else 'local',
            'history': request.session.get(CHAT_HISTORY_SESSION_KEY, []),
        })
        response['Cache-Control'] = 'no-store'
        return response
    if request.method != 'POST':
        return JsonResponse({'error': 'Use GET to load the conversation or POST to send a message.'}, status=405)

    action = request.POST.get('action', '')
    if action == 'new_chat':
        request.session.pop(CHAT_HISTORY_SESSION_KEY, None)
        return JsonResponse({'history': [], 'cleared': True})

    payload = request.POST.get('message', '').strip()
    if not payload:
        return JsonResponse({'error': 'Enter a question for Skillora Guide.'}, status=400)
    if len(payload) > 1500:
        return JsonResponse({'error': 'Please keep your message under 1,500 characters.'}, status=400)

    history = request.session.get(CHAT_HISTORY_SESSION_KEY, [])
    if not isinstance(history, list):
        history = []
    history = [
        item for item in history[-CHAT_HISTORY_LIMIT:]
        if isinstance(item, dict)
        and item.get('role') in ('user', 'assistant')
        and isinstance(item.get('content'), str)
    ]
    try:
        result = generate_assistant_reply(request.user, payload, history)
    except AssistantServiceError as exc:
        response = JsonResponse({'error': str(exc)}, status=exc.status)
        response['Cache-Control'] = 'no-store'
        return response

    updated_history = [
        *history,
        {'role': 'user', 'content': payload},
        {'role': 'assistant', 'content': result['reply']},
    ][-CHAT_HISTORY_LIMIT:]
    request.session[CHAT_HISTORY_SESSION_KEY] = updated_history
    result['history'] = updated_history
    response = JsonResponse(result)
    response['Cache-Control'] = 'no-store'
    return response


@login_required
def teacher_dashboard(request):
    if (
        not request.user.is_teacher
        or (request.user.role == User.Role.INSTRUCTOR and not request.user.instructor_approved)
    ):
        return HttpResponse('This dashboard is available to approved teachers and faculty.', status=403)
    courses = Course.objects.filter(instructor=request.user).select_related('skill', 'department').prefetch_related('batches')
    learners = Enrollment.objects.filter(course__instructor=request.user).select_related('student', 'course')
    student_requests = SessionRequest.objects.filter(to_user=request.user, status=SessionRequest.Status.PENDING).select_related('from_user')
    return render(request, 'instructor_dashboard.html', {
        'courses': courses,
        'learners': learners,
        'student_requests': student_requests,
        'pending_completions': learners.filter(completed=False),
        'pending_applications': CourseApplication.objects.filter(
            course__instructor=request.user,
            status=CourseApplication.Status.PENDING,
        ).select_related('student', 'course', 'batch', 'department').order_by('applied_at'),
        'accepted_applications': _applications_with_attendance(
            CourseApplication.objects.filter(
                course__instructor=request.user,
                status=CourseApplication.Status.ACCEPTED,
            ).select_related('student', 'course', 'batch', 'department')
        ),
        'pending_certificates': CertificateRequest.objects.filter(
            course__instructor=request.user,
        ).select_related('student', 'course')[:8],
    })


def _applications_with_attendance(applications):
    rows = []
    for application in applications:
        attendance = AttendanceRecord.objects.filter(
            course=application.course,
            batch=application.batch,
            student=application.student,
        )
        session_count = AttendanceRecord.objects.filter(batch=application.batch).values('session_date').distinct().count()
        present_count = attendance.filter(present=True).count()
        rows.append({
            'application': application,
            'attendance_percent': round(present_count * 100 / session_count) if session_count else 0,
            'present_count': present_count,
            'session_count': session_count,
            'enrollment': Enrollment.objects.filter(student=application.student, course=application.course).first(),
        })
    return rows


@login_required
def instructor_dashboard(request):
    return redirect('teacher_dashboard')


@login_required
def faculty_dashboard(request):
    return redirect('college_admin_dashboard' if request.user.is_college_admin else 'teacher_dashboard')


@login_required
def record_attendance(request, slug):
    course = get_object_or_404(Course, slug=slug)
    if not request.user.is_college_admin and (
        not request.user.is_teacher or course.instructor_id != request.user.pk
    ):
        return HttpResponse('Only the assigned teacher or college administrator can manage attendance.', status=403)
    batch = course.batches.filter(is_open=True).order_by('start_date', 'schedule').first()
    if batch is None:
        batch = _create_next_batch(course)
    return redirect('batch_attendance', batch_id=batch.pk)


@login_required
def college_admin_dashboard(request):
    if not request.user.is_college_admin:
        return HttpResponse('College administrator access is required.', status=403)
    users = User.objects.exclude(is_superuser=True).order_by('username')
    role_filter = request.GET.get('role')
    if role_filter in (User.Role.STUDENT, User.Role.INSTRUCTOR, User.Role.FACULTY):
        users = users.filter(role=role_filter)
    search = request.GET.get('q', '').strip()
    if search:
        users = users.filter(
            Q(username__icontains=search)
            | Q(first_name__icontains=search)
            | Q(last_name__icontains=search)
            | Q(email__icontains=search)
        )
    courses = Course.objects.select_related('instructor', 'skill').order_by('-created_at')
    pending_courses = courses.filter(approval_status=Course.ApprovalStatus.PENDING)
    pending_teachers = User.objects.filter(role=User.Role.INSTRUCTOR, instructor_approved=False)
    pending_certificates = CertificateRequest.objects.filter(
        status=CertificateRequest.Status.PENDING,
    ).select_related('student', 'course')
    pending_applications = CourseApplication.objects.filter(
        status=CourseApplication.Status.PENDING,
    ).select_related('student', 'course', 'course__instructor', 'batch', 'department')
    return render(request, 'college_admin_dashboard.html', {
        'users': Paginator(users, 12).get_page(request.GET.get('users_page')),
        'courses': Paginator(courses, 10).get_page(request.GET.get('courses_page')),
        'pending_courses': pending_courses,
        'pending_teachers': pending_teachers,
        'pending_certificates': pending_certificates,
        'pending_applications': pending_applications,
        'search': search,
        'role_filter': role_filter,
        'student_count': User.objects.filter(role=User.Role.STUDENT).count(),
        'teacher_count': User.objects.filter(
            Q(role=User.Role.FACULTY) | Q(role=User.Role.INSTRUCTOR, instructor_approved=True)
        ).count(),
        'course_count': Course.objects.filter(approval_status=Course.ApprovalStatus.APPROVED).count(),
        'pending_course_count': pending_courses.count(),
        'enrollment_count': Enrollment.objects.count(),
    })


@login_required
def approve_teacher(request, user_id):
    if request.method != 'POST':
        return HttpResponse(status=405)
    if not request.user.is_college_admin:
        return HttpResponse('College administrator access is required.', status=403)
    teacher = get_object_or_404(User, pk=user_id, role=User.Role.INSTRUCTOR)
    teacher.instructor_approved = True
    teacher.save(update_fields=['instructor_approved'])
    messages.success(request, f'{teacher.get_full_name() or teacher.username} is now an approved teacher.')
    return redirect('college_admin_dashboard')


@login_required
def toggle_user_active(request, user_id):
    if request.method != 'POST':
        return HttpResponse(status=405)
    if not request.user.is_college_admin:
        return HttpResponse('College administrator access is required.', status=403)
    target = get_object_or_404(User, pk=user_id)
    if target.pk == request.user.pk or target.is_superuser or target.is_staff:
        messages.error(request, 'This administrator account cannot be changed here.')
        return redirect('college_admin_dashboard')
    target.is_active = not target.is_active
    target.save(update_fields=['is_active'])
    messages.success(request, f'{target.username} is now {"active" if target.is_active else "inactive"}.')
    return redirect('college_admin_dashboard')


@login_required
def review_course(request, course_id):
    if request.method != 'POST':
        return HttpResponse(status=405)
    if not request.user.is_college_admin:
        return HttpResponse('College administrator access is required.', status=403)
    course = get_object_or_404(Course, pk=course_id)
    decision = request.POST.get('decision')
    if decision not in (Course.ApprovalStatus.APPROVED, Course.ApprovalStatus.REJECTED):
        messages.error(request, 'Choose a valid course review decision.')
    elif decision == Course.ApprovalStatus.APPROVED and (
        not course.instructor.is_active or not course.instructor.is_teacher
    ):
        messages.error(request, 'Approve the course instructor before approving this course.')
    else:
        course.approval_status = decision
        course.status = (
            Course.Status.PUBLISHED
            if decision == Course.ApprovalStatus.APPROVED
            else Course.Status.DRAFT
        )
        course.reviewed_by = request.user
        course.reviewed_at = timezone.now()
        course.save(update_fields=('approval_status', 'status', 'reviewed_by', 'reviewed_at'))
        messages.success(request, f'Course “{course.title}” was {decision}.')
    return redirect('college_admin_dashboard')


@login_required
def export_report(request, report_type):
    if not request.user.is_college_admin:
        return HttpResponse('College administrator access is required.', status=403)
    if report_type not in ('students', 'courses', 'certificates'):
        return HttpResponse('Unknown report type.', status=404)
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="skillora-{report_type}.csv"'
    writer = csv.writer(response)

    def write_row(values):
        safe_values = [
            f"'{value}" if isinstance(value, str) and value[:1] in ('=', '+', '-', '@', '\t', '\r') else value
            for value in values
        ]
        writer.writerow(safe_values)

    if report_type == 'students':
        write_row(('username', 'name', 'email', 'department', 'active', 'joined_at'))
        for student in User.objects.filter(role=User.Role.STUDENT).order_by('username'):
            write_row((student.username, student.get_full_name(), student.email, student.department, student.is_active, student.date_joined.isoformat()))
    elif report_type == 'courses':
        write_row(('title', 'teacher', 'approval_status', 'status', 'enrollments', 'created_at'))
        for course in Course.objects.select_related('instructor').annotate(enrollment_count=Count('enrollments')):
            write_row((course.title, course.instructor.username, course.approval_status, course.status, course.enrollment_count, course.created_at.isoformat()))
    elif report_type == 'certificates':
        write_row(('student', 'course', 'status', 'certificate_number', 'requested_at', 'issued_at'))
        for certificate in CertificateRequest.objects.select_related('student', 'course'):
            write_row((certificate.student.username, certificate.course.title, certificate.status, certificate.certificate_number, certificate.requested_at.isoformat(), certificate.issued_at.isoformat() if certificate.issued_at else ''))
    return response


def marketplace(request):
    courses = _public_courses().select_related('instructor', 'skill')
    query = request.GET.get('q', '').strip()
    if query:
        courses = courses.filter(Q(title__icontains=query) | Q(skill__title__icontains=query))
    category = request.GET.get('category')
    if category:
        courses = courses.filter(skill__category__icontains=category)
    department_slug = request.GET.get('department')
    if department_slug:
        courses = courses.filter(department__slug=department_slug)
    mode = request.GET.get('mode')
    if mode in (Course.Mode.ONLINE, Course.Mode.OFFLINE):
        courses = courses.filter(mode=mode)
    skill_list = Skill.objects.all()
    return render(request, 'marketplace.html', {
        'courses': Paginator(courses, 9).get_page(request.GET.get('page')),
        'skill_list': skill_list,
        'department_list': Department.objects.all(),
        'query': query,
        'current_category': category,
        'current_mode': mode,
        'current_department': department_slug,
    })


def departments_page(request):
    departments = Department.objects.prefetch_related(
        Prefetch(
            'courses',
            queryset=_public_courses().select_related('instructor', 'department').prefetch_related('batches'),
        ),
    )
    return render(request, 'departments.html', {'departments': departments})


def course_detail(request, slug):
    course = get_object_or_404(
        Course.objects.select_related('instructor', 'skill', 'department').prefetch_related('batches'),
        slug=slug,
    )
    is_public = (
        course.status == Course.Status.PUBLISHED
        and course.approval_status == Course.ApprovalStatus.APPROVED
        and course.instructor.is_active
        and course.instructor.is_teacher
    )
    can_preview = request.user.is_authenticated and (
        request.user.is_college_admin or course.instructor_id == request.user.pk
    )
    if not is_public and not can_preview:
        return HttpResponse(status=404)
    application_status = None
    if request.user.is_authenticated and request.user.is_student:
        application_status = CourseApplication.objects.filter(
            student=request.user,
            course=course,
        ).order_by('-applied_at').first()
    batches = list(course.batches.filter(is_open=True).order_by('start_date', 'schedule'))
    if request.user.is_authenticated and request.user.is_teacher:
        batches = list(course.batches.filter(is_open=True).order_by('start_date', 'schedule'))
    return render(request, 'course_detail.html', {
        'course': course,
        'application_status': application_status,
        'batches': batches,
    })


@login_required
def apply_course(request, slug):
    if not request.user.is_student:
        return HttpResponse('Only student accounts can apply for courses.', status=403)
    course = get_object_or_404(_public_courses().select_related('department', 'instructor'), slug=slug)
    if course.department_id is None:
        messages.error(request, 'This course is not assigned to a department yet. Please contact a Skillora administrator.')
        return redirect('course_detail', slug=course.slug)
    accepted = CourseApplication.objects.filter(
        student=request.user,
        course=course,
        status=CourseApplication.Status.ACCEPTED,
    ).exists()
    if accepted:
        messages.info(request, 'You already have an accepted application for this course.')
        return redirect('student_dashboard')
    pending = CourseApplication.objects.filter(
        student=request.user,
        course=course,
        status=CourseApplication.Status.PENDING,
    ).first()
    if pending:
        messages.info(request, 'Your application for this course is already awaiting review.')
        return redirect('student_dashboard')

    if not course.batches.exists():
        _create_next_batch(course)
    suggested_batch = _next_open_batch(course)
    if request.method == 'POST':
        form = CourseApplicationForm(request.POST, course=course, user=request.user)
        if form.is_valid():
            batch = form.cleaned_data['batch']
            if batch.is_full:
                next_batch = _next_open_batch(course)
                messages.warning(
                    request,
                    f'{batch.name} is full. Apply for the next available batch: {next_batch.start_date:%B %d, %Y}, {next_batch.schedule}.',
                )
                return render(request, 'apply_course.html', {
                    'course': course,
                    'form': CourseApplicationForm(
                        course=course,
                        user=request.user,
                        initial={'batch': next_batch.pk, 'preferred_mode': next_batch.mode},
                    ),
                    'batches': course.batches.filter(is_open=True).order_by('start_date', 'schedule'),
                })
            try:
                with transaction.atomic():
                    locked_batch = Batch.objects.select_for_update().select_related('course').get(pk=batch.pk)
                    if locked_batch.is_full or not locked_batch.is_open:
                        next_batch = _next_open_batch(course)
                        messages.warning(
                            request,
                            f'That batch filled while you were applying. The next batch is {next_batch.start_date:%B %d, %Y}, {next_batch.schedule}.',
                        )
                        return render(request, 'apply_course.html', {
                            'course': course,
                            'form': CourseApplicationForm(
                                course=course,
                                user=request.user,
                                initial={'batch': next_batch.pk, 'preferred_mode': next_batch.mode},
                            ),
                            'batches': course.batches.filter(is_open=True).order_by('start_date', 'schedule'),
                        })
                    application = CourseApplication.objects.create(
                        student=request.user,
                        course=course,
                        batch=locked_batch,
                        department=form.cleaned_data['department'],
                        applicant_name=form.cleaned_data['applicant_name'],
                        college_email=form.cleaned_data['college_email'],
                        preferred_mode=form.cleaned_data['preferred_mode'],
                    )
            except IntegrityError:
                messages.info(request, 'You already applied for this batch.')
                return redirect('student_dashboard')
            _notify_student(
                application,
                'Course application submitted',
                f'Your application for {course.title} ({batch.name}) is pending teacher or college review.',
            )
            messages.success(request, 'Your application is pending review. You will see its status on your dashboard.')
            return redirect('student_dashboard')
    else:
        form = CourseApplicationForm(
            course=course,
            user=request.user,
            initial={'batch': suggested_batch.pk, 'preferred_mode': suggested_batch.mode},
        )
    return render(request, 'apply_course.html', {
        'course': course,
        'form': form,
        'batches': course.batches.filter(is_open=True).order_by('start_date', 'schedule'),
    })


@login_required
def create_course(request):
    if not request.user.is_teacher:
        messages.error(request, 'Only approved teachers and faculty can create courses.')
        return redirect('dashboard')
    if request.method == 'POST':
        form = CourseForm(request.POST)
        if form.is_valid():
            course = form.save(commit=False)
            course.instructor = request.user
            course.status = Course.Status.DRAFT
            course.approval_status = Course.ApprovalStatus.PENDING
            course.save()
            messages.success(request, 'Your course has been submitted for college approval.')
            return redirect('teacher_dashboard')
    else:
        form = CourseForm()
    return render(request, 'create_course.html', {'form': form})


@login_required
def edit_course(request, slug):
    course = get_object_or_404(Course, slug=slug, instructor=request.user)
    if not request.user.is_teacher:
        return HttpResponse('Approved teacher access is required.', status=403)
    if request.method == 'POST':
        form = CourseForm(request.POST, instance=course)
        if form.is_valid():
            course = form.save(commit=False)
            course.status = Course.Status.DRAFT
            course.approval_status = Course.ApprovalStatus.PENDING
            course.reviewed_by = None
            course.reviewed_at = None
            course.save()
            messages.success(request, 'Course changes were submitted for approval.')
            return redirect('teacher_dashboard')
    else:
        form = CourseForm(instance=course)
    return render(request, 'create_course.html', {'form': form, 'editing': True})


@login_required
def create_batch(request, slug):
    course = get_object_or_404(Course, slug=slug)
    if not request.user.is_college_admin and (
        not request.user.is_teacher or course.instructor_id != request.user.pk
    ):
        return HttpResponse('Only the assigned teacher or college administrator can manage batches.', status=403)
    if request.method == 'POST':
        form = BatchForm(request.POST)
        if form.is_valid():
            batch = form.save(commit=False)
            batch.course = course
            batch.capacity = 10
            batch.save()
            messages.success(request, f'{batch.name} was added with a maximum of 10 accepted students.')
            return redirect('teacher_dashboard' if not request.user.is_college_admin else 'college_admin_dashboard')
    else:
        form = BatchForm(initial={
            'name': f'Batch {course.batches.count() + 1}',
            'schedule': course.schedule,
            'mode': course.mode,
            'venue': course.venue,
            'meeting_link': course.meeting_link,
        })
    return render(request, 'create_batch.html', {'course': course, 'form': form})


@login_required
def review_application(request, application_id):
    if request.method != 'POST':
        return HttpResponse(status=405)
    application = get_object_or_404(
        CourseApplication.objects.select_related('course', 'student', 'batch', 'department'),
        pk=application_id,
    )
    if not request.user.is_college_admin and (
        not request.user.is_teacher or application.course.instructor_id != request.user.pk
    ):
        return HttpResponse('Only the assigned teacher or college administrator can review applications.', status=403)
    decision = request.POST.get('decision')
    if decision not in (CourseApplication.Status.ACCEPTED, CourseApplication.Status.REJECTED):
        messages.error(request, 'Choose Accept or Reject.')
        return redirect('teacher_dashboard')
    if application.status != CourseApplication.Status.PENDING:
        messages.error(request, 'This application has already been reviewed.')
        return redirect('teacher_dashboard')
    if decision == CourseApplication.Status.ACCEPTED and (
        application.course.approval_status != Course.ApprovalStatus.APPROVED
        or application.course.status != Course.Status.PUBLISHED
        or not application.course.instructor.is_active
        or not application.course.instructor.is_teacher
    ):
        messages.error(request, 'This course must be approved before student applications can be accepted.')
        return redirect('teacher_dashboard')

    with transaction.atomic():
        application = CourseApplication.objects.select_for_update().select_related(
            'course', 'student', 'batch', 'department',
        ).get(pk=application.pk)
        if decision == CourseApplication.Status.ACCEPTED:
            batch = Batch.objects.select_for_update().get(pk=application.batch_id)
            if batch.is_full or not batch.is_open:
                next_batch = _next_open_batch(application.course)
                duplicate = CourseApplication.objects.filter(
                    student=application.student,
                    batch=next_batch,
                ).exclude(pk=application.pk).exists()
                if duplicate:
                    messages.warning(
                        request,
                        f'{batch.name} is full. The student already has an application for {next_batch.name}.',
                    )
                    return redirect('teacher_dashboard')
                application.batch = next_batch
                application.reviewed_by = None
                application.reviewed_at = None
                application.save(update_fields=('batch', 'reviewed_by', 'reviewed_at'))
                _notify_student(
                    application,
                    'A later batch is available',
                    f'{batch.name} was full. Your pending application was moved to {next_batch.name}: {next_batch.start_date:%B %d, %Y}, {next_batch.schedule}.',
                )
                messages.warning(
                    request,
                    f'{batch.name} is full. The application remains pending for {next_batch.name} ({next_batch.start_date:%B %d, %Y}, {next_batch.schedule}).',
                )
                return redirect('teacher_dashboard')
            application.status = CourseApplication.Status.ACCEPTED
            enrollment, _ = Enrollment.objects.get_or_create(
                student=application.student,
                course=application.course,
                defaults={
                    'batch': batch,
                    'status': Enrollment.Status.ENROLLED,
                },
            )
            if enrollment.batch_id != batch.pk:
                enrollment.batch = batch
                enrollment.status = Enrollment.Status.ENROLLED
                enrollment.save(update_fields=('batch', 'status'))
        else:
            application.status = CourseApplication.Status.REJECTED
        application.reviewed_by = request.user
        application.reviewed_at = timezone.now()
        application.save(update_fields=('status', 'reviewed_by', 'reviewed_at'))

    label = 'accepted' if decision == CourseApplication.Status.ACCEPTED else 'rejected'
    _notify_student(
        application,
        f'Application {label}',
        f'Your application for {application.course.title} ({application.batch.name}) was {label}.',
    )
    try:
        sent = _send_application_email(application)
    except (SMTPException, OSError, ValueError) as error:
        messages.error(
            request,
            f'Application {label}, but the notification email could not be sent ({error}).',
        )
    else:
        if sent:
            if settings.EMAIL_BACKEND == 'django.core.mail.backends.console.EmailBackend':
                messages.success(request, f'Application {label}. The email was printed to the development console and was not delivered.')
            else:
                messages.success(request, f'Application {label} and email sent to {application.college_email}.')
        else:
            messages.error(request, f'Application {label}, but the email backend did not confirm delivery.')
    return redirect('teacher_dashboard' if not request.user.is_college_admin else 'college_admin_dashboard')


@login_required
def batch_attendance(request, batch_id):
    batch = get_object_or_404(Batch.objects.select_related('course'), pk=batch_id)
    if not request.user.is_college_admin and (
        not request.user.is_teacher or batch.course.instructor_id != request.user.pk
    ):
        return HttpResponse('Only the assigned teacher or college administrator can manage attendance.', status=403)
    applications = list(CourseApplication.objects.filter(
        batch=batch,
        status=CourseApplication.Status.ACCEPTED,
    ).select_related('student', 'department').order_by('applicant_name'))
    attendance_date = timezone.localdate()
    if request.method == 'POST':
        attendance_date = parse_date(request.POST.get('session_date', ''))
        if attendance_date is None:
            messages.error(request, 'Choose a valid class date.')
            attendance_date = timezone.localdate()
        else:
            with transaction.atomic():
                for application in applications:
                    present = request.POST.get(f'present_{application.pk}') == 'on'
                    AttendanceRecord.objects.update_or_create(
                        course=batch.course,
                        batch=batch,
                        student=application.student,
                        session_date=attendance_date,
                        defaults={
                            'present': present,
                            'recorded_by': request.user,
                            'verified_by': request.user,
                        },
                    )
                total_sessions = AttendanceRecord.objects.filter(batch=batch).values('session_date').distinct().count()
                newly_completed = []
                for application in applications:
                    if request.POST.get(f'complete_{application.pk}') != 'on':
                        continue
                    present_count = AttendanceRecord.objects.filter(
                        batch=batch,
                        student=application.student,
                        present=True,
                    ).count()
                    percentage = round(present_count * 100 / total_sessions) if total_sessions else 0
                    if percentage < 75:
                        messages.warning(
                            request,
                            f'{application.applicant_name} needs at least 75% attendance before course completion can be verified ({percentage}% recorded).',
                        )
                        continue
                    enrollment = Enrollment.objects.filter(
                        student=application.student,
                        course=batch.course,
                    ).first()
                    if enrollment:
                        enrollment.completed = True
                        enrollment.status = Enrollment.Status.COMPLETED
                        enrollment.completion_date = attendance_date
                        enrollment.completion_verified_by = request.user
                        enrollment.save(update_fields=(
                            'completed',
                            'status',
                            'completion_date',
                            'completion_verified_by',
                        ))
                        CertificateRequest.objects.get_or_create(
                            student=application.student,
                            course=batch.course,
                            defaults={'completion_date': attendance_date},
                        )
                        newly_completed.append(application)
                for application in newly_completed:
                    _notify_student(
                        application,
                        'Course completion verified',
                        f'Your completion of {batch.course.title} was verified. A certificate request is now awaiting authorized review.',
                    )
            messages.success(request, 'Attendance for the class date was saved.')
            return redirect('batch_attendance', batch_id=batch.pk)

    total_sessions = AttendanceRecord.objects.filter(batch=batch).values('session_date').distinct().count()
    students = []
    for application in applications:
        rows = AttendanceRecord.objects.filter(
            batch=batch,
            student=application.student,
        )
        present_count = rows.filter(present=True).count()
        todays_record = rows.filter(session_date=attendance_date).first()
        enrollment = Enrollment.objects.filter(student=application.student, course=batch.course).first()
        students.append({
            'application': application,
            'present_count': present_count,
            'total_sessions': total_sessions,
            'attendance_percent': round(present_count * 100 / total_sessions) if total_sessions else 0,
            'present_today': todays_record.present if todays_record else False,
            'completed': bool(enrollment and enrollment.completed),
        })
    return render(request, 'batch_attendance.html', {
        'batch': batch,
        'students': students,
        'attendance_date': attendance_date,
    })


@login_required
def request_session(request):
    if not (request.user.is_student or request.user.is_teacher):
        messages.error(request, 'Only students and approved teachers can request learning sessions.')
        return redirect('dashboard')
    if request.method == 'POST':
        form = SessionRequestForm(request.POST)
        if form.is_valid():
            recipient_id = request.POST.get('to_user')
            recipients = User.objects.filter(
                Q(role=User.Role.STUDENT)
                | Q(role=User.Role.FACULTY)
                | Q(role=User.Role.INSTRUCTOR, instructor_approved=True),
                is_active=True,
            ).exclude(pk=request.user.pk)
            recipient = recipients.filter(pk=recipient_id).first()
            if recipient is None:
                messages.error(request, 'Select an eligible student or approved teacher.')
            else:
                session = form.save(commit=False)
                session.from_user = request.user
                session.to_user = recipient
                session.save()
                messages.success(request, 'Your learning session request has been sent.')
                return redirect('dashboard')
    else:
        form = SessionRequestForm()
    recipients = User.objects.filter(
        Q(role=User.Role.STUDENT)
        | Q(role=User.Role.FACULTY)
        | Q(role=User.Role.INSTRUCTOR, instructor_approved=True),
        is_active=True,
    ).exclude(pk=request.user.pk)
    return render(request, 'request_session.html', {'form': form, 'recipients': recipients})


@login_required
def decide_session(request, session_id):
    if request.method != 'POST':
        return HttpResponse(status=405)
    session = get_object_or_404(SessionRequest, pk=session_id)
    if session.to_user_id != request.user.pk:
        return HttpResponse('Only the invited recipient can respond.', status=403)
    decision = request.POST.get('decision')
    if session.status != SessionRequest.Status.PENDING or decision not in (
        SessionRequest.Status.ACCEPTED,
        SessionRequest.Status.REJECTED,
    ):
        messages.error(request, 'This session request cannot be updated.')
    else:
        session.status = decision
        session.save(update_fields=['status'])
        messages.success(request, f'Session request {decision}.')
    return redirect('dashboard')

@login_required
def request_certificate(request, course_id):
    if not request.user.is_student:
        return HttpResponse('Only students can request certificates.', status=403)
    course = get_object_or_404(Course, pk=course_id)
    enrollment = get_object_or_404(Enrollment, course=course, student=request.user)
    if not enrollment.completed or not enrollment.completion_verified_by_id:
        messages.warning(request, 'Your instructor must verify course completion before you can request a certificate.')
        return redirect('dashboard')

    certificate, created = CertificateRequest.objects.get_or_create(
        student=request.user,
        course=course,
        defaults={
            'status': CertificateRequest.Status.PENDING,
            'completion_date': enrollment.completion_date,
        },
    )
    if not created:
        messages.info(request, 'A certificate request already exists for this course.')
        return redirect('dashboard')

    messages.success(request, 'Your certificate request has been submitted for faculty review.')
    return redirect('dashboard')


@login_required
def review_certificate(request, certificate_id):
    certificate = get_object_or_404(CertificateRequest, pk=certificate_id)
    if not request.user.is_faculty and not request.user.is_college_admin:
        return HttpResponse('Faculty or college administrator access is required.', status=403)
    if request.method == 'POST':
        form = CertificateStatusForm(request.POST)
        if form.is_valid():
            decision = form.cleaned_data['status']
            if decision == CertificateRequest.Status.APPROVED and not Enrollment.objects.filter(
                student=certificate.student,
                course=certificate.course,
                completed=True,
                completion_verified_by__isnull=False,
            ).exists():
                messages.error(request, 'This student does not have instructor-verified course completion.')
                return redirect('dashboard')
            enrollment = Enrollment.objects.filter(
                student=certificate.student,
                course=certificate.course,
                completed=True,
                completion_verified_by__isnull=False,
            ).first()
            if decision == CertificateRequest.Status.APPROVED and not (
                certificate.completion_date or (enrollment and enrollment.completion_date)
            ):
                messages.error(request, 'Record the verified course completion date before issuing a certificate.')
                return redirect('dashboard')
            certificate.status = decision
            certificate.reviewed_by = request.user
            if decision == CertificateRequest.Status.APPROVED:
                if not certificate.certificate_number:
                    certificate.certificate_number = f"SKL-{certificate.pk:08d}"
                certificate.issued_at = timezone.now()
                if not certificate.completion_date:
                    certificate.completion_date = enrollment.completion_date
            elif decision == CertificateRequest.Status.REJECTED:
                certificate.certificate_number = ''
                certificate.issued_at = None
            certificate.notes = form.cleaned_data['notes']
            certificate.save()
            messages.success(request, 'Certificate request updated.')
            return redirect('dashboard')
    else:
        initial_status = (
            ''
            if certificate.status == CertificateRequest.Status.PENDING
            else certificate.status
        )
        form = CertificateStatusForm(initial={'status': initial_status, 'notes': certificate.notes})
    return render(request, 'review_certificate.html', {'certificate': certificate, 'form': form})


def _certificate_verification_url(request, certificate):
    return request.build_absolute_uri(
        reverse('verify_certificate', args=(certificate.pk,))
    )


def _certificate_college_name():
    return COLLEGE_NAME if 'coimbatore' in COLLEGE_NAME.casefold() else f'{COLLEGE_NAME}, Coimbatore'


@login_required
def view_certificate(request, certificate_id):
    certificate = get_object_or_404(
        CertificateRequest.objects.select_related(
            'student',
            'course',
            'course__department',
            'course__instructor',
            'reviewed_by',
        ),
        pk=certificate_id,
        status=CertificateRequest.Status.APPROVED,
    )
    if (
        request.user != certificate.student
        and not request.user.is_faculty
        and not request.user.is_college_admin
    ):
        return HttpResponse('Unauthorized', status=403)
    return render(request, 'certificate.html', {
        'certificate': certificate,
        'college_name': _certificate_college_name(),
        'verification_url': _certificate_verification_url(request, certificate),
    })


def certificate_qr(request, certificate_id):
    certificate = get_object_or_404(
        CertificateRequest.objects.filter(status=CertificateRequest.Status.APPROVED),
        pk=certificate_id,
    )
    if renderSVG is None or QrCodeWidget is None or Drawing is None:
        return HttpResponse('QR code generation is unavailable.', status=500)
    code = QrCodeWidget(_certificate_verification_url(request, certificate))
    bounds = code.getBounds()
    drawing = Drawing(bounds[2] - bounds[0], bounds[3] - bounds[1])
    drawing.add(code)
    response = HttpResponse(renderSVG.drawToString(drawing), content_type='image/svg+xml')
    response['Cache-Control'] = 'public, max-age=300'
    return response


@login_required
def download_certificate(request, certificate_id):
    certificate = get_object_or_404(
        CertificateRequest.objects.select_related(
            'student',
            'course',
            'course__department',
            'course__instructor',
            'reviewed_by',
        ),
        pk=certificate_id,
    )
    if (
        request.user != certificate.student
        and not request.user.is_faculty
        and not request.user.is_college_admin
    ):
        return HttpResponse('Unauthorized', status=403)
    if certificate.status != CertificateRequest.Status.APPROVED:
        messages.warning(request, 'This certificate is not approved yet.')
        return redirect('dashboard')

    if canvas is None or renderPDF is None:
        return HttpResponse('PDF library unavailable.', status=500)

    issue_date = certificate.issued_at.date() if certificate.issued_at else timezone.localdate()
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=landscape(A4), pageCompression=1)
    width, height = landscape(A4)
    margin = 25
    green = HexColor('#174b3a')
    dark_green = HexColor('#10382c')
    mint = HexColor('#e8f3ed')
    muted = HexColor('#65756e')
    text = HexColor('#28352f')
    student_name = certificate.student.get_full_name() or certificate.student.username
    department = certificate.course.department.name if certificate.course.department_id else 'Not recorded'
    instructor = certificate.course.instructor.get_full_name() or certificate.course.instructor.username
    reviewer = (
        certificate.reviewed_by.get_full_name() or certificate.reviewed_by.username
        if certificate.reviewed_by_id
        else 'Not recorded'
    )
    verification_url = _certificate_verification_url(request, certificate)

    def draw_fitted_centered(value, y, font_name, font_size, max_width=width - 100):
        size = font_size
        while size > 8 and pdf.stringWidth(value, font_name, size) > max_width:
            size -= 1
        pdf.setFont(font_name, size)
        pdf.drawCentredString(width / 2, y, value)

    pdf.setTitle(f'{certificate.student.get_full_name() or certificate.student.username} - Certificate')
    pdf.setFillColor(HexColor('#ffffff'))
    pdf.rect(0, 0, width, height, fill=1, stroke=0)
    pdf.setStrokeColor(green)
    pdf.setLineWidth(2.2)
    pdf.roundRect(margin, margin, width - margin * 2, height - margin * 2, 10, fill=0, stroke=1)
    pdf.setStrokeColor(HexColor('#a9cbb9'))
    pdf.setLineWidth(0.7)
    pdf.roundRect(margin + 7, margin + 7, width - (margin + 7) * 2, height - (margin + 7) * 2, 7, fill=0, stroke=1)

    pdf.saveState()
    pdf.setFillColor(mint)
    pdf.setFont('Helvetica-Bold', 72)
    pdf.drawCentredString(width / 2, height / 2 - 20, 'SKILLORA')
    pdf.restoreState()

    pdf.setFillColor(green)
    pdf.circle(72, height - 70, 25, fill=1, stroke=0)
    pdf.setFillColor(HexColor('#ffffff'))
    pdf.setFont('Helvetica-Bold', 20)
    pdf.drawCentredString(72, height - 77, 'S')
    pdf.setFillColor(muted)
    pdf.setFont('Helvetica-Bold', 8)
    pdf.drawString(108, height - 63, 'SKILLORA')
    pdf.setFont('Helvetica', 7)
    pdf.drawString(108, height - 76, 'STUDENT SKILL EXCHANGE')

    pdf.setFillColor(dark_green)
    draw_fitted_centered(_certificate_college_name(), height - 54, 'Helvetica-Bold', 12)
    pdf.setFillColor(muted)
    pdf.setFont('Helvetica', 8)
    pdf.drawCentredString(width / 2, height - 69, 'Learning context | Skillora platform record')

    pdf.setStrokeColor(HexColor('#bdd8c9'))
    pdf.setLineWidth(1)
    pdf.line(width * 0.25, height - 91, width * 0.75, height - 91)
    pdf.setFillColor(green)
    pdf.setFont('Times-Bold', 26)
    pdf.drawCentredString(width / 2, height - 132, 'CERTIFICATE OF COMPLETION')
    pdf.setFillColor(muted)
    pdf.setFont('Times-Roman', 13)
    pdf.drawCentredString(width / 2, height - 163, 'This is to certify that')

    pdf.setFillColor(dark_green)
    draw_fitted_centered(student_name, height - 204, 'Times-Bold', 27, width - 150)
    pdf.setStrokeColor(HexColor('#83b49a'))
    pdf.setLineWidth(1)
    pdf.line(width * 0.32, height - 213, width * 0.68, height - 213)

    pdf.setFillColor(text)
    pdf.setFont('Times-Roman', 13)
    pdf.drawCentredString(width / 2, height - 242, 'has successfully completed the course')
    pdf.setFillColor(green)
    draw_fitted_centered(certificate.course.title, height - 274, 'Helvetica-Bold', 19, width - 160)
    pdf.setFillColor(text)
    pdf.setFont('Helvetica', 10)
    pdf.drawCentredString(width / 2, height - 296, f'offered through Skillora in the {department} department.')

    pdf.setFillColor(muted)
    draw_fitted_centered(
        f'Course instructor: {instructor}     |     Completion date: {certificate.completion_date:%B %d, %Y}',
        height - 322,
        'Helvetica',
        8,
        width - 160,
    )

    sign_y = 99
    pdf.setStrokeColor(HexColor('#9bb5a6'))
    pdf.setLineWidth(0.7)
    left_x, right_x = width * 0.27, width * 0.56
    pdf.line(left_x - 80, sign_y + 21, left_x + 80, sign_y + 21)
    pdf.line(right_x - 80, sign_y + 21, right_x + 80, sign_y + 21)
    pdf.setFillColor(dark_green)
    pdf.setFont('Helvetica-Bold', 9)
    pdf.drawCentredString(left_x, sign_y + 7, instructor)
    pdf.drawCentredString(right_x, sign_y + 7, reviewer)
    pdf.setFillColor(muted)
    pdf.setFont('Helvetica', 7)
    pdf.drawCentredString(left_x, sign_y - 5, 'Course instructor · signature not recorded')
    pdf.drawCentredString(right_x, sign_y - 5, 'Authorized Skillora reviewer · signature not recorded')

    pdf.setFont('Helvetica', 7)
    pdf.drawString(54, 53, f'Issue date: {issue_date:%B %d, %Y}')
    pdf.drawString(54, 40, f'Certificate ID: {certificate.certificate_number}')
    pdf.drawCentredString(
        width / 2,
        27,
        'Skillora-issued learning record. Not a college-issued credential or college endorsement.',
    )

    if QrCodeWidget is not None and Drawing is not None:
        qr = QrCodeWidget(verification_url)
        bounds = qr.getBounds()
        qr_drawing = Drawing(bounds[2] - bounds[0], bounds[3] - bounds[1])
        qr_drawing.add(qr)
        pdf.setFillColor(HexColor('#ffffff'))
        pdf.roundRect(width - 132, 38, 91, 91, 6, fill=1, stroke=0)
        renderPDF.draw(qr_drawing, pdf, width - 123, 47)
        pdf.setFillColor(muted)
        pdf.setFont('Helvetica', 6)
        pdf.drawCentredString(width - 86, 32, 'SCAN TO VERIFY')

    pdf.showPage()
    pdf.save()

    response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="skillora-certificate-{certificate.pk}.pdf"'
    return response


def verify_certificate(request, certificate_id):
    certificate = CertificateRequest.objects.select_related(
        'student',
        'course',
        'course__department',
        'course__instructor',
        'reviewed_by',
    ).filter(pk=certificate_id).first()
    is_valid = bool(
        certificate
        and certificate.status == CertificateRequest.Status.APPROVED
        and certificate.certificate_number
        and certificate.issued_at
    )
    return render(request, 'verify_certificate.html', {
        'certificate': certificate,
        'is_valid': is_valid,
        'college_name': COLLEGE_NAME,
    })
