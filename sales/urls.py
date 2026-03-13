from django.urls import path
from sales import views

app_name = 'sales'

urlpatterns = [
    # ── Dashboard ──────────────────────────────────────────────────────────
    path('dashboard/', views.dashboard, name='dashboard'),

    # ── SalesPerson management ─────────────────────────────────────────────
    path('salespersons/', views.list_salespersons, name='salespersons'),
    path('salespersons/add/', views.add_salesperson, name='add_salesperson'),

    # ── SM Collections (FG Store → Sales Manager) ──────────────────────────
    path('collections/', views.list_sm_collections, name='list_collections'),
    path('collections/<int:collection_id>/acknowledge/', views.acknowledge_collection, name='acknowledge_collection'),

    # ── SP Distribution & Performance Tracking (no financial impact) ────────
    path('distribution/new/', views.record_distribution, name='record_distribution'),
    path('sales-result/new/', views.record_sales_result, name='record_sales_result'),
    path('sp-performance/', views.sp_performance, name='sp_performance'),
    path('salespersons/<int:sp_id>/history/', views.sp_detail, name='sp_detail'),

    # ── SM Payments (SM sends money → GM confirms) ─────────────────────────
    path('sm-payment/new/', views.record_sm_payment, name='record_sm_payment'),
    path('sm-payment/<int:payment_id>/confirm/', views.confirm_sm_payment, name='confirm_sm_payment'),
    path('sm-payments/', views.list_sm_payments, name='list_sm_payments'),

    # ── Outstanding balances (SM level) ────────────────────────────────────
    path('outstanding/', views.outstanding_view, name='outstanding'),

    # ── Company Direct Sales & Brand (GM only — separate flow) ────────────
    path('company-sale/new/', views.record_company_sale, name='record_company_sale'),
    path('bran-sale/new/', views.record_bran_sale, name='record_bran_sale'),
    
    # ── GM Factory-Gate Direct Sales & MD Confirmation ─────────────────────
    path('direct-sale/new/', views.record_direct_sale, name='record_direct_sale'),
    path('direct-sales/', views.list_direct_sales, name='list_direct_sales'),
    path('direct-sale/<int:pk>/confirm/', views.md_confirm_direct_sale, name='md_confirm_direct_sale'),

    # ── Legacy routes (historical SalesRecord / SalesPayment viewing) ──────
    path('list/', views.list_sales, name='list'),
    path('<int:sale_id>/receipt/', views.sale_receipt, name='receipt'),
    path('<int:sale_id>/payment/', views.record_payment, name='record_payment'),
]
