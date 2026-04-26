from django.contrib import admin
from .models import (
    Parking, UserProfile, Booking, ParkingImage,
    FavoriteParking, RecurringBooking, Payment,
    PaymentTransaction, Receipt
)


# ===================== PARKING ADMIN ===================== #
class ParkingImageInline(admin.TabularInline):
    model = ParkingImage
    extra = 1

class ParkingAdmin(admin.ModelAdmin):
    list_display = ('parking_name', 'location', 'provider', 'bike_slots', 'car_slots')
    list_filter = ('provider',)
    search_fields = ('parking_name', 'location')
    inlines = [ParkingImageInline]


# ===================== BOOKING ADMIN ===================== #
class BookingAdmin(admin.ModelAdmin):
    list_display = ('booking_code', 'user', 'parking', 'vehicle_type', 'vehicle_number',
                     'status', 'total_price', 'start_time', 'end_time', 'is_checked_out')
    list_filter = ('vehicle_type', 'status', 'is_checked_out', 'booking_time', 'parking')
    search_fields = ('booking_code', 'user__username', 'vehicle_number')
    readonly_fields = ('booking_code', 'booking_time')
    fieldsets = (
        ('Booking Code & Time', {
            'fields': ('booking_code', 'booking_time', 'start_time', 'end_time')
        }),
        ('User & Parking', {
            'fields': ('user', 'parking')
        }),
        ('Vehicle Details', {
            'fields': ('vehicle_type', 'vehicle_number')
        }),
        ('Pricing', {
            'fields': ('hours', 'total_price', 'overstay_penalty')
        }),
        ('Status', {
            'fields': ('status', 'is_active', 'is_checked_out', 'actual_exit_time')
        }),
    )


# ===================== PAYMENT ADMIN ===================== #
class PaymentTransactionInline(admin.TabularInline):
    model = PaymentTransaction
    readonly_fields = ('transaction_id', 'created_at')
    can_delete = False
    extra = 0


class PaymentAdmin(admin.ModelAdmin):
    list_display = ('get_booking_code', 'total_amount', 'deposit_amount',
                     'balance_amount', 'status', 'payment_date')
    list_filter = ('status', 'payment_method', 'payment_date')
    search_fields = ('booking__booking_code', 'transaction_id')
    readonly_fields = ('transaction_id', 'payment_date', 'balance_paid_date',
                        'razorpay_order_id', 'razorpay_payment_id', 'razorpay_signature')
    inlines = [PaymentTransactionInline]

    # ✅ Fixed: Use method instead of __ notation for list_display
    def get_booking_code(self, obj):
        return obj.booking.booking_code
    get_booking_code.short_description = 'Booking Code'

    fieldsets = (
        ('Payment Details', {
            'fields': ('booking', 'total_amount', 'deposit_amount', 'balance_amount', 'status')
        }),
        ('Payment Info', {
            'fields': ('payment_method', 'transaction_id', 'payment_date', 'balance_paid_date')
        }),
        ('Razorpay Gateway', {
            'fields': ('razorpay_order_id', 'razorpay_payment_id', 'razorpay_signature'),
            'classes': ('collapse',),
        }),
    )


class PaymentTransactionAdmin(admin.ModelAdmin):
    list_display = ('get_booking_code', 'amount', 'transaction_type',
                     'status', 'payment_method', 'created_at')
    list_filter = ('transaction_type', 'status', 'payment_method', 'created_at')
    search_fields = ('transaction_id', 'payment__booking__booking_code')
    readonly_fields = ('transaction_id', 'created_at')

    def get_booking_code(self, obj):
        return obj.payment.booking.booking_code
    get_booking_code.short_description = 'Booking Code'


# ===================== RECEIPT ADMIN ===================== #
class ReceiptAdmin(admin.ModelAdmin):
    list_display = ('receipt_number', 'get_user', 'total_amount', 'payment_status', 'generated_at')
    search_fields = ('receipt_number', 'transaction_id')

    def get_user(self, obj):
        return obj.booking.user.username
    get_user.short_description = 'User'


# ===================== REGISTER ALL ===================== #
admin.site.register(Parking, ParkingAdmin)
admin.site.register(UserProfile)
admin.site.register(Booking, BookingAdmin)
admin.site.register(ParkingImage)
admin.site.register(FavoriteParking)
admin.site.register(RecurringBooking)
admin.site.register(Payment, PaymentAdmin)
admin.site.register(PaymentTransaction, PaymentTransactionAdmin)
admin.site.register(Receipt, ReceiptAdmin)