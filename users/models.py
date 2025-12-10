from django.db import models
from django.contrib.auth.models import User

# ---------------------------------------------
# User Profile
# ---------------------------------------------
class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    preferred_language = models.CharField(max_length=50, default="python")
    total_tests_taken = models.IntegerField(default=0)
    average_score = models.FloatField(default=0.0)

    def __str__(self):
        return self.user.username


# ---------------------------------------------
# User Learning Path Tracking (for RL)
# ---------------------------------------------
LANG_ORDER = ["python", "java", "cpp", "c"]
LEVELS = ["Beginner", "Intermediate", "Advanced"]

def default_lang():
    return LANG_ORDER[0]

def default_level():
    return LEVELS[0]

class UserPath(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="path")
    current_language = models.CharField(max_length=32, default=default_lang)
    current_level = models.CharField(max_length=16, default=default_level)
    badge_languages = models.JSONField(default=list, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    legend_badges = models.IntegerField(default=0)

    tests_taken_today = models.IntegerField(default=0)
    last_test_date = models.DateField(null=True, blank=True)

    def __str__(self):
        return f"{self.user.username} → {self.current_language} / {self.current_level}"


# ---------------------------------------------
# ✅ FINAL & ONLY TestResult MODEL
# ---------------------------------------------
class TestResult(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    language = models.CharField(max_length=32)
    difficulty = models.CharField(max_length=16)   # Beginner/Intermediate/Advanced
    score = models.IntegerField()
    hints_used = models.IntegerField(default=0)
    time_elapsed = models.IntegerField(default=0)  # seconds
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} {self.language}-{self.difficulty}: {self.score}%"
from django.db import models
from django.contrib.auth.models import User

class UserBadge(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    language = models.CharField(max_length=50)
    level = models.CharField(max_length=50)  # Beginner / Intermediate / Advanced / Legend
    awarded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "language", "level")  # prevents duplicates

    def __str__(self):
        return f"{self.user.username} - {self.language} ({self.level})"
    # users/models.py (only changed/added parts shown)
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone

# ... your existing constants LANG_ORDER, LEVELS, etc.

class UserPath(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="path")
    current_language = models.CharField(max_length=32, default=default_lang)
    current_level = models.CharField(max_length=16, default=default_level)
    badge_languages = models.JSONField(default=list, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    legend_badges = models.IntegerField(default=0)

    tests_taken_today = models.IntegerField(default=0)
    last_test_date = models.DateField(null=True, blank=True)

    # NEW: block user from taking tests until this timestamp
    locked_until = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.user.username} → {self.current_language} / {self.current_level}"

    def is_locked(self):
        if not self.locked_until:
            return False
        return self.locked_until > timezone.now()