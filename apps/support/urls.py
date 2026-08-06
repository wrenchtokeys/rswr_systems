from django.urls import path

from . import views

urlpatterns = [
    path('', views.help_home, name='help_home'),
    path('contact/', views.contact, name='help_contact'),  # before <slug>
    path('<slug:slug>/feedback/', views.guide_feedback, name='guide_feedback'),
    path('<slug:slug>/', views.help_topic, name='help_topic'),
]
