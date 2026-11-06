from django.urls import path
from . import views
app_name='commerce'
urlpatterns=[path('',views.home,name='home'),path('record/',views.create_sale,name='create'),path('money/',views.money_home,name='money_home'),path('money/send/',views.money_send,name='money_send'),path('money/corrections/',views.corrections_home,name='corrections_home'),path('money/correction/<int:pk>/',views.correction_detail,name='correction_detail'),path('money/<int:pk>/correct/<str:kind>/<int:target_id>/',views.correction_request,name='correction_request'),path('money/<int:pk>/',views.money_detail,name='money_detail'),path('<int:pk>/',views.detail,name='detail')]
