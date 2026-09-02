from django.urls import path
from . import api

urlpatterns = [
    path('csrf/', api.api_csrf, name='api-csrf'),
    path('client/log', api.api_client_log, name='api-client-log'),
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
    path('admin/dashboard', api.api_admin_dashboard, name='api-admin-dashboard'),
    path('admin/tournaments', api.api_admin_tournaments, name='api-admin-tournaments'),
    path('admin/tournaments/<int:pk>', api.api_admin_tournament_detail, name='api-admin-tournament-detail'),
    path('admin/tournaments/<int:pk>/publish', api.api_admin_tournament_publish, name='api-admin-tournament-publish'),
    path('admin/tournaments/<int:pk>/draft', api.api_admin_tournament_draft, name='api-admin-tournament-draft'),
    path('admin/tournaments/<int:pk>/start', api.api_admin_tournament_start, name='api-admin-tournament-start'),
    path('admin/tournaments/<int:pk>/progress', api.api_admin_tournament_progress, name='api-admin-tournament-progress'),
    path('admin/tournaments/<int:pk>/attendees', api.api_admin_tournament_attendees, name='api-admin-tournament-attendees'),
    path('admin/wallet-transactions', api.api_admin_wallet_transactions, name='api-admin-wallet-transactions'),
    path('admin/users', api.api_admin_users, name='api-admin-users'),
    path('admin/transfers', api.api_admin_transfers, name='api-admin-transfers'),
    path('admin/users/<int:pk>', api.api_admin_user_detail, name='api-admin-user-detail'),
    path('admin/users/<int:pk>/wallet', api.api_admin_user_wallet, name='api-admin-user-wallet'),
    
]
