from django.urls import path
from procurement import views

app_name = 'procurement'

urlpatterns = [
    path('dashboard/', views.dashboard, name='dashboard'),
    path('receive/', views.receive_raw, name='receive'),
    path('issue/', views.issue_raw, name='issue'),
    path('list/', views.list_records, name='list'),
    path('receipt/<int:receipt_id>/set-cost/', views.set_receipt_cost, name='set_cost'),
    path('cleaning-loss-config/', views.cleaning_loss_config, name='cleaning_loss'),
]
