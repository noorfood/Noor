from django.urls import path
from reports import views

app_name = 'reports'

urlpatterns = [
    path('dashboard/', views.dashboard, name='dashboard'),
    path('md-insights/', views.md_insights, name='md_insights'),
    path('production/', views.production_report, name='production'),
    path('store/', views.store_report, name='store'),
    path('sales/', views.sales_report, name='sales'),
    path('bran-sales/', views.bran_sales_report, name='bran_sales'),
    path('outstanding/', views.outstanding_report, name='outstanding'),
    path('flow/', views.company_flow, name='flow'),
    path('md-ledger/', views.md_ledger, name='ledger'),
    path('snapshot/record/', views.record_monthly_snapshot, name='record_monthly_snapshot'),
    path('', views.reports_index, name='index'),
    path('weekly/', views.weekly_summary, name='weekly_summary'),
    path('oversight/', views.oversight, name='oversight'),
    path('no-activity/', views.report_no_activity, name='no_activity'),
]

