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
    # Packaging & Material Costs (Constant Expenses)
    path('packaging/', views.list_packaging_costs, name='packaging_costs'),
    path('packaging/new-global/', views.new_packaging_cost, name='new_packaging_cost'),
    path('packaging/new-cleaning/', views.new_cleaning_cost, name='new_cleaning_cost'),
    path('packaging/new-labour/', views.new_labour_cost, name='new_labour_cost'),
]
