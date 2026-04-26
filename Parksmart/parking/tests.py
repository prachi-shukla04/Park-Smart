from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta
from .models import Parking, Booking, UserProfile, FavoriteParking, Payment


class ParkingModelTest(TestCase):
    def setUp(self):
        self.provider = User.objects.create_user(username='provider', password='pass')
        UserProfile.objects.create(user=self.provider, role='provider')

    def test_parking_creation(self):
        parking = Parking.objects.create(
            provider=self.provider,
            parking_name='Test Parking',
            location='Test Location',
            bike_slots=10,
            car_slots=5,
            available_bike_slots=10,
            available_car_slots=5,
        )
        self.assertEqual(parking.available_bike_slots, 10)
        self.assertEqual(parking.available_car_slots, 5)
        self.assertEqual(str(parking), 'Test Parking — Test Location')

    def test_get_price(self):
        parking = Parking.objects.create(
            provider=self.provider,
            parking_name='Test',
            location='Test',
            bike_price=20, car_price=50,
        )
        self.assertEqual(parking.get_price('Bike'), 20)
        self.assertEqual(parking.get_price('Car'), 50)

    def test_reset_daily_counters(self):
        parking = Parking.objects.create(
            provider=self.provider,
            parking_name='Test Parking',
            location='Test Location',
            bike_slots=10,
            available_bike_slots=10,
            bike_first_free_limit=2,
        )
        parking.used_bike_first_free_today = 1
        parking.save()
        parking.reset_daily_counters()
        parking.refresh_from_db()
        self.assertEqual(parking.used_bike_first_free_today, 0)


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
            bike_slots=10, car_slots=5,
            available_bike_slots=10, available_car_slots=5,
            bike_price=20, car_price=50,
            bike_first_free_limit=2,
        )

    def test_booking_with_time_slot(self):
        """Phase 2: Test booking with start/end time instead of hours"""
        now = timezone.now()
        booking = Booking.objects.create(
            user=self.user,
            parking=self.parking,
            vehicle_type='Bike',
            vehicle_number='UP32AB1234',
            start_time=now,
            end_time=now + timedelta(hours=2),
            total_price=40,
            status='booked',
        )
        booking.refresh_from_db()
        self.assertEqual(booking.status, 'booked')
        self.assertIsNotNone(booking.booking_code)

    def test_booking_status_flow(self):
        """Phase 2: Test status transitions"""
        now = timezone.now()
        booking = Booking.objects.create(
            user=self.user,
            parking=self.parking,
            vehicle_type='Car',
            vehicle_number='UP32AB1234',
            start_time=now,
            end_time=now + timedelta(hours=1),
            total_price=50,
            status='booked',
        )
        # Simulate provider marking exit
        booking.status = 'completed'
        booking.is_checked_out = True
        booking.actual_exit_time = timezone.now()
        booking.save()
        booking.refresh_from_db()
        self.assertEqual(booking.status, 'completed')
        self.assertTrue(booking.is_checked_out)


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
            bike_slots=10,
            available_bike_slots=10,
        )

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
            bike_slots=10, car_slots=5,
            available_bike_slots=10, available_car_slots=5,
            bike_price=20, car_price=50,
            bike_first_free_limit=2,
        )

    def test_user_dashboard_requires_login(self):
        response = self.client.get('/user/dashboard/')
        self.assertEqual(response.status_code, 302)

    def test_user_dashboard_logged_in(self):
        self.client.login(username='user', password='pass')
        session = self.client.session
        session['role'] = 'user'
        session.save()
        response = self.client.get('/user/dashboard/')
        self.assertEqual(response.status_code, 200)

    def test_book_parking_with_time_slot(self):
        """Phase 2: Test booking via POST with start/end time"""
        self.client.login(username='user', password='pass')
        now = timezone.localtime(timezone.now())
        start = (now + timedelta(minutes=10)).strftime('%Y-%m-%dT%H:%M')
        end = (now + timedelta(hours=2)).strftime('%Y-%m-%dT%H:%M')
        response = self.client.post(f'/book-parking/{self.parking.id}/', {
            'vehicle_type': 'Bike',
            'vehicle_number': 'UP32AB1234',
            'start_time': start,
            'end_time': end,
            'payment_timing': 'pay_now',
        }, follow=True)
        
        booking = Booking.objects.filter(user=self.user).first()
        self.assertIsNotNone(booking)
        self.assertEqual(booking.status, 'booked')
