from django.contrib import admin
from django.urls import path, include
from accounts import views as acc_views

urlpatterns = [
    path('', acc_views.login_view, name='login'),
    path('logout/', acc_views.logout_view, name='logout'),
    path('dashboard/', acc_views.dashboard_redirect, name='dashboard'),
    path('staff/', include('accounts.urls', namespace='accounts')),
    path('procurement/', include('procurement.urls', namespace='procurement')),
    path('cleaning/', include('cleaning.urls', namespace='cleaning')),
    path('clean-store/', include('clean_store.urls', namespace='clean_store')),
    path('production/', include('production.urls', namespace='production')),
    path('finished-store/', include('finished_store.urls', namespace='finished_store')),
    path('sales/', include('sales.urls', namespace='sales')),
    path('reconciliation/', include('reconciliation.urls', namespace='reconciliation')),
    path('pricing/', include('pricing.urls', namespace='pricing')),
    path('audit/', include('audit.urls', namespace='audit')),
    path('reports/', include('reports.urls', namespace='reports')),
    path('admin/', admin.site.urls),
    path('data-explorer/', include('data_explorer.urls', namespace='data_explorer')),
]
