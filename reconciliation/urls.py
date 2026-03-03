from django.urls import path
from reconciliation import views

app_name = 'reconciliation'

urlpatterns = [
    path('dashboard/', views.dashboard, name='dashboard'),
    path('money/record/', views.record_money, name='record_money'),
    path('list/', views.list_view, name='list'),
    path('flags/', views.flags_view, name='flags'),
]
