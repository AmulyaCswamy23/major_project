from django.contrib import admin
from django.urls import path, include
from users import views as user_views  # import your app’s views

urlpatterns = [
    path('admin/', admin.site.urls),

    # Redirect root URL "/" to login page (or dashboard if already logged in)
    path('', user_views.login_view, name='home'),

    # Users app routes
    path('', include('users.urls')),
]