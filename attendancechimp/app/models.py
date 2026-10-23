"""
Data model for AttendanceChimp.

Entities (see app/docs/my-data-model.png):

    auth.User 1 ── 0..1 InstructorProfile 1 ── 0..* Course
    auth.User 1 ── 0..1 StudentProfile
    StudentProfile 0..* ── 0..* Course          (through Enrollment)
    Course 1 ── 0..* Lecture
    StudentProfile 1 ── 0..* QRCodeUpload
    Lecture 0..1 ── 0..* QRCodeUpload          (lecture is optional)

Why separate InstructorProfile / StudentProfile instead of one Users table?
    * Instructors and students carry different attributes (department/office
      vs. student ID/major). A single table would need many nullable columns
      that only make sense for one role.
    * Foreign keys can enforce roles at the database level: Course.instructor
      can only point at an instructor, Enrollment.student only at a student.
      With one Users table nothing stops a student from "teaching" a course.
    * Authentication stays in Django's built-in auth.User; the profiles hold
      only domain data, so login, passwords and permissions keep working as-is.
"""

import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class InstructorProfile(models.Model):
    """
    Instructor-specific data attached one-to-one to a Django auth user.

    Attributes:
        user:       The login account (one profile per user).
        department: Academic department, e.g. "Computer Science".
        office:     Optional office location.

    Reverse relations:
        courses:    All Course objects this instructor teaches.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="instructor_profile",
    )
    department = models.CharField(max_length=100, blank=True)
    office = models.CharField(max_length=100, blank=True)

    def __str__(self):
        return self.user.get_full_name() or self.user.username


class StudentProfile(models.Model):
    """
    Student-specific data attached one-to-one to a Django auth user.

    Attributes:
        user:            The login account (one profile per user).
        student_id:      University-issued ID, unique across students.
        major:           Optional declared major.
        graduation_year: Optional expected graduation year.

    Reverse relations:
        enrollments:  Enrollment rows for this student.
        courses:      Courses the student is enrolled in (via Enrollment).
        qr_uploads:   QRCodeUpload rows submitted by this student.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="student_profile",
    )
    student_id = models.CharField(max_length=20, unique=True)
    major = models.CharField(max_length=100, blank=True)
    graduation_year = models.PositiveSmallIntegerField(null=True, blank=True)

    def __str__(self):
        name = self.user.get_full_name() or self.user.username
        return f"{name} ({self.student_id})"

    def attended_lectures(self, course=None):
        """Return the distinct lectures this student uploaded a QR code for,
        optionally restricted to one course."""
        lectures = Lecture.objects.filter(qr_uploads__student=self)
        if course is not None:
            lectures = lectures.filter(course=course)
        return lectures.distinct()

    def attendance_rate(self, course):
        """Fraction (0.0–1.0) of a course's lectures this student attended.
        Returns 0.0 if the course has no lectures yet."""
        total = course.lectures.count()
        if total == 0:
            return 0.0
        return self.attended_lectures(course).count() / total


class Course(models.Model):
    """
    A course taught by one instructor, meeting on a regular weekly schedule.

    Attributes:
        code:         Unique course code, e.g. "CMSC 13600".
        name:         Human-readable title.
        instructor:   The InstructorProfile teaching the course.
        meeting_days: Days the course meets, as letters from "MTWRFSU"
                      (R = Thursday, S = Saturday, U = Sunday), e.g. "TR".
        start_time:   Time each meeting starts.
        end_time:     Time each meeting ends.
        start_date:   First day of the term (optional).
        end_date:     Last day of the term (optional).
        students:     Many-to-many to StudentProfile through Enrollment.

    Reverse relations:
        lectures:     Lecture objects for this course.
        enrollments:  Enrollment rows for this course.
    """

    DAY_LETTERS = "MTWRFSU"  # index matches date.weekday(): Monday == 0

    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=200)
    instructor = models.ForeignKey(
        InstructorProfile,
        on_delete=models.PROTECT,  # don't silently delete courses with an instructor
        related_name="courses",
    )
    meeting_days = models.CharField(max_length=7, help_text='e.g. "MWF" or "TR"')
    start_time = models.TimeField()
    end_time = models.TimeField()
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    students = models.ManyToManyField(
        StudentProfile,
        through="Enrollment",
        related_name="courses",
        blank=True,
    )

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return f"{self.code}: {self.name}"

    def clean(self):
        """Validate the schedule fields."""
        bad = set(self.meeting_days.upper()) - set(self.DAY_LETTERS)
        if bad:
            raise ValidationError(
                {"meeting_days": f"Invalid day letters: {''.join(sorted(bad))}"}
            )
        if self.start_time and self.end_time and self.end_time <= self.start_time:
            raise ValidationError("end_time must be after start_time.")
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValidationError("end_date must not be before start_date.")

    def meets_on(self, date):
        """Return True if the course is scheduled to meet on the given date."""
        if self.start_date and date < self.start_date:
            return False
        if self.end_date and date > self.end_date:
            return False
        return self.DAY_LETTERS[date.weekday()] in self.meeting_days.upper()

    def is_enrolled(self, student):
        """Return True if the given StudentProfile is enrolled in this course."""
        return self.enrollments.filter(student=student).exists()


class Enrollment(models.Model):
    """
    Junction table linking students to courses (many-to-many).

    Attributes:
        student:     The enrolled StudentProfile.
        course:      The Course enrolled in.
        enrolled_at: Timestamp the enrollment was created.

    A student can be enrolled in a given course at most once.
    """

    student = models.ForeignKey(
        StudentProfile, on_delete=models.CASCADE, related_name="enrollments"
    )
    course = models.ForeignKey(
        Course, on_delete=models.CASCADE, related_name="enrollments"
    )
    enrolled_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["student", "course"], name="unique_enrollment"
            )
        ]

    def __str__(self):
        return f"{self.student} in {self.course.code}"


class Lecture(models.Model):
    """
    A single class meeting of a course, identified by a QR code.

    Attributes:
        course:        The Course this lecture belongs to.
        date:          The date the lecture takes place.
        qr_identifier: Random UUID encoded in the QR code shown in class.
                       Unique, and generated automatically so it can't be
                       guessed from the course or date.

    Reverse relations:
        qr_uploads:    QRCodeUpload rows matched to this lecture.

    A course has at most one lecture per date.
    """

    course = models.ForeignKey(
        Course, on_delete=models.CASCADE, related_name="lectures"
    )
    date = models.DateField()
    qr_identifier = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    class Meta:
        ordering = ["course", "date"]
        constraints = [
            models.UniqueConstraint(
                fields=["course", "date"], name="unique_lecture_per_day"
            )
        ]

    def __str__(self):
        return f"{self.course.code} on {self.date}"

    def attendees(self):
        """Return the distinct StudentProfiles who uploaded a QR code for this lecture."""
        return StudentProfile.objects.filter(qr_uploads__lecture=self).distinct()


class QRCodeUpload(models.Model):
    """
    An image of a lecture QR code uploaded by a student as proof of attendance.

    Attributes:
        student:     The StudentProfile who uploaded the image.
        lecture:     The Lecture the QR code was matched to. Optional (nullable)
                     because the upload is saved first and matched afterwards;
                     it stays NULL if the code can't be read or matches no
                     lecture, so the raw upload is never lost.
        image:       The uploaded picture of the QR code.
        uploaded_at: Timestamp of the upload.

    Note: ImageField requires the Pillow package (pip install Pillow).
    """

    student = models.ForeignKey(
        StudentProfile, on_delete=models.CASCADE, related_name="qr_uploads"
    )
    lecture = models.ForeignKey(
        Lecture,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="qr_uploads",
    )
    image = models.ImageField(upload_to="qr_uploads/%Y/%m/%d/")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-uploaded_at"]

    def __str__(self):
        target = self.lecture if self.lecture else "unmatched"
        return f"{self.student} → {target} at {self.uploaded_at:%Y-%m-%d %H:%M}"

    def is_matched(self):
        """Return True if this upload has been linked to a lecture."""
        return self.lecture_id is not None

    def match_to_lecture(self, qr_value):
        """
        Link this upload to the Lecture whose qr_identifier equals qr_value
        (the string decoded from the image). Only matches if the student is
        enrolled in that lecture's course. Saves and returns the Lecture,
        or returns None if there is no valid match.
        """
        try:
            lecture = Lecture.objects.select_related("course").get(
                qr_identifier=uuid.UUID(str(qr_value))
            )
        except (ValueError, Lecture.DoesNotExist):
            return None
        if not lecture.course.is_enrolled(self.student):
            return None
        self.lecture = lecture
        self.save(update_fields=["lecture"])
        return lecture
