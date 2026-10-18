from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models import Q
from django.core.validators import MaxValueValidator, MinValueValidator


class User(AbstractUser):
    class Role(models.TextChoices):
        STUDENT = 'student', 'Student'
        INSTRUCTOR = 'instructor', 'Teacher / Student Instructor'
        FACULTY = 'faculty', 'Faculty'

    role = models.CharField(max_length=20, choices=Role.choices, default=Role.STUDENT)
    instructor_approved = models.BooleanField(default=False)
    phone = models.CharField(max_length=30, blank=True)
    bio = models.TextField(blank=True)
    department = models.CharField(max_length=80, blank=True)
    avatar_url = models.URLField(blank=True)

    def __str__(self):
        return f"{self.get_full_name() or self.username} ({self.role})"

    @property
    def is_student(self):
        return self.role == self.Role.STUDENT

    @property
    def is_instructor(self):
        return self.role == self.Role.INSTRUCTOR

    @property
    def is_faculty(self):
        return self.role == self.Role.FACULTY

    @property
    def is_teacher(self):
        return self.is_faculty or (self.is_instructor and self.instructor_approved)

    @property
    def is_college_admin(self):
        return self.is_superuser or (self.is_staff and not self.is_instructor)


class Department(models.Model):
    name = models.CharField(max_length=120, unique=True)
    slug = models.SlugField(unique=True)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class Skill(models.Model):
    title = models.CharField(max_length=120)
    category = models.CharField(max_length=60)
    description = models.TextField()
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='skills')

    class Meta:
        ordering = ['title']

    def __str__(self):
        return self.title


class Course(models.Model):
    class Mode(models.TextChoices):
        ONLINE = 'online', 'Online'
        OFFLINE = 'offline', 'Offline'

    class Status(models.TextChoices):
        DRAFT = 'draft', 'Draft'
        PUBLISHED = 'published', 'Published'
        CLOSED = 'closed', 'Closed'

    class ApprovalStatus(models.TextChoices):
        PENDING = 'pending', 'Pending approval'
        APPROVED = 'approved', 'Approved'
        REJECTED = 'rejected', 'Rejected'

    title = models.CharField(max_length=180)
    slug = models.SlugField(unique=True)
    description = models.TextField()
    skill = models.ForeignKey(Skill, on_delete=models.SET_NULL, null=True, blank=True, related_name='courses')
    department = models.ForeignKey(
        Department,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='courses',
    )
    instructor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='courses_taught',
        limit_choices_to=Q(role__in=(User.Role.INSTRUCTOR, User.Role.FACULTY)),
    )
    learning_objectives = models.TextField(blank=True)
    prerequisites = models.TextField(blank=True)
    duration_weeks = models.PositiveIntegerField(default=4)
    mode = models.CharField(max_length=20, choices=Mode.choices, default=Mode.ONLINE)
    schedule = models.CharField(max_length=200)
    venue = models.CharField(max_length=200, blank=True)
    meeting_link = models.URLField(blank=True)
    max_learners = models.PositiveIntegerField(default=20)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PUBLISHED)
    approval_status = models.CharField(
        max_length=20,
        choices=ApprovalStatus.choices,
        default=ApprovalStatus.PENDING,
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='course_reviews',
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    materials_link = models.URLField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.title

    @property
    def available_slots(self):
        enrolled = self.enrollments.filter(
            status__in=(Enrollment.Status.ENROLLED, Enrollment.Status.COMPLETED),
        ).count()
        return max(self.max_learners - enrolled, 0)

    @property
    def is_full(self):
        return self.available_slots <= 0


class Batch(models.Model):
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='batches')
    name = models.CharField(max_length=100)
    start_date = models.DateField()
    schedule = models.CharField(max_length=200)
    mode = models.CharField(max_length=20, choices=Course.Mode.choices)
    venue = models.CharField(max_length=200, blank=True)
    meeting_link = models.URLField(blank=True)
    capacity = models.PositiveSmallIntegerField(
        default=10,
        validators=[MinValueValidator(1), MaxValueValidator(10)],
    )
    is_open = models.BooleanField(default=True)

    class Meta:
        ordering = ['start_date', 'schedule', 'id']
        constraints = [
            models.UniqueConstraint(fields=('course', 'name'), name='unique_batch_name_per_course'),
            models.CheckConstraint(condition=Q(capacity__gte=1, capacity__lte=10), name='batch_capacity_1_to_10'),
        ]

    def __str__(self):
        return f'{self.course.title} - {self.name}'

    @property
    def accepted_count(self):
        application_count = self.applications.filter(status=CourseApplication.Status.ACCEPTED).count()
        enrollment_count = self.enrollments.filter(
            status__in=(Enrollment.Status.ENROLLED, Enrollment.Status.COMPLETED),
        ).count()
        return max(application_count, enrollment_count)

    @property
    def available_seats(self):
        return max(self.capacity - self.accepted_count, 0)

    @property
    def is_full(self):
        return self.available_seats == 0


class CourseApplication(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        ACCEPTED = 'accepted', 'Accepted'
        REJECTED = 'rejected', 'Rejected'

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='course_applications',
    )
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='applications')
    batch = models.ForeignKey(Batch, on_delete=models.PROTECT, related_name='applications')
    department = models.ForeignKey(Department, on_delete=models.PROTECT, related_name='applications')
    applicant_name = models.CharField(max_length=200)
    college_email = models.EmailField()
    preferred_mode = models.CharField(max_length=20, choices=Course.Mode.choices)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    applied_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_course_applications',
    )
    review_note = models.TextField(blank=True)

    class Meta:
        ordering = ['-applied_at']
        constraints = [
            models.UniqueConstraint(fields=('student', 'batch'), name='unique_student_batch_application'),
        ]

    def __str__(self):
        return f'{self.student} / {self.course} / {self.status}'


class StudentNotification(models.Model):
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='skillora_notifications',
    )
    title = models.CharField(max_length=180)
    message = models.TextField()
    url = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.student.username}: {self.title}'


class Enrollment(models.Model):
    class Status(models.TextChoices):
        ENROLLED = 'enrolled', 'Enrolled'
        COMPLETED = 'completed', 'Completed'
        WAITLIST = 'waitlist', 'Waitlist'

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='enrollments',
        limit_choices_to={'role': User.Role.STUDENT},
    )
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='enrollments')
    batch = models.ForeignKey(
        Batch,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='enrollments',
    )
    enrolled_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ENROLLED)
    completed = models.BooleanField(default=False)
    completion_date = models.DateField(null=True, blank=True)
    completion_verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='verified_enrollments',
    )

    class Meta:
        unique_together = ('student', 'course')
        ordering = ['-enrolled_at']

    def __str__(self):
        return f"{self.student} -> {self.course}"


class SessionRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        ACCEPTED = 'accepted', 'Accepted'
        REJECTED = 'rejected', 'Rejected'
        CANCELLED = 'cancelled', 'Cancelled'

    from_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='session_requests_sent')
    to_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='session_requests_received')
    skill = models.ForeignKey(Skill, on_delete=models.SET_NULL, null=True, blank=True, related_name='session_requests')
    title = models.CharField(max_length=180)
    preferred_slot = models.CharField(max_length=200)
    mode = models.CharField(max_length=20, choices=Course.Mode.choices, default=Course.Mode.ONLINE)
    venue = models.CharField(max_length=200, blank=True)
    meeting_link = models.URLField(blank=True)
    notes = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.title} ({self.status})"


class AttendanceRecord(models.Model):
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='attendance_records')
    batch = models.ForeignKey(
        Batch,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='attendance_records',
    )
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='attendance_records')
    session_date = models.DateField()
    present = models.BooleanField(default=False)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='attendance_entered')
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='attendance_verified',
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('course', 'student', 'session_date')

    def __str__(self):
        return f"{self.student} - {self.course} - {self.session_date}"


class CertificateRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        APPROVED = 'approved', 'Approved'
        REJECTED = 'rejected', 'Rejected'
        REVOKED = 'revoked', 'Revoked'

    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='certificate_requests')
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='certificate_requests')
    requested_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='certificate_reviews',
    )
    issued_at = models.DateTimeField(null=True, blank=True)
    completion_date = models.DateField(null=True, blank=True)
    certificate_number = models.CharField(max_length=80, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-requested_at']
        unique_together = ('student', 'course')

    def __str__(self):
        return f"{self.student} / {self.course} / {self.status}"
