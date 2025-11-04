from django.db import models

# Create your models here.
from django.db import models
from django.contrib.auth.models import User

# Extending the default Django user with extra info
class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    preferred_language = models.CharField(max_length=50, default="python")
    total_tests_taken = models.IntegerField(default=0)
    average_score = models.FloatField(default=0.0)

    def __str__(self):
        return self.user.username


# Store results of each test
class TestResult(models.Model):
    DIFFICULTY_CHOICES = [
        ('basic', 'Basic'),
        ('intermediate', 'Intermediate'),
        ('legend', 'Legend'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    language = models.CharField(max_length=50)
    difficulty = models.CharField(max_length=20, choices=DIFFICULTY_CHOICES, default='basic')
    
    score = models.FloatField()
    hints_used = models.IntegerField(default=0)
    time_elapsed = models.IntegerField(default=0)  # in seconds
    date_taken = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} - {self.language} - {self.difficulty} - {self.score}"
