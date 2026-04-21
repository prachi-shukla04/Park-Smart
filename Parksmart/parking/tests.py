from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta
from .models import Parking, Booking, UserProfile, FavoriteParking, Payment


class ParkingModelTest(TestCase):
    def setUp(self):
        self.provider = User.objects.create_user(username='provider', password='pass')
        UserProfile.objects.create(user=self.provider, role='provider')

    # Model Test: Test that when a parking is created, available slots are set equal to total slots
    def test_parking_save_sets_available_slots(self):
        parking = Parking.objects.create(
            provider=self.provider,
            parking_name='Test Parking',
            location='Test Location',
            bike_slots=10,
            car_slots=5
        )
        self.assertEqual(parking.available_bike_slots, 10)
        self.assertEqual(parking.available_car_slots, 5)

    # Model Test: Test that daily counters reset when the date changes
    def test_reset_daily_counters(self):
        parking = Parking.objects.create(
            provider=self.provider,
            parking_name='Test Parking',
            location='Test Location',
            bike_slots=10,
            daily_free_slots=2
        )
        parking.used_free_slots_today = 1
        parking.save()
        parking.reset_daily_counters()
        parking.refresh_from_db()
        self.assertEqual(parking.used_free_slots_today, 0)


class BookingTest(TestCase):
    def setUp(self):
        self.provider = User.objects.create_user(username='provider', password='pass')
        UserProfile.objects.create(user=self.provider, role='provider')
        self.user = User.objects.create_user(username='user', password='pass')
        UserProfile.objects.create(user=self.user, role='user')
        self.parking = Parking.objects.create(
            provider=self.provider,
            parking_name='Test Parking',
            location='Test Location',
            bike_slots=10,
            car_slots=5,
            bike_price=20,
            car_price=50,
            daily_free_slots=1,
            first_free_limit=2
        )

    # Unit Test: Test that booking creation sets correct total price
    def test_booking_creation(self):
        booking = Booking.objects.create(
            user=self.user,
            parking=self.parking,
            vehicle_type='Bike',
            vehicle_number='UP32AB1234',
            hours=2
        )
        booking.refresh_from_db()  # To get auto fields
        self.assertEqual(booking.total_price, 40)


class FavoriteTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='user', password='pass')
        UserProfile.objects.create(user=self.user, role='user')
        self.provider = User.objects.create_user(username='provider', password='pass')
        UserProfile.objects.create(user=self.provider, role='provider')
        self.parking = Parking.objects.create(
            provider=self.provider,
            parking_name='Test Parking',
            location='Test Location',
            bike_slots=10
        )

    # Integration Test: Test that adding a favorite creates the relationship
    def test_add_favorite(self):
        favorite = FavoriteParking.objects.create(user=self.user, parking=self.parking)
        self.assertEqual(favorite.user, self.user)
        self.assertEqual(favorite.parking, self.parking)


class ViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='user', password='pass')
        UserProfile.objects.create(user=self.user, role='user')
        self.provider = User.objects.create_user(username='provider', password='pass')
        UserProfile.objects.create(user=self.provider, role='provider')
        self.parking = Parking.objects.create(
            provider=self.provider,
            parking_name='Test Parking',
            location='Test Location',
            bike_slots=10,
            car_slots=5,
            bike_price=20,
            car_price=50,
            first_free_limit=2
        )

    # View Test: Test that user dashboard requires login (redirects to login)
    def test_user_dashboard_requires_login(self):
        response = self.client.get('/user/dashboard/')
        self.assertEqual(response.status_code, 302)  # Redirect to login

    # View Test: Test that logged-in user can access dashboard
    def test_user_dashboard_logged_in(self):
        self.client.login(username='user', password='pass')
        session = self.client.session
        session['role'] = 'user'
        session.save()
        response = self.client.get('/user/dashboard/')
        self.assertEqual(response.status_code, 200)

    # Integration Test: Test the booking creation via POST request, including promotions
    def test_book_parking(self):
        self.client.login(username='user', password='pass')
        response = self.client.post(f'/book-parking/{self.parking.id}/', {
            'vehicle_type': 'Bike',
            'vehicle_number': 'UP32AB1234',
            'hours': 1
        })
        self.assertEqual(response.status_code, 302)  # Redirect after booking
        booking = Booking.objects.filter(user=self.user).first()
        self.assertIsNotNone(booking)
        self.assertEqual(booking.total_price, 0)  # Should be free (first booking)
