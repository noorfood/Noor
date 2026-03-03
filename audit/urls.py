from django.urls import path
from audit import views

app_name = 'audit'

urlpatterns = [
    path('log/', views.audit_log_view, name='log'),
]
