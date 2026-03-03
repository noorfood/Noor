from django.urls import path
from clean_store import views

app_name = 'clean_store'

urlpatterns = [
    path('dashboard/', views.dashboard, name='dashboard'),
    path('receive/', views.receive_clean, name='receive'),
    path('issue/', views.issue_clean, name='issue'),
    path('return/<int:return_id>/acknowledge/', views.acknowledge_return, name='acknowledge_return'),
    path('list/', views.list_records, name='list'),
]
