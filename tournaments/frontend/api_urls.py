from django.urls import path
from billing.admin_checkout import admin_checkouts
from billing.catalog import admin_catalog
from billing.tranzila_setup import admin_readiness
from billing.tranzila_flow import checkout_session, reconcile
from billing import operations as payment_operations
from . import api
from . import accounts
from . import google_auth
from . import push
from .operations import health
from .admin_matches import admin_match

urlpatterns = [
    path('auth/google/config', google_auth.config, name='api-google-config'),
    path('auth/google', google_auth.authenticate, name='api-google-auth'),
    path('auth/google/complete', google_auth.complete, name='api-google-complete'),
    path('push/config', push.config, name='api-push-config'),
    path('push/subscription', push.subscription, name='api-push-subscription'),
    path('health/', health, name='api-health'),
    path('csrf/', api.api_csrf, name='api-csrf'),
    path('client/log', api.api_client_log, name='api-client-log'),
    path('auth/me', api.api_me, name='api-me'),
    path('auth/profile', api.api_profile, name='api-profile'),
    path('auth/login', api.api_login, name='api-login'),
    path('auth/logout', api.api_logout, name='api-logout'),
    path('auth/signup', accounts.signup, name='api-signup'),
    path('auth/verify/request', accounts.request_link, {'purpose': 'verify'}, name='api-verify-request'),
    path('auth/verify/confirm', accounts.confirm_link, {'purpose': 'verify'}, name='api-verify-confirm'),
    path('auth/reset/request', accounts.request_link, {'purpose': 'reset'}, name='api-reset-request'),
    path('auth/reset/confirm', accounts.confirm_link, {'purpose': 'reset'}, name='api-reset-confirm'),
    path('tournaments', api.api_tournaments, name='api-tournaments'),
    path('tournaments/<int:pk>', api.api_tournament_detail,
         name='api-tournament-detail'),
    path('tournaments/<int:pk>/join', api.api_join, name='api-join'),
    path('tournaments/<int:pk>/withdraw',
         api.api_withdraw, name='api-withdraw'),
    path('head-to-head/tables', api.api_head_to_head_tables, name='api-head-to-head-tables'),
    path('head-to-head/quick-match', api.api_head_to_head_quick_match, name='api-head-to-head-quick-match'),
    path('head-to-head/tables/<str:code>', api.api_head_to_head_table, name='api-head-to-head-table'),
    path('head-to-head/tables/<str:code>/join', api.api_head_to_head_join, name='api-head-to-head-join'),
    path('head-to-head/tables/<str:code>/cancel', api.api_head_to_head_cancel, name='api-head-to-head-cancel'),
    path('wallet/recurring-bonus', api.api_recurring_coin_bonus, name='api-recurring-coin-bonus'),
    # Admin (staff only)
    path('admin/tournaments/<int:pk>/matches/<int:fixture_id>', admin_match, name='api-admin-match'),
    path('admin/dashboard', api.api_admin_dashboard, name='api-admin-dashboard'),
    path('admin/direct-play/settings', api.api_admin_direct_play_settings, name='api-admin-direct-play-settings'),
    path('admin/direct-play/tables', api.api_admin_head_to_head_tables, name='api-admin-head-to-head-tables'),
    path('admin/direct-play/tables/<int:pk>/cancel', api.api_admin_head_to_head_cancel, name='api-admin-head-to-head-cancel'),
    path('admin/notifications', api.api_admin_notifications, name='api-admin-notifications'),
    path('admin/finance', api.api_admin_finance, name='api-admin-finance'),
    path('admin/checkouts', admin_checkouts, name='api-admin-checkouts'),
    path('admin/store-catalog', admin_catalog, name='api-admin-store-catalog'),
    path('admin/tranzila-readiness', admin_readiness, name='api-admin-tranzila-readiness'),
    path('admin/checkouts/<uuid:identifier>/session', checkout_session, name='api-admin-tranzila-session'),
    path('admin/checkouts/<uuid:identifier>/reconcile', reconcile, name='api-admin-tranzila-reconcile'),
    path('admin/tranzila-operations', payment_operations.operations_status, name='api-admin-tranzila-operations'),
    path('admin/tranzila-health', payment_operations.health_check, name='api-admin-tranzila-health'),
    path('admin/tranzila-issues/<int:identifier>/resolve', payment_operations.resolve_issue, name='api-admin-tranzila-resolve'),
    path('admin/checkouts/<uuid:identifier>/refunds', payment_operations.record_refund, name='api-admin-tranzila-refund'),
    path('admin/checkouts/<uuid:identifier>/refunds/<int:refund_id>/adjustment', payment_operations.complete_adjustment, name='api-admin-tranzila-adjustment'),
    path('admin/store-catalog/<int:pk>', admin_catalog, name='api-admin-store-product'),
    path('admin/tournaments', api.api_admin_tournaments, name='api-admin-tournaments'),
    path('admin/tournaments/<int:pk>', api.api_admin_tournament_detail, name='api-admin-tournament-detail'),
    path('admin/tournaments/<int:pk>/publish', api.api_admin_tournament_publish, name='api-admin-tournament-publish'),
    path('admin/tournaments/<int:pk>/draft', api.api_admin_tournament_draft, name='api-admin-tournament-draft'),
    path('admin/tournaments/<int:pk>/registration/close', api.api_admin_tournament_close_registration, name='api-admin-tournament-close-registration'),
    path('admin/tournaments/<int:pk>/registration/reopen', api.api_admin_tournament_reopen_registration, name='api-admin-tournament-reopen-registration'),
    path('admin/tournaments/<int:pk>/draw', api.api_admin_tournament_draw, name='api-admin-tournament-draw'),
    path('admin/tournaments/<int:pk>/draw/confirm', api.api_admin_tournament_confirm_draw, name='api-admin-tournament-confirm-draw'),
    path('admin/tournaments/<int:pk>/start', api.api_admin_tournament_start, name='api-admin-tournament-start'),
    path('admin/tournaments/<int:pk>/progress', api.api_admin_tournament_progress, name='api-admin-tournament-progress'),
    path('admin/tournaments/<int:pk>/attendees', api.api_admin_tournament_attendees, name='api-admin-tournament-attendees'),
    path('admin/wallet-transactions', api.api_admin_wallet_transactions, name='api-admin-wallet-transactions'),
    path('admin/users', api.api_admin_users, name='api-admin-users'),
    path('admin/transfers', api.api_admin_transfers, name='api-admin-transfers'),
    path('admin/users/<int:pk>', api.api_admin_user_detail, name='api-admin-user-detail'),
    path('admin/users/<int:pk>/wallet', api.api_admin_user_wallet, name='api-admin-user-wallet'),
    
]
