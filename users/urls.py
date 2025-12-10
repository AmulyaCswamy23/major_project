from django.urls import path
from . import views

urlpatterns = [
    path('', views.home_view, name='home'), 
    path('signup/', views.signup_view, name='signup'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('dashboard/', views.dashboard_view, name='dashboard'),
    path("home/", views.home_view, name="home"),
    path('take-test/', views.take_test, name='take_test'),
    path('api/user/', views.get_user_info),
    path('api/questions/', views.api_questions),
    path("api/hint/", views.hint_api, name="hint_api"),
    path('api/submit_test/', views.submit_test_api),
    path('start-test-page/', views.start_test_page, name="start_test_page"),
    path("test-result/", views.test_result_page, name="test_result_page"),
    path("roadmap/", views.roadmap_form, name="roadmap_form"),
    path("roadmap/generate/", views.roadmap_generate, name="roadmap_generate"),
    path("roadmap/pdf/", views.roadmap_pdf, name="roadmap_pdf"),
    path("choose-language/", views.choose_preferred_language_page, name="choose_preferred_language"),
    path("choose-next-language/", views.choose_next_language, name="choose_next_language"),
]