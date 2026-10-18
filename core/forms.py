from django import forms
from django.contrib.auth.forms import UserCreationForm

from .models import Batch, Course, Department, Skill, SessionRequest, User


class CustomUserCreationForm(UserCreationForm):
    email = forms.EmailField(required=True)
    role = forms.ChoiceField(
        choices=(
            (User.Role.STUDENT, 'Student'),
            (User.Role.INSTRUCTOR, 'Apply as a teacher / student instructor'),
        ),
        initial=User.Role.STUDENT,
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ('username', 'email', 'role', 'password1', 'password2')

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data['email']
        user.role = self.cleaned_data['role']
        if user.role == User.Role.INSTRUCTOR:
            user.instructor_approved = False
        if commit:
            user.save()
        return user


class SkillForm(forms.ModelForm):
    class Meta:
        model = Skill
        fields = ('title', 'category', 'description')


class CourseForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['department'].required = True

    class Meta:
        model = Course
        fields = (
            'title',
            'slug',
            'description',
            'skill',
            'department',
            'learning_objectives',
            'prerequisites',
            'duration_weeks',
            'mode',
            'schedule',
            'venue',
            'meeting_link',
            'materials_link',
        )
        widgets = {
            'description': forms.Textarea(attrs={'rows': 4}),
            'learning_objectives': forms.Textarea(attrs={'rows': 3}),
            'prerequisites': forms.Textarea(attrs={'rows': 2}),
        }

    def clean_slug(self):
        slug = self.cleaned_data['slug']
        if slug.lower() == 'create':
            raise forms.ValidationError('This course URL is reserved.')
        return slug


class SessionRequestForm(forms.ModelForm):
    class Meta:
        model = SessionRequest
        fields = ('title', 'skill', 'preferred_slot', 'mode', 'venue', 'meeting_link', 'notes')


class CourseApplicationForm(forms.Form):
    applicant_name = forms.CharField(max_length=200, label='Student name')
    college_email = forms.EmailField(label='College email address')
    department = forms.ModelChoiceField(queryset=Department.objects.none())
    batch = forms.ModelChoiceField(queryset=Batch.objects.none(), label='Preferred class timing')
    preferred_mode = forms.ChoiceField(choices=Course.Mode.choices, label='Online or offline')

    def __init__(self, *args, course, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.course = course
        self.user = user
        self.fields['department'].queryset = Department.objects.all()
        self.fields['batch'].queryset = Batch.objects.filter(course=course, is_open=True).order_by('start_date', 'schedule')
        self.fields['department'].initial = Department.objects.filter(name__iexact=user.department).first()
        self.fields['applicant_name'].initial = user.get_full_name()
        self.fields['college_email'].initial = user.email
        self.fields['preferred_mode'].initial = course.mode

    def clean_college_email(self):
        email = self.cleaned_data['college_email']
        if email.casefold() != self.user.email.casefold():
            raise forms.ValidationError('Use the email address registered on your Skillora account.')
        return email

    def clean_batch(self):
        batch = self.cleaned_data['batch']
        if batch.course_id != self.course.pk or not batch.is_open:
            raise forms.ValidationError('Choose an open batch for this course.')
        return batch

    def clean(self):
        cleaned_data = super().clean()
        batch = cleaned_data.get('batch')
        preferred_mode = cleaned_data.get('preferred_mode')
        if batch and preferred_mode and batch.mode != preferred_mode:
            self.add_error('preferred_mode', 'Choose the same class mode as your selected batch.')
        return cleaned_data


class BatchForm(forms.ModelForm):
    class Meta:
        model = Batch
        fields = ('name', 'start_date', 'schedule', 'mode', 'venue', 'meeting_link')
        widgets = {'start_date': forms.DateInput(attrs={'type': 'date'})}


class ProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ('first_name', 'last_name', 'email', 'phone', 'department', 'bio')


class CertificateStatusForm(forms.Form):
    status = forms.ChoiceField(choices=(
        ('', 'Select a decision'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('revoked', 'Revoked'),
    ))
    notes = forms.CharField(widget=forms.Textarea, required=False)
