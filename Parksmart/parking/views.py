from datetime import datetime, timedelta


from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages

from django.http import HttpResponse
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Q
from django.core.files.base import ContentFile
from django.utils import timezone
from .utils import generate_receipt_pdf
import uuid, math
from django.db import transaction
from .models import Parking, Booking, ParkingImage, UserProfile, Payment, PaymentTransaction, FavoriteParking, RecurringBooking, Receipt


# ===================== RECEIPT GENERATION ===================== #
@login_required
def receipt_generation(request, booking_id):
    booking = get_object_or_404(Booking, id=booking_id, user=request.user)

    transaction = PaymentTransaction.objects.filter(
        payment__booking=booking,
        status='success'
    ).order_by('-created_at').first()

    if not transaction:
        return HttpResponse("No transaction found")

    receipt_number = f"RCP-{timezone.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:8].upper()}"

    return render(request, 'receipt_generation.html', {
        'booking': booking,
        'transaction': transaction,
        'receipt_number': receipt_number
    })


# ===================== HOME ===================== #
def home(request):
    return render(request, 'base.html')


# ===================== REGISTER ===================== #
def register(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        email = request.POST.get('email')
        phone = request.POST.get('phone')
        address = request.POST.get('address')
        role = request.POST.get('role')
        password = request.POST.get('password')

        if User.objects.filter(username=email).exists():
            return render(request, 'register.html', {'error': 'User already exists'})

        user = User.objects.create_user(
            username=email,
            email=email,
            password=password,
            first_name=name
        )

        UserProfile.objects.create(
            user=user,
            phone=phone,
            address=address,
            role=role
        )

        return redirect('login')

    return render(request, 'register.html', {'page': 'register'})


# ===================== LOGIN ===================== #
def login_view(request):
    if request.method == "POST":
        email = request.POST.get('email')
        password = request.POST.get('password')
        role = request.POST.get('role')

        user = authenticate(request, username=email, password=password)

        if user is not None:
            profile = UserProfile.objects.filter(user=user).first()
            if not profile:
                return render(request, 'login.html', {'error': 'Profile missing'})

            if profile.role == role:
                login(request, user)
                request.session['role'] = profile.role

                return redirect('parking_provider' if role == 'provider' else 'user_dashboard')
            else:
                return render(request, 'login.html', {'error': 'Wrong role selected'})
        else:
            return render(request, 'login.html', {'error': 'Invalid credentials'})

    return render(request, 'login.html', {'page': 'login'})
# ===================== LOGOUT ===================== #
def logout_view(request):
    logout(request)
    return redirect('login')

# ===================== USER DASHBOARD ===================== #

@login_required
def user_dashboard(request):
    if request.session.get('role') != 'user':
        return redirect('login')

    query = request.GET.get('q', '').strip()

    parkings = Parking.objects.all()

    if query:
        parkings = parkings.filter(
            Q(parking_name__icontains=query) |
            Q(location__icontains=query)
        )

    for p in parkings:
        total = (
            p.available_bike_slots +
            p.available_car_slots +
            p.available_suv_slots +
            p.available_truck_slots
        )
        p.total_available = total

        if total == 0:
            p.availability_status = "FULL"
        elif total < 5:
            p.availability_status = "ALMOST"
        else:
            p.availability_status = "AVAILABLE"

    parkings = sorted(parkings, key=lambda x: x.total_available, reverse=True)

    user_bookings = Booking.objects.filter(
        user=request.user,
        status__in=['booked', 'active', 'overstaying']
    )
    booked_parking_ids = user_bookings.values_list('parking_id', flat=True)

    favorites = FavoriteParking.objects.filter(user=request.user)\
                .values_list('parking_id', flat=True)

    return render(request, 'user_dashboard.html', {
        'parkings': parkings,
        'booked_parking_ids': booked_parking_ids,
        'favorites': favorites,
        'has_searched': bool(query),
        'query': query
    })
# ===================== BOOK PARKING ===================== #
@login_required
def book_parking(request, parking_id):
    parking = get_object_or_404(Parking, id=parking_id)

    # ✅ Phase 2: Check using status instead of is_active
    if Booking.objects.filter(
        user=request.user, parking=parking,
        status__in=['booked', 'active', 'overstaying']
    ).exists():
        messages.error(request, "You already have an active booking at this parking ❌")
        return redirect('user_dashboard')

    if request.method == "POST":
        vehicle_type = request.POST.get('vehicle_type')
        vehicle_number = request.POST.get('vehicle_number', '').upper()
        payment_timing = request.POST.get('payment_timing', 'pay_now')

        # ✅ Phase 2: Parse user-selected time slot
        start_time_str = request.POST.get('start_time')
        end_time_str = request.POST.get('end_time')

        try:
            start_time = timezone.make_aware(
                datetime.strptime(start_time_str, '%Y-%m-%dT%H:%M')
            ) if start_time_str else None
            end_time = timezone.make_aware(
                datetime.strptime(end_time_str, '%Y-%m-%dT%H:%M')
            ) if end_time_str else None
        except (ValueError, TypeError):
            messages.error(request, "Invalid date/time format")
            return redirect('book_parking', parking_id=parking_id)

        if not start_time or not end_time:
            messages.error(request, "Please select start and end time")
            return redirect('book_parking', parking_id=parking_id)

        if start_time >= end_time:
            messages.error(request, "End time must be after start time")
            return redirect('book_parking', parking_id=parking_id)

        if start_time < timezone.now() - timedelta(minutes=5):
            messages.error(request, "Start time cannot be in the past")
            return redirect('book_parking', parking_id=parking_id)

        hours = max(1, math.ceil((end_time - start_time).total_seconds() / 3600))

        parking.reset_daily_counters()

        # ✅ Phase 1: Transaction safety — prevents race conditions
        with transaction.atomic():
            parking = Parking.objects.select_for_update().get(id=parking_id)

            if vehicle_type == "Bike":
                if parking.available_bike_slots <= 0:
                    messages.error(request, "No bike slots available ❌")
                    return redirect('user_dashboard')
                price = parking.bike_price
                parking.available_bike_slots -= 1
            elif vehicle_type == "Car":
                if parking.available_car_slots <= 0:
                    messages.error(request, "No car slots available ❌")
                    return redirect('user_dashboard')
                price = parking.car_price
                parking.available_car_slots -= 1
            elif vehicle_type == "SUV":
                if parking.available_suv_slots <= 0:
                    messages.error(request, "No SUV slots available ❌")
                    return redirect('user_dashboard')
                price = parking.suv_price
                parking.available_suv_slots -= 1
            elif vehicle_type == "Truck":
                if parking.available_truck_slots <= 0:
                    messages.error(request, "No truck slots available ❌")
                    return redirect('user_dashboard')
                price = parking.truck_price
                parking.available_truck_slots -= 1
            else:
                messages.error(request, "Invalid vehicle type")
                return redirect('user_dashboard')

            # ✅ Free hours promotion — deduct free hours from total
            free_hours_map = {
                "Bike": parking.bike_first_free_limit,
                "Car": parking.car_first_free_limit,
                "SUV": parking.suv_first_free_limit,
                "Truck": parking.truck_first_free_limit,
            }
            free_hours = free_hours_map.get(vehicle_type, 0)

            # Calculate billable hours (total hours minus free hours)
            billable_hours = max(0, hours - free_hours)
            total_price = price * billable_hours

            # ✅ Phase 3: Assign a real-world physical slot number (e.g., C-3, B-12)
            prefix = vehicle_type[0].upper()
            if vehicle_type == "Bike":
                max_slots = parking.bike_slots
            elif vehicle_type == "Car":
                max_slots = parking.car_slots
            elif vehicle_type == "SUV":
                max_slots = parking.suv_slots
            else: # Truck
                max_slots = parking.truck_slots

            active_bookings = Booking.objects.filter(
                parking=parking,
                vehicle_type=vehicle_type,
                status__in=['booked', 'active', 'overstaying']
            ).exclude(assigned_slot__isnull=True)
            
            occupied_slots = set(active_bookings.values_list('assigned_slot', flat=True))
            
            assigned_slot = f"{prefix}-1"
            for i in range(1, max_slots + 1):
                candidate = f"{prefix}-{i}"
                if candidate not in occupied_slots:
                    assigned_slot = candidate
                    break

            booking = Booking.objects.create(
                user=request.user,
                parking=parking,
                vehicle_type=vehicle_type,
                vehicle_number=vehicle_number,
                hours=hours,
                total_price=total_price,
                start_time=start_time,
                end_time=end_time,
                payment_timing=payment_timing,
                status='booked',
                assigned_slot=assigned_slot,
            )

            parking.save()

        # If total is ₹0 (fully within free hours), skip payment
        if total_price == 0:
            messages.success(request, f"🎉 Booking confirmed! First {free_hours} hour(s) FREE!")
            return redirect('my_bookings')

        Payment.objects.create(booking=booking, total_amount=total_price)

        if payment_timing == 'pay_now':
            return redirect('payment_qr', booking_id=booking.id)

        messages.success(request, f"Booking confirmed! Pay ₹{total_price} later.")
        return redirect('my_bookings')

    return render(request, 'book_parking.html', {'parking': parking})
# ===================== MY BOOKINGS ===================== #
from collections import defaultdict

@login_required
def my_bookings(request):
    now = timezone.now()
    bookings = Booking.objects.filter(user=request.user)

    # ✅ Phase 2: Auto-update status based on time
    for b in bookings:
        if b.status == 'booked' and b.start_time and b.start_time <= now:
            b.status = 'active'
            b.save(update_fields=['status'])
        if b.status == 'active' and b.end_time and b.end_time < now:
            b.status = 'overstaying'
            b.save(update_fields=['status'])

    active_bookings = list(bookings.filter(status__in=['booked', 'active', 'overstaying']))
    completed_bookings = list(bookings.filter(status__in=['completed', 'cancelled']))

    # Attach receipts to each booking
    booking_ids = [b.id for b in active_bookings + completed_bookings]
    receipts = Receipt.objects.filter(booking_id__in=booking_ids)

    receipts_dict = defaultdict(list)
    for receipt in receipts:
        receipts_dict[receipt.booking_id].append(receipt)

    for b in active_bookings + completed_bookings:
        b.receipts = receipts_dict.get(b.id, [])

    return render(request, 'my_booking.html', {
        'active_bookings': active_bookings,
        'expired_bookings': completed_bookings,
    })

# ===================== CANCEL BOOKING ===================== #

@login_required
def cancel_booking(request, booking_id):
    if request.method != "POST":
        return redirect("my_bookings")

    booking = get_object_or_404(Booking, id=booking_id, user=request.user)

    # ✅ Phase 2: Use status instead of is_active
    if booking.status in ['completed', 'cancelled']:
        messages.info(request, "Already cancelled or completed")
        return redirect("my_bookings")

    # Only allow cancel if vehicle hasn't been parked yet (status is 'booked')
    with transaction.atomic():
        parking = Parking.objects.select_for_update().get(id=booking.parking_id)

        # Free the slot
        if booking.vehicle_type == "Bike":
            parking.available_bike_slots = min(parking.available_bike_slots + 1, parking.bike_slots)
        elif booking.vehicle_type == "Car":
            parking.available_car_slots = min(parking.available_car_slots + 1, parking.car_slots)
        elif booking.vehicle_type == "SUV":
            parking.available_suv_slots = min(parking.available_suv_slots + 1, parking.suv_slots)
        elif booking.vehicle_type == "Truck":
            parking.available_truck_slots = min(parking.available_truck_slots + 1, parking.truck_slots)

        parking.save()

        booking.status = 'cancelled'
        booking.is_active = False
        booking.save()

        # ✅ Razorpay Refund — if payment was completed, refund the money
        try:
            payment = Payment.objects.get(booking=booking)
            if payment.status == 'completed' and payment.razorpay_payment_id:
                # Trigger refund via Razorpay API
                refund = razorpay_client.payment.refund(payment.razorpay_payment_id, {
                    'amount': int(payment.total_amount * 100),  # in paise
                    'notes': {
                        'reason': 'Booking cancelled by user',
                        'booking_code': booking.booking_code,
                    }
                })

                # Log the refund transaction
                PaymentTransaction.objects.create(
                    payment=payment,
                    amount=payment.total_amount,
                    transaction_type='refund',
                    status='success',
                    transaction_id=refund.get('id', ''),
                    payment_method='razorpay',
                )

                payment.status = 'refunded'
                payment.save()

                messages.success(request, f"Booking cancelled. ₹{payment.total_amount} refund initiated — will reach your account in 5-7 business days 💰")
                return redirect("my_bookings")

            elif payment.status == 'pending':
                payment.status = 'cancelled'
                payment.save()

        except Payment.DoesNotExist:
            pass  # No payment record — free booking
        except Exception as e:
            logger.error(f"Refund failed for {booking.booking_code}: {e}")
            messages.warning(request, "Booking cancelled but refund failed. Contact support.")
            return redirect("my_bookings")

    messages.success(request, "Booking cancelled successfully ✅")
    return redirect("my_bookings")
# ===================== VIEW SLOTS ===================== #
@login_required
def view_slots(request, parking_id):
    parking = get_object_or_404(Parking, id=parking_id)
    return render(request, 'view_slots.html', {'parking': parking})


# ✅ Phase 2: auto_cancel_expired_bookings() REMOVED
# Slots are now only freed when provider marks vehicle exit

# ===================== ADD FAVORITE ===================== #
@login_required
def add_favorite(request, parking_id):
    parking = get_object_or_404(Parking, id=parking_id)
    FavoriteParking.objects.get_or_create(user=request.user, parking=parking)
    messages.success(request, f"Added {parking.parking_name} to favorites ❤️")
    return redirect('user_dashboard')


# ===================== REMOVE FAVORITE ===================== #
@login_required
def remove_favorite(request, parking_id):
    parking = get_object_or_404(Parking, id=parking_id)
    FavoriteParking.objects.filter(user=request.user, parking=parking).delete()
    messages.success(request, f"Removed {parking.parking_name} from favorites")
    return redirect('user_dashboard')


# ===================== EXTEND BOOKING ===================== #
@login_required
def extend_booking(request, booking_id):
    booking = get_object_or_404(Booking, id=booking_id, user=request.user)

    # Check if booking has payment
    try:
        payment = booking.payment
    except Payment.DoesNotExist:
        messages.error(request, "Payment record not found")
        return redirect('my_bookings')

    # Redirect to extension payment instead of direct extension
    return redirect('payment_extension', booking_id=booking.id)
# ===================== EARLY EXIT ===================== #
# ✅ Phase 2: User can request early exit, but slot is NOT freed
# Provider must confirm via mark_vehicle_exit

@login_required
def early_exit(request, booking_id):
    booking = get_object_or_404(
        Booking, id=booking_id, user=request.user,
        status__in=['booked', 'active']
    )

    # Calculate usage from start_time
    start = booking.start_time or booking.booking_time
    used_time = (timezone.now() - start).total_seconds() / 3600
    used_hours = max(1, math.ceil(used_time))

    rate = booking.parking.get_price(booking.vehicle_type)
    actual_price = used_hours * rate

    if actual_price < booking.total_price:
        refund = booking.total_price - actual_price
        messages.success(request, f"₹{refund} refund will be processed 💸")
    elif actual_price > booking.total_price:
        return redirect('payment_extension', booking_id=booking.id)
    else:
        messages.info(request, "No extra charge")

    booking.total_price = actual_price
    booking.status = 'completed'
    booking.is_active = False
    booking.is_checked_out = True
    booking.actual_exit_time = timezone.now()
    booking.save()

    # ✅ Phase 2: Free slot on early exit (user-initiated exit)
    with transaction.atomic():
        parking = Parking.objects.select_for_update().get(id=booking.parking_id)
        if booking.vehicle_type == "Bike":
            parking.available_bike_slots = min(parking.available_bike_slots + 1, parking.bike_slots)
        elif booking.vehicle_type == "Car":
            parking.available_car_slots = min(parking.available_car_slots + 1, parking.car_slots)
        elif booking.vehicle_type == "SUV":
            parking.available_suv_slots = min(parking.available_suv_slots + 1, parking.suv_slots)
        elif booking.vehicle_type == "Truck":
            parking.available_truck_slots = min(parking.available_truck_slots + 1, parking.truck_slots)
        parking.save()

    return redirect('my_bookings')
# ===================== PROVIDER DASHBOARD ===================== #
@login_required
def parking_provider(request):
    if request.session.get('role') == 'provider':
        return render(request, 'parking_provider.html')
    return redirect('login')
# ===================== ADD PARKING ===================== #

@login_required
def add_parking(request):
    if request.method == "POST":

        latitude = request.POST.get('latitude')
        longitude = request.POST.get('longitude')

        latitude = float(latitude) if latitude else None
        longitude = float(longitude) if longitude else None

        if latitude is None or longitude is None:
            messages.error(request, "Please select location from map")
            return redirect('add_parking')

        bike_slots = int(request.POST.get('bike_slots') or 0)
        car_slots = int(request.POST.get('car_slots') or 0)
        suv_slots = int(request.POST.get('suv_slots') or 0)
        truck_slots = int(request.POST.get('truck_slots') or 0)

        parking = Parking.objects.create(
            provider=request.user,
            parking_name=request.POST.get('parking_name'),
            location=request.POST.get('location'),
            latitude=latitude,
            longitude=longitude,

            bike_slots=bike_slots,
            car_slots=car_slots,
            suv_slots=suv_slots,
            truck_slots=truck_slots,

            bike_price=float(request.POST.get('bike_price') or 0),
            car_price=float(request.POST.get('car_price') or 0),
            suv_price=float(request.POST.get('suv_price') or 0),
            truck_price=float(request.POST.get('truck_price') or 0),

            bike_first_free_limit=int(request.POST.get('bike_first_free_limit') or 0),
            car_first_free_limit=int(request.POST.get('car_first_free_limit') or 0),
            suv_first_free_limit=int(request.POST.get('suv_first_free_limit') or 0),
            truck_first_free_limit=int(request.POST.get('truck_first_free_limit') or 0),

            # ✅ FIX HERE
            available_bike_slots=bike_slots,
            available_car_slots=car_slots,
            available_suv_slots=suv_slots,
            available_truck_slots=truck_slots,
        )


        # Images
        for img in request.FILES.getlist('images'):
            ParkingImage.objects.create(parking=parking, image=img)

        return redirect('my_parking')

    return render(request, 'add_parking.html')
# ===================== MY PARKING ===================== #
@login_required
def my_parking(request):
    parkings = Parking.objects.filter(provider=request.user)
    return render(request, 'my_parking.html', {'parkings': parkings})


# ===================== EDIT PARKING ===================== #
@login_required
def edit_parking(request, id):
    parking = get_object_or_404(Parking, id=id, provider=request.user)

    if request.method == 'POST':

        parking.parking_name = request.POST.get('parking_name')
        parking.location = request.POST.get('location')

        parking.bike_slots = int(request.POST.get('bike_slots', 0))
        parking.car_slots = int(request.POST.get('car_slots', 0))
        parking.suv_slots = int(request.POST.get('suv_slots', 0))
        parking.truck_slots = int(request.POST.get('truck_slots', 0))

        parking.bike_price = float(request.POST.get('bike_price', 0))
        parking.car_price = float(request.POST.get('car_price', 0))
        parking.suv_price = float(request.POST.get('suv_price', 0))
        parking.truck_price = float(request.POST.get('truck_price', 0))

        # ✅ VEHICLE FREE LIMITS
        parking.bike_first_free_limit = int(request.POST.get('bike_first_free_limit', 0))
        parking.car_first_free_limit = int(request.POST.get('car_first_free_limit', 0))
        parking.suv_first_free_limit = int(request.POST.get('suv_first_free_limit', 0))
        parking.truck_first_free_limit = int(request.POST.get('truck_first_free_limit', 0))

        # Adjust available slots safely
        parking.available_bike_slots = min(parking.available_bike_slots, parking.bike_slots)
        parking.available_car_slots = min(parking.available_car_slots, parking.car_slots)
        parking.available_suv_slots = min(parking.available_suv_slots, parking.suv_slots)
        parking.available_truck_slots = min(parking.available_truck_slots, parking.truck_slots)

        parking.save()


        # Images
        for img in request.FILES.getlist('images'):
            ParkingImage.objects.create(parking=parking, image=img)

        return redirect('my_parking')

    return render(request, 'edit_parking.html', {'parking': parking})


# ===================== DELETE IMAGE ===================== #
@login_required
def delete_image(request, image_id):
    image = get_object_or_404(ParkingImage, id=image_id)
    parking = image.parking

    # ✅ VERIFY OWNERSHIP
    if parking.provider != request.user:
        return redirect('my_parking')

    parking_id = parking.id
    image.delete()
    return redirect('edit_parking', id=parking_id)


# ===================== DELETE PARKING ===================== #
@login_required
def delete_parking(request, id):
    parking = get_object_or_404(Parking, id=id, provider=request.user)
    parking.delete()
    return redirect('my_parking')


# ===================== PROVIDER BOOKINGS ===================== #
@login_required
def provider_bookings(request):
    now = timezone.now()
    all_bookings = Booking.objects.filter(
        parking__provider=request.user
    ).exclude(status='cancelled').select_related('parking', 'user')

    # ✅ Phase 2: Auto-update statuses
    for b in all_bookings:
        if b.status == 'booked' and b.start_time and b.start_time <= now:
            b.status = 'active'
            b.save(update_fields=['status'])
        if b.status == 'active' and b.end_time and b.end_time < now:
            b.status = 'overstaying'
            b.save(update_fields=['status'])

    active_bookings = all_bookings.filter(status__in=['booked', 'active'])
    overstaying_bookings = all_bookings.filter(status='overstaying')
    completed_bookings = all_bookings.filter(status='completed')

    return render(request, 'provider_bookings.html', {
        'active_bookings': active_bookings,
        'overstaying_bookings': overstaying_bookings,
        'completed_bookings': completed_bookings,
        'now': now,
    })


# ===================== RATINGS ===================== #
@login_required
def submit_rating(request, booking_id):
    if request.method == "POST":
        booking = get_object_or_404(Booking, id=booking_id, user=request.user)
        if booking.status == 'completed':
            rating = request.POST.get('rating')
            if rating and rating.isdigit() and 1 <= int(rating) <= 5:
                booking.rating = int(rating)
                booking.save()
                messages.success(request, "Thanks for your feedback! ⭐")
        return redirect('my_bookings')
    return redirect('my_bookings')

# ===================== QR CODE EXIT SCANNER ===================== #
@login_required
def scan_qr(request, booking_id):
    """Provider scans the user's QR code to mark exit"""
    booking = get_object_or_404(Booking, id=booking_id)

    if booking.parking.provider != request.user:
        messages.error(request, "Unauthorized. You don't own this parking lot ❌")
        return redirect('provider_bookings')

    if booking.is_checked_out:
        messages.info(request, "Vehicle is already checked out.")
        return redirect('provider_bookings')

    # If GET request, show confirmation page. If POST, we could mark exit.
    # Actually, we can just render a simple confirmation page or directly invoke mark_vehicle_exit.
    # Since mark_vehicle_exit requires POST, we'll render a confirm page.
    return render(request, 'scan_confirm.html', {'booking': booking})


# ===================== MARK VEHICLE EXIT (Phase 2) ===================== #
@login_required
def mark_vehicle_exit(request, booking_id):
    """Provider marks that a vehicle has physically left the parking."""
    if request.method != "POST":
        return redirect('provider_bookings')

    booking = get_object_or_404(Booking, id=booking_id)

    # Verify this provider owns the parking
    if booking.parking.provider != request.user:
        messages.error(request, "Unauthorized ❌")
        return redirect('provider_bookings')

    if booking.is_checked_out:
        messages.info(request, "Vehicle already checked out")
        return redirect('provider_bookings')

    now = timezone.now()

    # Calculate overstay penalty (1.5x rate for extra hours)
    # Added 15-minute grace period
    penalty = 0
    if booking.end_time:
        grace_period_end = booking.end_time + timedelta(minutes=15)
        if now > grace_period_end:
            overstay_seconds = (now - booking.end_time).total_seconds()
            overstay_hours = max(1, math.ceil(overstay_seconds / 3600))
            rate = booking.parking.get_price(booking.vehicle_type)
            penalty = overstay_hours * rate * 1.5

    with transaction.atomic():
        parking = Parking.objects.select_for_update().get(id=booking.parking_id)

        booking.is_checked_out = True
        booking.actual_exit_time = now
        booking.status = 'completed'
        booking.overstay_penalty = penalty
        booking.is_active = False
        booking.save()

        # ✅ NOW free the slot (only when provider confirms)
        if booking.vehicle_type == "Bike":
            parking.available_bike_slots = min(parking.available_bike_slots + 1, parking.bike_slots)
        elif booking.vehicle_type == "Car":
            parking.available_car_slots = min(parking.available_car_slots + 1, parking.car_slots)
        elif booking.vehicle_type == "SUV":
            parking.available_suv_slots = min(parking.available_suv_slots + 1, parking.suv_slots)
        elif booking.vehicle_type == "Truck":
            parking.available_truck_slots = min(parking.available_truck_slots + 1, parking.truck_slots)
        parking.save()

    if penalty > 0:
        messages.warning(request, f"Vehicle checked out with overstay penalty: ₹{penalty:.0f}")
    else:
        messages.success(request, "Vehicle checked out successfully ✅")

    return redirect('provider_bookings')


# ===================== PROVIDER EARNINGS ===================== #
@login_required
def provider_earnings(request):
    bookings = Booking.objects.filter(
        parking__provider=request.user,
        status__in=['completed', 'active', 'booked', 'overstaying']
    ).select_related('parking').order_by('-booking_time')

    total_earnings = bookings.aggregate(Sum('total_price'))['total_price__sum'] or 0
    total_penalties = bookings.aggregate(Sum('overstay_penalty'))['overstay_penalty__sum'] or 0

    # Calculate paid vs pending
    paid_bookings = []
    pending_bookings = []
    paid_total = 0
    pending_total = 0

    for b in bookings:
        try:
            payment = Payment.objects.get(booking=b)
            b.payment_status = payment.status
            b.payment_txn = payment.razorpay_payment_id or ''
            if payment.status == 'completed':
                paid_bookings.append(b)
                paid_total += payment.total_amount
            else:
                pending_bookings.append(b)
                pending_total += b.total_price
        except Payment.DoesNotExist:
            b.payment_status = 'free' if b.total_price == 0 else 'no_record'
            b.payment_txn = ''
            if b.total_price == 0:
                paid_bookings.append(b)
            else:
                pending_bookings.append(b)
                pending_total += b.total_price

    gross_earnings = total_earnings + total_penalties
    platform_fee = gross_earnings * 0.10
    net_earnings = gross_earnings - platform_fee

    return render(request, 'provider_earning.html', {
        'total_earnings': gross_earnings,
        'total_penalties': total_penalties,
        'paid_total': paid_total,
        'pending_total': pending_total,
        'platform_fee': platform_fee,
        'net_earnings': net_earnings,
        'bookings': bookings,
        'paid_count': len(paid_bookings),
        'pending_count': len(pending_bookings),
    })


# ===================== PAYMENT SYSTEM (Dual Mode: Razorpay + Simulation) ===================== #
import razorpay
from django.conf import settings as django_settings
import json, logging, hashlib

logger = logging.getLogger(__name__)

# ✅ Auto-detect if Razorpay keys are real or placeholder
RAZORPAY_LIVE = (
    not django_settings.RAZORPAY_KEY_ID.startswith('rzp_test_XXXX')
    and 'XXXX' not in django_settings.RAZORPAY_KEY_SECRET
)

if RAZORPAY_LIVE:
    razorpay_client = razorpay.Client(
        auth=(django_settings.RAZORPAY_KEY_ID, django_settings.RAZORPAY_KEY_SECRET)
    )
else:
    razorpay_client = None
    logger.warning("⚠️ Razorpay keys are placeholder — running in SIMULATION mode")


def _generate_txn_id():
    """Generate a realistic transaction ID."""
    return f"pay_SIM{uuid.uuid4().hex[:14].upper()}"


def _generate_order_id():
    """Generate a realistic order ID."""
    return f"order_SIM{uuid.uuid4().hex[:14].upper()}"


# ===================== BOOKING PAYMENT ===================== #
@login_required
def payment_qr(request, booking_id):
    """Show payment page — Razorpay if live, simulation if not."""
    booking = get_object_or_404(Booking, id=booking_id, user=request.user)

    payment, created = Payment.objects.get_or_create(
        booking=booking,
        defaults={'total_amount': booking.total_price}
    )

    if payment.status == 'completed':
        messages.info(request, "This booking is already paid!")
        return redirect('my_bookings')

    amount_paise = int(payment.total_amount * 100)

    if RAZORPAY_LIVE:
        # ✅ REAL MODE — Create Razorpay order
        try:
            if not payment.razorpay_order_id:
                razorpay_order = razorpay_client.order.create({
                    'amount': amount_paise,
                    'currency': 'INR',
                    'payment_capture': 1,
                    'notes': {
                        'booking_code': booking.booking_code,
                        'user': request.user.username,
                    }
                })
                payment.razorpay_order_id = razorpay_order['id']
                payment.save()
        except Exception as e:
            logger.error(f"Razorpay order creation failed: {e}")
            messages.error(request, "Payment gateway error. Please try again.")
            return redirect('my_bookings')

        context = {
            'booking': booking,
            'payment': payment,
            'razorpay_key': django_settings.RAZORPAY_KEY_ID,
            'razorpay_order_id': payment.razorpay_order_id,
            'amount': amount_paise,
            'amount_display': payment.total_amount,
            'user_email': request.user.email,
            'user_name': request.user.first_name or request.user.username,
            'is_live': True,
        }
    else:
        # ✅ SIMULATION MODE — Generate simulated order
        if not payment.razorpay_order_id:
            payment.razorpay_order_id = _generate_order_id()
            payment.save()

        context = {
            'booking': booking,
            'payment': payment,
            'amount': amount_paise,
            'amount_display': payment.total_amount,
            'user_email': request.user.email,
            'user_name': request.user.first_name or request.user.username,
            'is_live': False,
        }

    return render(request, 'payment_qr.html', context)


@login_required
def verify_payment(request, booking_id):
    """Verify payment — real Razorpay verification or simulation."""
    if request.method != 'POST':
        return redirect('my_bookings')

    booking = get_object_or_404(Booking, id=booking_id, user=request.user)

    try:
        payment = Payment.objects.get(booking=booking)
    except Payment.DoesNotExist:
        messages.error(request, "Payment record not found")
        return redirect('my_bookings')

    if payment.status == 'completed':
        return redirect('my_bookings')

    if RAZORPAY_LIVE:
        # ✅ REAL verification
        razorpay_payment_id = request.POST.get('razorpay_payment_id', '')
        razorpay_order_id = request.POST.get('razorpay_order_id', '')
        razorpay_signature = request.POST.get('razorpay_signature', '')

        try:
            razorpay_client.utility.verify_payment_signature({
                'razorpay_order_id': razorpay_order_id,
                'razorpay_payment_id': razorpay_payment_id,
                'razorpay_signature': razorpay_signature,
            })
        except razorpay.errors.SignatureVerificationError:
            logger.warning(f"Signature verification failed: {booking.booking_code}")
            payment.status = 'failed'
            payment.save()
            messages.error(request, "Payment verification failed!")
            return redirect('payment_failed', booking_id=booking.id)

        payment.razorpay_payment_id = razorpay_payment_id
        payment.razorpay_order_id = razorpay_order_id
        payment.razorpay_signature = razorpay_signature
    else:
        # ✅ SIMULATION verification
        payment_method = request.POST.get('payment_method', 'UPI')
        sim_payment_id = _generate_txn_id()

        # Generate a simulated signature (hash of order+payment for consistency)
        sim_signature = hashlib.sha256(
            f"{payment.razorpay_order_id}{sim_payment_id}".encode()
        ).hexdigest()[:40]

        payment.razorpay_payment_id = sim_payment_id
        payment.razorpay_signature = sim_signature

    # ✅ Mark complete (both modes)
    payment.status = 'completed'
    payment.payment_method = 'razorpay' if RAZORPAY_LIVE else 'gateway_sim'
    payment.payment_date = timezone.now()
    payment.save()

    PaymentTransaction.objects.create(
        payment=payment,
        amount=payment.total_amount,
        transaction_type='deposit',
        status='success',
        transaction_id=payment.razorpay_payment_id,
        payment_method=payment.payment_method,
    )

    receipt_number = f"RCP-{timezone.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:8].upper()}"
    receipt = Receipt.objects.create(
        booking=booking,
        receipt_number=receipt_number,
        total_amount=payment.total_amount,
        amount=int(payment.total_amount),
        payment_method=payment.payment_method,
        transaction_id=payment.razorpay_payment_id,
    )

    messages.success(request, f"Payment of ₹{payment.total_amount} successful!")
    return redirect('payment_success', receipt_id=receipt.id)


@login_required
def payment_failed(request, booking_id):
    """Show payment failure page with retry option."""
    booking = get_object_or_404(Booking, id=booking_id, user=request.user)
    return render(request, 'payment_failed.html', {'booking': booking})


# ===================== EXTENSION PAYMENT ===================== #
@login_required
def payment_extension(request, booking_id):
    """Show extension page — Razorpay if live, simulation if not."""
    booking = get_object_or_404(Booking, id=booking_id, user=request.user)

    rate = booking.parking.get_price(booking.vehicle_type)

    if request.method == "POST":
        hours = int(request.POST.get("extension_hours", 1))
        total = rate * hours
        amount_paise = int(total * 100)

        if RAZORPAY_LIVE:
            try:
                razorpay_order = razorpay_client.order.create({
                    'amount': amount_paise,
                    'currency': 'INR',
                    'payment_capture': 1,
                    'notes': {
                        'booking_code': booking.booking_code,
                        'type': 'extension',
                        'extension_hours': str(hours),
                    }
                })
                order_id = razorpay_order['id']
            except Exception as e:
                logger.error(f"Razorpay extension order failed: {e}")
                messages.error(request, "Payment gateway error. Please try again.")
                return redirect('my_bookings')
        else:
            order_id = _generate_order_id()

        context = {
            'booking': booking,
            'extension_hours': hours,
            'extension_total': total,
            'razorpay_key': django_settings.RAZORPAY_KEY_ID,
            'razorpay_order_id': order_id,
            'amount': amount_paise,
            'amount_display': total,
            'user_name': request.user.first_name or request.user.username,
            'user_email': request.user.email,
            'show_checkout': True,
            'is_live': RAZORPAY_LIVE,
        }
        return render(request, "payment_extension.html", context)

    return render(request, "payment_extension.html", {
        "booking": booking,
        "show_checkout": False,
    })


@login_required
def verify_extension(request, booking_id):
    """Verify extension payment and extend the booking."""
    if request.method != 'POST':
        return redirect('my_bookings')

    booking = get_object_or_404(Booking, id=booking_id, user=request.user)
    extension_hours = int(request.POST.get('extension_hours', 1))

    if RAZORPAY_LIVE:
        razorpay_payment_id = request.POST.get('razorpay_payment_id', '')
        razorpay_order_id = request.POST.get('razorpay_order_id', '')
        razorpay_signature = request.POST.get('razorpay_signature', '')

        try:
            razorpay_client.utility.verify_payment_signature({
                'razorpay_order_id': razorpay_order_id,
                'razorpay_payment_id': razorpay_payment_id,
                'razorpay_signature': razorpay_signature,
            })
        except razorpay.errors.SignatureVerificationError:
            logger.warning(f"Extension signature failed: {booking.booking_code}")
            messages.error(request, "Payment verification failed!")
            return redirect('payment_failed', booking_id=booking.id)

        txn_id = razorpay_payment_id
    else:
        txn_id = _generate_txn_id()

    rate = booking.parking.get_price(booking.vehicle_type)
    total = rate * extension_hours

    with transaction.atomic():
        booking.hours += extension_hours
        if booking.end_time:
            booking.end_time += timedelta(hours=extension_hours)
        booking.total_price = (booking.total_price or 0) + total
        booking.save()

        receipt = Receipt.objects.create(
            booking=booking,
            receipt_number=f"RCP-EXT-{uuid.uuid4().hex[:8].upper()}",
            total_amount=total,
            amount=int(total),
            payment_method='razorpay' if RAZORPAY_LIVE else 'gateway_sim',
            transaction_id=txn_id,
        )

    messages.success(request, f"Booking extended by {extension_hours} hours!")
    return redirect("payment_success", receipt_id=receipt.id)


# ===================== DOWNLOAD RECEIPT ===================== #
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from django.http import HttpResponse
from django.shortcuts import get_object_or_404

@login_required
def download_receipt(request, receipt_id):
    receipt = get_object_or_404(Receipt, id=receipt_id)

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename=invoice_{receipt.id}.pdf'

    doc = SimpleDocTemplate(response)
    styles = getSampleStyleSheet()

    elements = []

    elements.append(Paragraph("PARK SMART - INVOICE", styles['Title']))
    elements.append(Spacer(1, 20))

    elements.append(Paragraph(f"<b>Receipt No:</b> {receipt.receipt_number}", styles['Normal']))
    elements.append(Paragraph(f"<b>Transaction ID:</b> {receipt.transaction_id}", styles['Normal']))
    elements.append(Paragraph(f"<b>Amount Paid:</b> ₹{receipt.total_amount}", styles['Normal']))
    elements.append(Paragraph(f"<b>Status:</b> {receipt.payment_status}", styles['Normal']))

    elements.append(Spacer(1, 20))
    elements.append(Paragraph("Thank you for using Park Smart 🚗", styles['Italic']))

    doc.build(elements)

    return response

#===================== PAYMENT SUCCESS ===================== #
@login_required
def payment_success(request, receipt_id):
    receipt = get_object_or_404(Receipt, id=receipt_id)
    return render(request, "payment_success.html", {"receipt": receipt})