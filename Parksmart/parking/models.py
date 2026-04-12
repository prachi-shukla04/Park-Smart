from datetime import timedelta

from django.db import models
from django.contrib.auth.models import User
import re
from django.core.exceptions import ValidationError



# ===================== PARKING MODEL ===================== #
class Parking(models.Model):
    provider = models.ForeignKey(User, on_delete=models.CASCADE)
    parking_name = models.CharField(max_length=100)
    location = models.CharField(max_length=200)

    # Vehicle-wise slots
    bike_slots = models.IntegerField(default=0)
    car_slots = models.IntegerField(default=0)
    suv_slots = models.IntegerField(default=0)
    truck_slots = models.IntegerField(default=0)

    # Available slots
    available_bike_slots = models.IntegerField(default=0)
    available_car_slots = models.IntegerField(default=0)
    available_suv_slots = models.IntegerField(default=0)
    available_truck_slots = models.IntegerField(default=0)

    # Pricing per vehicle
    bike_price = models.FloatField(default=0)
    car_price = models.FloatField(default=0)
    suv_price = models.FloatField(default=0)
    truck_price = models.FloatField(default=0)

    image = models.ImageField(upload_to='parking_images/', null=True, blank=True)

    def save(self, *args, **kwargs):
        if not self.pk:
            self.available_bike_slots = self.bike_slots
            self.available_car_slots = self.car_slots
            self.available_suv_slots = self.suv_slots
            self.available_truck_slots = self.truck_slots
        super().save(*args, **kwargs)


# ===================== USER PROFILE ===================== #
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

class Booking(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    parking = models.ForeignKey(Parking, on_delete=models.CASCADE)

    vehicle_type = models.CharField(max_length=20, choices=VEHICLE_CHOICES)
    vehicle_number = models.CharField(max_length=20)

    hours = models.IntegerField(default=1)
    total_price = models.FloatField(blank=True, null=True)

    booking_time = models.DateTimeField(auto_now_add=True)
    end_time = models.DateTimeField(blank=True, null=True)

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

        price = PRICE_PER_HOUR.get(self.vehicle_type, 50)
        self.total_price = price * self.hours

        if self.booking_time:
            self.end_time = self.booking_time + timedelta(hours=self.hours)

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.user.username} - {self.parking.parking_name}"