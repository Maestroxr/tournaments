from django.urls import path
from . import views

urlpatterns = [
    path('status', views.status, name='billing-status'),
    path('plan', views.plan, name='billing-plan'),
    path('checkout', views.checkout, name='billing-checkout'),
    path('subscriptions/<uuid:identifier>/cancel', views.cancel, name='billing-cancel'),
    path('payments/<int:payment_id>/refund', views.refund, name='billing-refund'),
    path('receipts/<uuid:identifier>', views.receipt, name='billing-receipt'),
    path('webhook', views.webhook, name='billing-webhook'),
]
