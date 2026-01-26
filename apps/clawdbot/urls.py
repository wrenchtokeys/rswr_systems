from django.urls import path
from . import views

app_name = 'clawdbot'

urlpatterns = [
    path('', views.status, name='status'),
    path('health/', views.health, name='health'),
]
