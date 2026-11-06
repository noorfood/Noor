from django.urls import path
from data_explorer import views
from django.http import HttpResponseForbidden

def disabled_action(request, *args, **kwargs):
    return HttpResponseForbidden("Destructive actions are unavailable.")

app_name = 'data_explorer'

urlpatterns = [
    path('', views.explorer_home, name='home'),
    path('clear-database/', disabled_action, name='clear_database'),
    path('<str:model_name>/', views.explore_model, name='model'),
    path('<str:model_name>/<int:pk>/edit/', disabled_action, name='edit'),
    path('<str:model_name>/<int:pk>/delete/', disabled_action, name='delete'),
    path('<str:model_name>/bulk-delete/', disabled_action, name='bulk_delete'),
]
