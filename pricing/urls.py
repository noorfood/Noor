from django.urls import path
from pricing import views

app_name = 'pricing'

urlpatterns = [
    # Price config
    path('list/', views.list_prices, name='list'),
    path('new/', views.new_price, name='new'),
    # Commission config
    path('commissions/', views.list_commissions, name='commissions'),
    path('commissions/new/', views.new_commission, name='new_commission'),
    # Sales targets
    path('targets/', views.list_targets, name='targets'),
    path('targets/new/', views.new_target, name='new_target'),
    # Operational expenses
    path('expenses/', views.list_expenses, name='expenses'),
    path('expenses/new/', views.new_expense, name='new_expense'),
]
