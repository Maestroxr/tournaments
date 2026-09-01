"""
URL patterns of the game link.

These carry their full path, so this module is included at the project root rather than under a
prefix — the two endpoints live in different parts of the URL space and neither of them belongs
under a shared one.
"""
from django.urls import path

from . import views

urlpatterns = [
    path('t/fixture/<int:pk>/play', views.StartGameView.as_view(), name='gamelink-start'),
    path('api/gamelink/result/', views.ResultCallbackView.as_view(), name='gamelink-result'),
    path('api/gamelink/live/', views.LiveSnapshotCallbackView.as_view(), name='gamelink-live'),
]
