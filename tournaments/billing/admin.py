from django.contrib import admin
from .models import Payment, Receipt, Refund, Subscription, WebhookEvent, CheckoutRequest, CheckoutEvent, StoreProduct, StoreProductAudit


class BillingAuditAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Subscription)
class SubscriptionAdmin(BillingAuditAdmin):
    list_display = ('id', 'user', 'status', 'provider_id', 'amount', 'currency', 'cancel_requested')
    list_filter = ('status',)


@admin.register(Payment)
class PaymentAdmin(BillingAuditAdmin):
    list_display = ('id', 'provider_id', 'subscription', 'amount', 'currency', 'period_end', 'refunded_amount', 'reversed')


admin.site.register((Receipt, Refund, WebhookEvent), BillingAuditAdmin)
admin.site.register((CheckoutRequest, CheckoutEvent), BillingAuditAdmin)
admin.site.register((StoreProduct, StoreProductAudit), BillingAuditAdmin)
