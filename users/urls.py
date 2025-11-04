from django.urls import path
from . import views

urlpatterns = [
    path('signup/', views.signup_view, name='signup'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('dashboard/', views.dashboard_view, name='dashboard'),
    path('take-test/', views.take_test, name='take_test'),
    
    path("api/user/", views.get_user_info, name="get_user_info"),
    path('generate/', views.generate_questions, name='generate_questions'),
    path('take-test/', views.take_test, name="take_test"),
    path('api/questions/', views.generate_questions),
    path('api/hint', views.hint_api),
    path('api/submit', views.submit_test_api),
    path('api/user', views.get_user_info),
    path("api/questions/", views.api_questions, name="api_questions"),
]