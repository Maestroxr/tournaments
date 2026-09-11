from django.urls import path
from . import views
from . import tranzila_flow

urlpatterns = [
    path('tranzila/notify', tranzila_flow.notify, name='tranzila-notify'),
    path('tranzila/orders/<uuid:identifier>', tranzila_flow.order_status, name='tranzila-order-status'),
    path('tranzila/orders/<uuid:identifier>/session', tranzila_flow.checkout_session, name='tranzila-session'),
    path('status', views.status, name='billing-status'),
    path('plan', views.plan, name='billing-plan'),
    path('checkout', views.checkout, name='billing-checkout'),
    path('subscriptions/<uuid:identifier>/cancel', views.cancel, name='billing-cancel'),
    path('payments/<int:payment_id>/refund', views.refund, name='billing-refund'),
    path('receipts/<uuid:identifier>', views.receipt, name='billing-receipt'),
    path('webhook', views.webhook, name='billing-webhook'),
]
