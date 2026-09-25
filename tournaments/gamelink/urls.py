"""
URL patterns of the game link.

These carry their full path, so this module is included at the project root rather than under a
prefix — the two endpoints live in different parts of the URL space and neither of them belongs
under a shared one.
"""
from django.urls import path

from . import views
from .practice import ActivePracticeView, ResumePracticeView, StartPracticeView

urlpatterns = [
    path('api/practice/', StartPracticeView.as_view(), name='practice-api'),
    path('api/practice/active/', ActivePracticeView.as_view(), name='practice-active'),
    path('api/practice/<uuid:purchase_id>/resume/', ResumePracticeView.as_view(), name='practice-resume'),
    path('t/practice/play', StartPracticeView.as_view(), name='gamelink-practice'),
    path('t/fixture/<int:pk>/play', views.StartGameView.as_view(), name='gamelink-start'),
    path('t/tournament/<int:pk>/play', views.StartTournamentGameView.as_view(),
         name='gamelink-tournament-start'),
    path('t/head-to-head/<str:code>/play', views.StartDirectPlayView.as_view(),
         name='gamelink-direct-play-start'),
    path('api/gamelink/result/', views.ResultCallbackView.as_view(), name='gamelink-result'),
    path('api/gamelink/live/', views.LiveSnapshotCallbackView.as_view(), name='gamelink-live'),
    path('api/gamelink/rematch/', views.RematchCallbackView.as_view(), name='gamelink-rematch'),
]
