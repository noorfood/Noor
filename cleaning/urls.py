from django.urls import path
from cleaning import views

app_name = 'cleaning'

urlpatterns = [
    path('dashboard/', views.dashboard, name='dashboard'),
    path('batch/new/', views.new_batch, name='new_batch'),
    path('list/', views.list_batches, name='list'),
    path('batch/<int:batch_id>/approve/', views.approve_batch, name='approve'),
]
