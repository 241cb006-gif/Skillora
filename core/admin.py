from django.contrib import admin

from .models import AttendanceRecord, Batch, CertificateRequest, Course, CourseApplication, Department, Enrollment, SessionRequest, Skill, StudentNotification, User


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ('username', 'email', 'role', 'instructor_approved', 'department', 'is_active', 'is_staff')
    list_filter = ('role', 'instructor_approved', 'is_active', 'is_staff')
    search_fields = ('username', 'email', 'department')


@admin.register(Skill)
class SkillAdmin(admin.ModelAdmin):
    list_display = ('title', 'category', 'created_by')
    search_fields = ('title', 'category')


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug')
    search_fields = ('name',)


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ('title', 'department', 'instructor', 'mode', 'approval_status', 'status', 'max_learners')
    list_filter = ('department', 'approval_status', 'mode', 'status', 'instructor')
    search_fields = ('title', 'instructor__username')


@admin.register(Batch)
class BatchAdmin(admin.ModelAdmin):
    list_display = ('name', 'course', 'start_date', 'schedule', 'mode', 'capacity', 'is_open')
    list_filter = ('mode', 'is_open', 'start_date', 'course__department')
    search_fields = ('name', 'course__title', 'schedule')


@admin.register(CourseApplication)
class CourseApplicationAdmin(admin.ModelAdmin):
    list_display = ('applicant_name', 'course', 'batch', 'department', 'status', 'applied_at')
    list_filter = ('status', 'department', 'course')
    search_fields = ('applicant_name', 'college_email', 'student__username')


@admin.register(Enrollment)
class EnrollmentAdmin(admin.ModelAdmin):
    list_display = ('student', 'course', 'status', 'completed')
    list_filter = ('status', 'completed')


@admin.register(SessionRequest)
class SessionRequestAdmin(admin.ModelAdmin):
    list_display = ('title', 'from_user', 'to_user', 'status')
    list_filter = ('status', 'mode')


@admin.register(AttendanceRecord)
class AttendanceRecordAdmin(admin.ModelAdmin):
    list_display = ('student', 'course', 'session_date', 'present')
    list_filter = ('present', 'session_date')


@admin.register(CertificateRequest)
class CertificateRequestAdmin(admin.ModelAdmin):
    list_display = ('student', 'course', 'status', 'certificate_number')
    list_filter = ('status',)


@admin.register(StudentNotification)
class StudentNotificationAdmin(admin.ModelAdmin):
    list_display = ('student', 'title', 'is_read', 'created_at')
    list_filter = ('is_read', 'created_at')
    search_fields = ('student__username', 'title', 'message')
