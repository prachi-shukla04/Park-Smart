from datetime import timedelta

from django.db import models
from django.contrib.auth.models import User
import re
from django.core.exceptions import ValidationError
import uuid
import string
import random

class Parking(models.Model):
    provider = models.ForeignKey(User, on_delete=models.CASCADE)
    parking_name = models.CharField(max_length=100)
    location = models.CharField(max_length=200)

    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)

    bike_slots = models.IntegerField(default=0)
    car_slots = models.IntegerField(default=0)
    suv_slots = models.IntegerField(default=0)
    truck_slots = models.IntegerField(default=0)

    available_bike_slots = models.IntegerField(default=0)
    available_car_slots = models.IntegerField(default=0)
    available_suv_slots = models.IntegerField(default=0)
    available_truck_slots = models.IntegerField(default=0)

    bike_price = models.FloatField(default=0)
    car_price = models.FloatField(default=0)
    suv_price = models.FloatField(default=0)
    truck_price = models.FloatField(default=0)

    qr_code_image = models.ImageField(upload_to='qr_codes/', null=True, blank=True)

    # Promotions
    bike_free_slots = models.IntegerField(default=0)
    car_free_slots = models.IntegerField(default=0)
    suv_free_slots = models.IntegerField(default=0)
    truck_free_slots = models.IntegerField(default=0)

    bike_first_free_limit = models.IntegerField(default=0)
    car_first_free_limit = models.IntegerField(default=0)
    suv_first_free_limit = models.IntegerField(default=0)
    truck_first_free_limit = models.IntegerField(default=0)

    # ✅ MOVE THESE INSIDE
    used_bike_free_today = models.IntegerField(default=0)
    used_car_free_today = models.IntegerField(default=0)
    used_suv_free_today = models.IntegerField(default=0)
    used_truck_free_today = models.IntegerField(default=0)

    used_bike_first_free_today = models.IntegerField(default=0)
    used_car_first_free_today = models.IntegerField(default=0)
    used_suv_first_free_today = models.IntegerField(default=0)
    used_truck_first_free_today = models.IntegerField(default=0)

    last_reset_date = models.DateField(null=True, blank=True)

    def get_price(self, vehicle_type):
        prices = {
            "Bike": self.bike_price,
            "Car": self.car_price,
            "SUV": self.suv_price,
            "Truck": self.truck_price
        }
        return prices.get(vehicle_type, 0)

    def reset_daily_counters(self):
        from django.utils import timezone
        today = timezone.now().date()

        if self.last_reset_date != today:
            self.used_bike_first_free_today = 0
            self.used_car_first_free_today = 0
            self.used_suv_first_free_today = 0
            self.used_truck_first_free_today = 0

            self.last_reset_date = today
            self.save()
   # ===================== VEHICLE-WISE PROMOTIONS ===================== #

    # Free slots per vehicle
    bike_free_slots = models.IntegerField(default=0)
    car_free_slots = models.IntegerField(default=0)
    suv_free_slots = models.IntegerField(default=0)
    truck_free_slots = models.IntegerField(default=0)

    # First free bookings per vehicle
    bike_first_free_limit = models.IntegerField(default=0)
    car_first_free_limit = models.IntegerField(default=0)
    suv_first_free_limit = models.IntegerField(default=0)
    truck_first_free_limit = models.IntegerField(default=0)

   
# ===================== TRACKING ===================== #

used_bike_free_today = models.IntegerField(default=0)
used_car_free_today = models.IntegerField(default=0)
used_suv_free_today = models.IntegerField(default=0)
used_truck_free_today = models.IntegerField(default=0)

used_bike_first_free_today = models.IntegerField(default=0)
used_car_first_free_today = models.IntegerField(default=0)
used_suv_first_free_today = models.IntegerField(default=0)
used_truck_first_free_today = models.IntegerField(default=0)
last_reset_date = models.DateField(null=True, blank=True)

def reset_daily_counters(self):
    from django.utils import timezone
    today = timezone.now().date()

    if self.last_reset_date != today:
        self.used_bike_first_free_today = 0
        self.used_car_first_free_today = 0
        self.used_suv_first_free_today = 0
        self.used_truck_first_free_today = 0

        self.last_reset_date = today
        self.save()

    if not hasattr(self, 'last_reset_date') or self.last_reset_date != today:
        self.used_bike_first_free_today = 0
        self.used_car_first_free_today = 0
        self.used_suv_first_free_today = 0
        self.used_truck_first_free_today = 0

        self.last_reset_date = today
        self.save()
class UserProfile(models.Model):
    ROLE_CHOICES = (
        ('user', 'Parking User'),
        ('provider', 'Parking Provider'),
    )

    user = models.OneToOneField(User, on_delete=models.CASCADE)
    phone = models.CharField(max_length=15, null=True, blank=True)
    address = models.TextField(null=True, blank=True)
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default='user')

    def __str__(self):
        return self.user.username


# ===================== BOOKING MODEL ===================== #
VEHICLE_CHOICES = [
    ('Bike', 'Bike'),
    ('Car', 'Car'),
    ('SUV', 'SUV'),
    ('Truck', 'Truck'),
]

PAYMENT_TIMING_CHOICES = [
    ('pay_now', 'Pay Now'),
    ('pay_at_end', 'Pay at End'),
]


# ===================== HELPER FUNCTION FOR UNIQUE CODE ===================== #
def generate_unique_booking_code():
    """Generate a unique booking code in format: PK-ABC123XYZ456"""
    characters = string.ascii_uppercase + string.digits
    random_code = ''.join(random.choices(characters, k=12))
    return f"PK-{random_code}"


class Booking(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    parking = models.ForeignKey(Parking, on_delete=models.CASCADE)

    vehicle_type = models.CharField(max_length=20, choices=VEHICLE_CHOICES)
    vehicle_number = models.CharField(max_length=20)

    # ✅ Unique booking code
    booking_code = models.CharField(max_length=20, unique=True, editable=False)

    hours = models.IntegerField(default=1)
    total_price = models.FloatField(blank=True, null=True)

    booking_time = models.DateTimeField(auto_now_add=True)
    end_time = models.DateTimeField(blank=True, null=True)

    # Payment timing choice
    payment_timing = models.CharField(max_length=15, choices=PAYMENT_TIMING_CHOICES, default='pay_now')

    # ✅ Soft delete field
    is_active = models.BooleanField(default=True)

    def clean(self):
        if not re.match(r'^[A-Z]{2}[0-9]{2}[A-Z]{2}[0-9]{4}$', self.vehicle_number):
            raise ValidationError("Enter valid vehicle number (e.g. UP32AB1234)")


    def save(self, *args, **kwargs):
        PRICE_PER_HOUR = {
            'Bike': 20,
            'Car': 50,
            'SUV': 70,
            'Truck': 100
        }

        # Generate unique booking code if not already set
        if not self.booking_code:
            self.booking_code = generate_unique_booking_code()

        # Set total_price only if not already set (for promotions)
        if self.total_price is None:
            price = PRICE_PER_HOUR.get(self.vehicle_type, 50)
            self.total_price = price * self.hours

        if self.booking_time:
            self.end_time = self.booking_time + timedelta(hours=self.hours)

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.user.username} - {self.parking.parking_name}"
    
# ===================== PARKING IMAGES ===================== #
class ParkingImage(models.Model):
    parking = models.ForeignKey(Parking, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(upload_to='parking_gallery/')


class FavoriteParking(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    parking = models.ForeignKey(Parking, on_delete=models.CASCADE)
    added_date = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'parking')

    def __str__(self):
        return f"{self.user.username} - {self.parking.parking_name}"


# ===================== RECURRING BOOKING ===================== #
class RecurringBooking(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    parking = models.ForeignKey(Parking, on_delete=models.CASCADE)
    vehicle_type = models.CharField(max_length=20, choices=VEHICLE_CHOICES)
    vehicle_number = models.CharField(max_length=20)
    hours = models.IntegerField(default=1)
    start_date = models.DateField()
    end_date = models.DateField()
    days_of_week = models.JSONField(default=list, help_text="List of days: ['monday', 'tuesday', etc.]")
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"Recurring: {self.user.username} - {self.parking.parking_name}"


# ===================== PAYMENT SYSTEM ===================== #
PAYMENT_STATUS_CHOICES = [
    ('pending', 'Pending'),
    ('completed', 'Completed'),
    ('failed', 'Failed'),
]

PAYMENT_METHOD_CHOICES = [
    ('qr_code', 'QR Code Payment'),
]

class Payment(models.Model):
    booking = models.OneToOneField(Booking, on_delete=models.CASCADE, related_name='payment')
    total_amount = models.FloatField()  # Total booking cost
    deposit_amount = models.FloatField(default=0)  # Deposit paid (20-30% of total)
    balance_amount = models.FloatField(default=0)  # Remaining amount to pay
    status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default='pending')
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES, blank=True)
    transaction_id = models.CharField(max_length=50, unique=True, blank=True)
    payment_date = models.DateTimeField(auto_now_add=True)
    balance_paid_date = models.DateTimeField(null=True, blank=True)

    def save(self, *args, **kwargs):
        # Auto-calculate deposit (25% of total, minimum ₹50)
        if not self.deposit_amount:
            self.deposit_amount = max(50, self.total_amount * 0.25)

        # Calculate balance
        self.balance_amount = self.total_amount - self.deposit_amount

        # Generate transaction ID if not set
        if not self.transaction_id:
            self.transaction_id = f"TXN-{uuid.uuid4().hex[:12].upper()}"

        super().save(*args, **kwargs)

    def is_fully_paid(self):
        return self.status == 'completed'

    def get_deposit_percentage(self):
        if self.total_amount > 0:
            return (self.deposit_amount / self.total_amount) * 100
        return 0

    def __str__(self):
        return f"Payment for {self.booking.booking_code} - {self.status}"


class PaymentTransaction(models.Model):
    payment = models.ForeignKey(Payment, on_delete=models.CASCADE, related_name='transactions')
    amount = models.FloatField()
    transaction_type = models.CharField(max_length=20, choices=[
        ('deposit', 'Deposit Payment'),
        ('balance', 'Balance Payment'),
        ('extension', 'Extension Payment'),
        ('refund', 'Refund'),
    ])
    status = models.CharField(max_length=20, choices=[
        ('success', 'Success'),
        ('failed', 'Failed'),
        ('pending', 'Pending'),
    ], default='pending')
    transaction_id = models.CharField(max_length=50, unique=True)
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.transaction_type} - ₹{self.amount} - {self.status}"


# ===================== RECEIPT MODEL ===================== #
class Receipt(models.Model):
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE)
    receipt_number = models.CharField(max_length=50, unique=True)
    generated_at = models.DateTimeField(auto_now_add=True)
    total_amount = models.FloatField()
    amount = models.IntegerField()
    payment_status = models.CharField(max_length=20, default="SUCCESS")
    payment_method = models.CharField(max_length=50)
    transaction_id = models.CharField(max_length=50)

    def __str__(self):
        return f"Receipt {self.receipt_number} - {self.booking.user.username}"

    def generate_receipt_number(self):
        return f"RCP-{self.generated_at.strftime('%Y%m%d')}-{uuid.uuid4().hex[:8].upper()}"