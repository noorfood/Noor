from django.urls import path
from reports import views

app_name = 'reports'

urlpatterns = [
    path('dashboard/', views.dashboard, name='dashboard'),
    path('md-insights/', views.md_insights, name='md_insights'),
    path('production/', views.production_report, name='production'),
    path('store/', views.store_report, name='store'),
    path('sales/', views.sales_report, name='sales'),
    path('outstanding/', views.outstanding_report, name='outstanding'),
    path('flow/', views.company_flow, name='flow'),
]

