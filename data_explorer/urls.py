from django.urls import path
from data_explorer import views

app_name = 'data_explorer'

urlpatterns = [
    path('', views.explorer_home, name='home'),
    path('clear-database/', views.clear_database, name='clear_database'),
    path('<str:model_name>/', views.explore_model, name='model'),
    path('<str:model_name>/<int:pk>/edit/', views.explore_edit, name='edit'),
    path('<str:model_name>/<int:pk>/delete/', views.explore_delete, name='delete'),
    path('<str:model_name>/bulk-delete/', views.explore_bulk_delete, name='bulk_delete'),
]
