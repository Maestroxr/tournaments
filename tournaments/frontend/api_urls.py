from django.urls import path
from . import api

urlpatterns = [
    path('csrf/', api.api_csrf, name='api-csrf'),
    path('auth/me', api.api_me, name='api-me'),
    path('auth/login', api.api_login, name='api-login'),
    path('auth/logout', api.api_logout, name='api-logout'),
    path('auth/signup', api.api_signup, name='api-signup'),
    path('tournaments', api.api_tournaments, name='api-tournaments'),
    path('tournaments/<int:pk>', api.api_tournament_detail,
         name='api-tournament-detail'),
    path('tournaments/<int:pk>/join', api.api_join, name='api-join'),
    path('tournaments/<int:pk>/withdraw',
         api.api_withdraw, name='api-withdraw'),
    # Admin (staff only)
    path('admin/tournaments', api.api_admin_tournaments, name='api-admin-tournaments'),
    path('admin/tournaments/<int:pk>', api.api_admin_tournament_detail, name='api-admin-tournament-detail'),
    path('admin/users', api.api_admin_users, name='api-admin-users'),
    path('admin/users/<int:pk>', api.api_admin_user_detail, name='api-admin-user-detail'),
]
