from datetime import timedelta
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Q
from django.contrib import messages
from django.utils import timezone

from .models import Parking, Booking, UserProfile


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
            profile = UserProfile.objects.get(user=user)

            if profile.role == role:
                login(request, user)
                request.session['role'] = profile.role

                if role == 'provider':
                    return redirect('parking_provider')
                else:
                    return redirect('user_dashboard')
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
    if request.session.get('role') == 'user':
        auto_cancel_expired_bookings()

        parkings = Parking.objects.all()
        user_bookings = Booking.objects.filter(user=request.user)
        booked_parking_ids = user_bookings.values_list('parking_id', flat=True)

        # 🔍 SEARCH
        query = request.GET.get('q')
        if query:
            parkings = parkings.filter(
                Q(parking_name__icontains=query) |
                Q(location__icontains=query)
            )

        # 🚗 VEHICLE FILTER
        vehicle = request.GET.get('vehicle')

        if vehicle == "Bike":
            parkings = parkings.filter(available_bike_slots__gt=0)
        elif vehicle == "Car":
            parkings = parkings.filter(available_car_slots__gt=0)
        elif vehicle == "SUV":
            parkings = parkings.filter(available_suv_slots__gt=0)
        elif vehicle == "Truck":
            parkings = parkings.filter(available_truck_slots__gt=0)


        return render(request, 'user_dashboard.html', {
            'parkings': parkings,
            'booked_parking_ids': booked_parking_ids
        })
    return redirect('login')


# ===================== BOOK PARKING ===================== #
@login_required
def book_parking(request, parking_id):
    parking = get_object_or_404(Parking, id=parking_id)

    # prevent duplicate booking
    if Booking.objects.filter(user=request.user, parking=parking).exists():
        messages.error(request, "You already booked this parking ❌")
        return redirect('user_dashboard')

    if request.method == "POST":
        vehicle_type = request.POST.get('vehicle_type')
        vehicle_number = request.POST.get('vehicle_number')
        hours = int(request.POST.get('hours'))

        # VEHICLE LOGIC
        if vehicle_type == "Bike":
            if parking.available_bike_slots <= 0:
                messages.error(request, "No Bike slots ❌")
                return redirect('user_dashboard')
            price = parking.bike_price
            parking.available_bike_slots -= 1

        elif vehicle_type == "Car":
            if parking.available_car_slots <= 0:
                messages.error(request, "No Car slots ❌")
                return redirect('user_dashboard')
            price = parking.car_price
            parking.available_car_slots -= 1

        elif vehicle_type == "SUV":
            if parking.available_suv_slots <= 0:
                messages.error(request, "No SUV slots ❌")
                return redirect('user_dashboard')
            price = parking.suv_price
            parking.available_suv_slots -= 1

        elif vehicle_type == "Truck":
            if parking.available_truck_slots <= 0:
                messages.error(request, "No Truck slots ❌")
                return redirect('user_dashboard')
            price = parking.truck_price
            parking.available_truck_slots -= 1

        total_price = price * hours

        booking = Booking.objects.create(
            user=request.user,
            parking=parking,
            vehicle_type=vehicle_type,
            vehicle_number=vehicle_number,
            hours=hours,
            total_price=total_price
        )

        # set end time
        booking.end_time = timezone.now() + timedelta(hours=hours)
        booking.save()

        parking.save()

        messages.success(request, "Booking Successful 🎉")
        return redirect('user_dashboard')

    return render(request, 'book_parking.html', {'parking': parking})


# ===================== MY BOOKINGS ===================== #
@login_required
def my_bookings(request):
    bookings = Booking.objects.filter(user=request.user)
    active = bookings.filter(end_time__gt=timezone.now())
    expired = bookings.filter(end_time__lt=timezone.now())
    return render(request, 'my_booking.html', 
     {'bookings': bookings, 
      'active': active, 
      'expired': expired})


# ===================== CANCEL BOOKING ===================== #
@login_required
def cancel_booking(request, booking_id):
    booking = get_object_or_404(Booking, id=booking_id, user=request.user)
    parking = booking.parking

    if booking.vehicle_type == "Bike":
        parking.available_bike_slots += 1
    elif booking.vehicle_type == "Car":
        parking.available_car_slots += 1
    elif booking.vehicle_type == "SUV":
        parking.available_suv_slots += 1
    elif booking.vehicle_type == "Truck":
        parking.available_truck_slots += 1

    parking.save()
    booking.delete()

    return redirect('my_bookings')


# ===================== AUTO CANCEL ===================== #
def auto_cancel_expired_bookings():
    expired_bookings = Booking.objects.filter(end_time__lt=timezone.now())

    for booking in expired_bookings:
        parking = booking.parking

        if booking.vehicle_type == "Bike":
            parking.available_bike_slots += 1
        elif booking.vehicle_type == "Car":
            parking.available_car_slots += 1
        elif booking.vehicle_type == "SUV":
            parking.available_suv_slots += 1
        elif booking.vehicle_type == "Truck":
            parking.available_truck_slots += 1

        parking.save()
        booking.delete()


# ===================== VIEW SLOTS ===================== #
@login_required
def view_slots(request, parking_id):
    parking = get_object_or_404(Parking, id=parking_id)
    return render(request, 'view_slots.html', {'parking': parking})


# ===================== EXTEND BOOKING ===================== #
@login_required
def extend_booking(request, booking_id):
    booking = get_object_or_404(Booking, id=booking_id, user=request.user)

    booking.hours += 1

    # dynamic price
    if booking.vehicle_type == "Bike":
        booking.total_price += booking.parking.bike_price
    elif booking.vehicle_type == "Car":
        booking.total_price += booking.parking.car_price
    elif booking.vehicle_type == "SUV":
        booking.total_price += booking.parking.suv_price
    elif booking.vehicle_type == "Truck":
        booking.total_price += booking.parking.truck_price

    booking.end_time += timedelta(hours=1)
    booking.save()

    return redirect('my_bookings')
#==========Early exit============================
@login_required
def early_exit(request, booking_id):
    booking = get_object_or_404(Booking, id=booking_id, user=request.user)
    parking = booking.parking

    # Calculate used time
    from django.utils import timezone
    used_time = (timezone.now() - booking.booking_time).total_seconds() / 3600

    # Minimum 1 hour charge
    used_hours = max(1, int(used_time))

    # Get price dynamically
    if booking.vehicle_type == "Bike":
        price_per_hour = parking.bike_price
        parking.available_bike_slots += 1
    elif booking.vehicle_type == "Car":
        price_per_hour = parking.car_price
        parking.available_car_slots += 1
    elif booking.vehicle_type == "SUV":
        price_per_hour = parking.suv_price
        parking.available_suv_slots += 1
    elif booking.vehicle_type == "Truck":
        price_per_hour = parking.truck_price
        parking.available_truck_slots += 1

    # Update price (optional logic)
    booking.total_price = used_hours * price_per_hour

    parking.save()
    booking.delete()

    messages.success(request, f"Exited early. Charged for {used_hours} hour(s) ✅")

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
        Parking.objects.create(
            provider=request.user,
            parking_name=request.POST.get('parking_name'),
            location=request.POST.get('location'),

            bike_slots=request.POST.get('bike_slots'),
            car_slots=request.POST.get('car_slots'),
            suv_slots=request.POST.get('suv_slots'),
            truck_slots=request.POST.get('truck_slots'),

            bike_price=request.POST.get('bike_price'),
            car_price=request.POST.get('car_price'),
            suv_price=request.POST.get('suv_price'),
            truck_price=request.POST.get('truck_price'),

            image=request.FILES.get('image')
        )
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

        parking.bike_slots = int(request.POST.get('bike_slots'))
        parking.car_slots = int(request.POST.get('car_slots'))
        parking.suv_slots = int(request.POST.get('suv_slots'))
        parking.truck_slots = int(request.POST.get('truck_slots'))

        parking.bike_price = float(request.POST.get('bike_price'))
        parking.car_price = float(request.POST.get('car_price'))
        parking.suv_price = float(request.POST.get('suv_price'))
        parking.truck_price = float(request.POST.get('truck_price'))

        parking.available_bike_slots = min(parking.available_bike_slots, parking.bike_slots)
        parking.available_car_slots = min(parking.available_car_slots, parking.car_slots)
        parking.available_suv_slots = min(parking.available_suv_slots, parking.suv_slots)
        parking.available_truck_slots = min(parking.available_truck_slots, parking.truck_slots)

        if request.FILES.get('image'):
            parking.image = request.FILES.get('image')

        parking.save()
        return redirect('my_parking')

    return render(request, 'edit_parking.html', {'parking': parking})


# ===================== DELETE PARKING ===================== #
@login_required
def delete_parking(request, id):
    parking = get_object_or_404(Parking, id=id, provider=request.user)
    parking.delete()
    return redirect('my_parking')


# ===================== PROVIDER BOOKINGS ===================== #
@login_required
def provider_bookings(request):
    bookings = Booking.objects.filter(parking__provider=request.user)
    return render(request, 'provider_bookings.html', {'bookings': bookings})


# ===================== PROVIDER EARNINGS ===================== #
@login_required
def provider_earnings(request):
    bookings = Booking.objects.filter(parking__provider=request.user)
    total_earnings = bookings.aggregate(Sum('total_price'))['total_price__sum'] or 0

    return render(request, 'provider_earning.html', {
        'total_earnings': total_earnings,
        'bookings': bookings
    })