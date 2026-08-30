"""
URL patterns of the game link.

These carry their full path, so this module is included at the project root rather than under a
prefix. Session 6 of the plan adds ``api/gamelink/result/`` here.
"""
from django.urls import path

from . import views

urlpatterns = [
    path('t/fixture/<int:pk>/play', views.StartGameView.as_view(), name='gamelink-start'),
]
