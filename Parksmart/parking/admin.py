from django.contrib import admin
from .models import Parking, UserProfile, Booking, Payment, PaymentTransaction

# ===================== BOOKING ADMIN ===================== #
class BookingAdmin(admin.ModelAdmin):
    list_display = ('booking_code', 'user', 'parking', 'vehicle_type', 'vehicle_number', 'total_price', 'booking_time', 'end_time')
    list_filter = ('vehicle_type', 'booking_time', 'parking')
    search_fields = ('booking_code', 'user__username', 'vehicle_number')
    readonly_fields = ('booking_code', 'booking_time', 'end_time', 'total_price')
    fieldsets = (
        ('Booking Code & Time', {
            'fields': ('booking_code', 'booking_time', 'end_time')
        }),
        ('User & Parking', {
            'fields': ('user', 'parking')
        }),
        ('Vehicle Details', {
            'fields': ('vehicle_type', 'vehicle_number')
        }),
        ('Pricing', {
            'fields': ('hours', 'total_price')
        }),
    )

# ===================== PAYMENT ADMIN ===================== #
class PaymentTransactionInline(admin.TabularInline):
    model = PaymentTransaction
    readonly_fields = ('transaction_id', 'created_at')
    can_delete = False
    extra = 0

class PaymentAdmin(admin.ModelAdmin):
    list_display = ('booking__booking_code', 'total_amount', 'deposit_amount', 'balance_amount', 'status', 'payment_date')
    list_filter = ('status', 'payment_method', 'payment_date')
    search_fields = ('booking__booking_code', 'transaction_id')
    readonly_fields = ('transaction_id', 'payment_date', 'balance_paid_date')
    inlines = [PaymentTransactionInline]

    fieldsets = (
        ('Payment Details', {
            'fields': ('booking', 'total_amount', 'deposit_amount', 'balance_amount', 'status')
        }),
        ('Payment Info', {
            'fields': ('payment_method', 'transaction_id', 'payment_date', 'balance_paid_date')
        }),
    )

class PaymentTransactionAdmin(admin.ModelAdmin):
    list_display = ('payment__booking__booking_code', 'amount', 'transaction_type', 'status', 'payment_method', 'created_at')
    list_filter = ('transaction_type', 'status', 'payment_method', 'created_at')
    search_fields = ('transaction_id', 'payment__booking__booking_code')
    readonly_fields = ('transaction_id', 'created_at')

admin.site.register(Booking, BookingAdmin)
admin.site.register(Payment, PaymentAdmin)
admin.site.register(PaymentTransaction, PaymentTransactionAdmin)
admin.site.register(Parking)
admin.site.register(UserProfile)