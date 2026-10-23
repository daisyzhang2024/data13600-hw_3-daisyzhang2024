# I used Claude with the prompt, "can you make a similar models.py file but allow multiple 
# lectures per day and duplicate check-ins, while also adding status fields for QRCodeUpload?"
import uuid

from django.conf import settings
from django.db import models


class InstructorProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="instructor_profile",
    )
    department = models.CharField(max_length=100, blank=True)
    office = models.CharField(max_length=100, blank=True)

    def __str__(self):
        return f"{self.user.get_full_name() or self.user.username} (Instructor)"


class StudentProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="student_profile",
    )
    student_id = models.CharField(max_length=20, unique=True)
    major = models.CharField(max_length=100, blank=True)
    graduation_year = models.PositiveSmallIntegerField(null=True, blank=True)

    def __str__(self):
        return f"{self.student_id} - {self.user.get_full_name() or self.user.username}"


class Course(models.Model):
    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=200)
    instructor = models.ForeignKey(
        InstructorProfile,
        on_delete=models.PROTECT,
        related_name="courses",
    )
    meeting_days = models.CharField(
        max_length=10,
        help_text='Day letters, e.g. "MWF" or "TR".',
    )
    start_time = models.TimeField()
    end_time = models.TimeField()
    start_date = models.DateField()
    end_date = models.DateField()

    def __str__(self):
        return f"{self.code}: {self.name}"


class Enrollment(models.Model):
    student = models.ForeignKey(
        StudentProfile,
        on_delete=models.CASCADE,
        related_name="enrollments",
    )
    course = models.ForeignKey(
        Course,
        on_delete=models.CASCADE,
        related_name="enrollments",
    )
    enrolled_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["student", "course"],
                name="unique_enrollment",
            )
        ]

    def __str__(self):
        return f"{self.student} in {self.course}"


class Lecture(models.Model):
    # No UNIQUE(course, date): a course can have several lectures per day.
    course = models.ForeignKey(
        Course,
        on_delete=models.CASCADE,
        related_name="lectures",
    )
    date = models.DateField()
    start_time = models.TimeField(
        null=True,
        blank=True,
        help_text="Distinguishes multiple lectures on the same day.",
    )
    qr_identifier = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    class Meta:
        ordering = ["date", "start_time"]

    def __str__(self):
        time = f" {self.start_time:%H:%M}" if self.start_time else ""
        return f"{self.course.code} on {self.date}{time}"


class QRCodeUpload(models.Model):
    # No uniqueness on (student, lecture): duplicate check-ins are allowed.

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        VERIFIED = "verified", "Verified"
        REJECTED = "rejected", "Rejected"

    student = models.ForeignKey(
        StudentProfile,
        on_delete=models.CASCADE,
        related_name="uploads",
    )
    lecture = models.ForeignKey(
        Lecture,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="uploads",
    )
    image = models.ImageField(upload_to="qr_uploads/%Y/%m/%d/")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    status_message = models.CharField(
        max_length=255,
        blank=True,
        help_text='Reason for the status, e.g. "QR code not readable".',
    )
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-uploaded_at"]

    def __str__(self):
        return f"{self.student} upload ({self.status}) at {self.uploaded_at:%Y-%m-%d %H:%M}"