from django.urls import path
from . import views

app_name = 'accounts'

urlpatterns = [
    # Staff Management (MD only)
    path('', views.staff_list, name='staff_list'),
    path('register/', views.staff_register, name='staff_register'),
    path('<int:pk>/edit/', views.staff_edit, name='staff_edit'),
    path('<int:pk>/reset-password/', views.staff_reset_password, name='staff_reset_password'),
    path('<int:pk>/action/', views.staff_action, name='staff_action'),
    
    # MD Impersonation
    path('<int:target_id>/impersonate/', views.md_impersonate, name='md_impersonate'),
    path('stop-impersonating/', views.md_stop_impersonating, name='md_stop_impersonating'),
]
