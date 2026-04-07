from django.urls import path
from finished_store import views

app_name = 'finished_store'

urlpatterns = [
    path('dashboard/', views.dashboard, name='dashboard'),
    path('receipt/<int:receipt_id>/acknowledge/', views.acknowledge_receipt, name='acknowledge_receipt'),
    path('issue/', views.issue_fg, name='issue'),
    path('collect-for-sm/', views.create_sm_collection, name='collect_for_sm'),
    path('issuance/<int:issuance_id>/acknowledge/', views.acknowledge_issuance, name='acknowledge_issuance'),
    path('return/<int:return_id>/acknowledge/', views.acknowledge_return, name='acknowledge_return'),
    path('list/', views.list_records, name='list'),
]

