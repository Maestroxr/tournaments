from django.urls import path
from . import views
from . import tranzila_flow
from . import player_checkout

urlpatterns = [
    path('catalog', player_checkout.catalog, name='billing-catalog'),
    path('tranzila/orders', player_checkout.orders, name='tranzila-orders'),
    path('tranzila/orders/<uuid:identifier>/cancel', player_checkout.cancel_draft, name='tranzila-cancel-draft'),
    path('tranzila/notify', tranzila_flow.notify, name='tranzila-notify'),
    path('tranzila/orders/<uuid:identifier>', tranzila_flow.order_status, name='tranzila-order-status'),
    path('tranzila/orders/<uuid:identifier>/session', tranzila_flow.checkout_session, name='tranzila-session'),
    path('status', views.status, name='billing-status'),
    path('plan', views.retired, name='billing-plan'),
    path('checkout', views.retired, name='billing-checkout'),
    path('subscriptions/<uuid:identifier>/cancel', views.retired, name='billing-cancel'),
    path('payments/<int:payment_id>/refund', views.retired, name='billing-refund'),
    path('receipts/<uuid:identifier>', views.receipt, name='billing-receipt'),
    path('webhook', views.retired, name='billing-webhook'),
]
