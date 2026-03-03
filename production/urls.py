from django.urls import path
from production import views

app_name = 'production'

urlpatterns = [
    path('dashboard/', views.dashboard, name='dashboard'),
    path('milling/new/', views.record_milling, name='record_milling'),
    path('packaging/new/', views.record_packaging, name='record_packaging'),
    path('list/', views.list_batches, name='list'),
    path('outstanding/', views.outstanding_view, name='outstanding'),
    path('returns/new/', views.initiate_return, name='initiate_return'),
    path('thresholds/', views.manage_thresholds, name='thresholds'),
    path('transfer/<int:issuance_id>/acknowledge/', views.acknowledge_transfer, name='acknowledge_transfer'),
]
