from urllib import request

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from datetime import timedelta
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

# @login_required
def user_dashboard(request):
    if request.session.get('role') == 'user':
        auto_cancel_expired_bookings()

        query = request.GET.get('q', '').strip()

        # 🔹 Show ALL parkings
        parkings = Parking.objects.all()

        # 🔍 Search
        if query:
            parkings = parkings.filter(
                Q(parking_name__icontains=query) |
                Q(location__icontains=query)
            )

        # 🔹 Add total slots annotation (for smart UI)
        for p in parkings:
            total = (
                p.available_bike_slots +
                p.available_car_slots +
                p.available_suv_slots +
                p.available_truck_slots
            )
            p.total_available = total

            if total == 0:
                p.status = "FULL"
            elif total < 5:
                p.status = "ALMOST"
            else:
                p.status = "AVAILABLE"

        # 🔹 Smart sorting (best first)
        parkings = sorted(parkings, key=lambda x: x.total_available, reverse=True)

        user_bookings = Booking.objects.filter(user=request.user, is_active=True)
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

    return redirect('login')
# ===================== BOOK PARKING ===================== #
@login_required
def book_parking(request, parking_id):
    parking = get_object_or_404(Parking, id=parking_id)

    if Booking.objects.filter(user=request.user, parking=parking, is_active=True).exists():
        messages.error(request, "You already booked this parking ❌")
        return redirect('user_dashboard')

    if request.method == "POST":

        try:
            hours = int(request.POST.get('hours', 1))
            if hours <= 0:
                raise ValueError
        except:
            messages.error(request, "Invalid hours")
            return redirect('user_dashboard')

        vehicle_type = request.POST.get('vehicle_type')
        vehicle_number = request.POST.get('vehicle_number').upper()
        payment_timing = request.POST.get('payment_timing', 'pay_now')

        parking.reset_daily_counters()

        if vehicle_type == "Bike":
            if parking.available_bike_slots <= 0:
                return redirect('user_dashboard')
            price = parking.bike_price
            parking.available_bike_slots -= 1

        elif vehicle_type == "Car":
            if parking.available_car_slots <= 0:
                return redirect('user_dashboard')
            price = parking.car_price
            parking.available_car_slots -= 1

        elif vehicle_type == "SUV":
            if parking.available_suv_slots <= 0:
                return redirect('user_dashboard')
            price = parking.suv_price
            parking.available_suv_slots -= 1

        elif vehicle_type == "Truck":
            if parking.available_truck_slots <= 0:
                return redirect('user_dashboard')
            price = parking.truck_price
            parking.available_truck_slots -= 1

        else:
            messages.error(request, "Invalid vehicle type")
            return redirect('user_dashboard')

        is_free = False
        total_price = price * hours

        if vehicle_type == "Bike" and parking.used_bike_first_free_today < parking.bike_first_free_limit:
            is_free = True
            parking.used_bike_first_free_today += 1

        elif vehicle_type == "Car" and parking.used_car_first_free_today < parking.car_first_free_limit:
            is_free = True
            parking.used_car_first_free_today += 1

        elif vehicle_type == "SUV" and parking.used_suv_first_free_today < parking.suv_first_free_limit:
            is_free = True
            parking.used_suv_first_free_today += 1

        elif vehicle_type == "Truck" and parking.used_truck_first_free_today < parking.truck_first_free_limit:
            is_free = True
            parking.used_truck_first_free_today += 1

        if is_free:
            total_price = 0

        booking = Booking.objects.create(
            user=request.user,
            parking=parking,
            vehicle_type=vehicle_type,
            vehicle_number=vehicle_number,
            hours=hours,
            total_price=total_price,
            payment_timing=payment_timing,
            end_time=timezone.now() + timedelta(hours=hours)
        )

        parking.save()

        if is_free:
            messages.success(request, "🎉 FREE booking!")
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
    bookings = Booking.objects.filter(user=request.user)
    active_bookings = bookings.filter(
    is_active=True,
    end_time__gt=timezone.now()
)

    expired_bookings = bookings.filter(
        is_active=False
    ) | bookings.filter(end_time__lt=timezone.now())

    booking_ids = list(bookings.values_list('id', flat=True))
    receipts = Receipt.objects.filter(booking_id__in=booking_ids)

    receipts_dict = defaultdict(list)
    for receipt in receipts:
        receipts_dict[receipt.booking_id].append(receipt)
    for b in bookings:
        b.receipts = receipts_dict.get(b.id, [])    

    return render(request, 'my_booking.html', {
        'bookings': bookings,
        'active_bookings': active_bookings,
        'expired_bookings': expired_bookings,
        'receipts': receipts_dict
    })


from django.contrib import messages
from django.shortcuts import redirect, get_object_or_404

@login_required
def cancel_booking(request, booking_id):

    if request.method != "POST":
        return redirect("my_bookings")   # 🔒 block GET

    booking = get_object_or_404(
        Booking,
        id=booking_id,
        user=request.user
    )

    if not booking.is_active:
        messages.info(request, "Already cancelled or completed")
        return redirect("my_bookings")

    parking = booking.parking

    # 🔥 FREE SLOT
    if booking.vehicle_type == "Bike":
        parking.available_bike_slots += 1
    elif booking.vehicle_type == "Car":
        parking.available_car_slots += 1
    elif booking.vehicle_type == "SUV":
        parking.available_suv_slots += 1
    elif booking.vehicle_type == "Truck":
        parking.available_truck_slots += 1

    parking.save()

    # 🔥 CANCEL
    booking.is_active = False
    booking.save()

    messages.success(request, "Booking cancelled successfully ✅")

    return redirect("my_bookings")
# ===================== VIEW SLOTS ===================== #
@login_required
def view_slots(request, parking_id):
    parking = get_object_or_404(Parking, id=parking_id)
    return render(request, 'view_slots.html', {'parking': parking})


# ===================== AUTO CANCEL ===================== #
def auto_cancel_expired_bookings():
    expired_bookings = Booking.objects.filter(end_time__lt=timezone.now(), is_active=True)

    for booking in expired_bookings:
        parking = booking.parking

        # ✅ FIXED overflow
        if booking.vehicle_type == "Bike":
            parking.available_bike_slots = min(parking.available_bike_slots + 1, parking.bike_slots)
        elif booking.vehicle_type == "Car":
            parking.available_car_slots = min(parking.available_car_slots + 1, parking.car_slots)
        elif booking.vehicle_type == "SUV":
            parking.available_suv_slots = min(parking.available_suv_slots + 1, parking.suv_slots)
        elif booking.vehicle_type == "Truck":
            parking.available_truck_slots = min(parking.available_truck_slots + 1, parking.truck_slots)

        parking.save()
        booking.is_active = False
        booking.save()

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

@login_required
def early_exit(request, booking_id):
    booking = get_object_or_404(
        Booking, id=booking_id, user=request.user, is_active=True
    )
    parking = booking.parking

    # calculate usage
    used_time = (timezone.now() - booking.booking_time).total_seconds() / 3600
    used_hours = max(1, math.ceil(used_time))

    rate = parking.get_price(booking.vehicle_type)
    actual_price = used_hours * rate

    # ================= REFUND / EXTRA =================
    if actual_price < booking.total_price:
        refund = booking.total_price - actual_price
        messages.success(request, f"₹{refund} refunded successfully 💸")

    elif actual_price > booking.total_price:
        extra = actual_price - booking.total_price
        return redirect('payment_extension', booking_id=booking.id)

    else:
        messages.info(request, "No extra charge")

    # ================= FREE SLOT =================
    if booking.vehicle_type == "Bike":
        parking.available_bike_slots = min(
            parking.available_bike_slots + 1, parking.bike_slots
        )
    elif booking.vehicle_type == "Car":
        parking.available_car_slots = min(
            parking.available_car_slots + 1, parking.car_slots
        )
    elif booking.vehicle_type == "SUV":
        parking.available_suv_slots = min(
            parking.available_suv_slots + 1, parking.suv_slots
        )
    elif booking.vehicle_type == "Truck":
        parking.available_truck_slots = min(
            parking.available_truck_slots + 1, parking.truck_slots
        )

    parking.save()

    # ================= CLOSE BOOKING =================
    booking.total_price = actual_price
    booking.is_active = False
    booking.save()

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

        parking = Parking.objects.create(
            provider=request.user,
            parking_name=request.POST.get('parking_name'),
            location=request.POST.get('location'),
            latitude=latitude,
            longitude=longitude,

            bike_slots=int(request.POST.get('bike_slots') or 0),
            car_slots=int(request.POST.get('car_slots') or 0),
            suv_slots=int(request.POST.get('suv_slots') or 0),
            truck_slots=int(request.POST.get('truck_slots') or 0),

            bike_price=float(request.POST.get('bike_price') or 0),
            car_price=float(request.POST.get('car_price') or 0),
            suv_price=float(request.POST.get('suv_price') or 0),
            truck_price=float(request.POST.get('truck_price') or 0),

            # ✅ VEHICLE FREE LIMITS
            bike_first_free_limit=int(request.POST.get('bike_first_free_limit') or 0),
            car_first_free_limit=int(request.POST.get('car_first_free_limit') or 0),
            suv_first_free_limit=int(request.POST.get('suv_first_free_limit') or 0),
            truck_first_free_limit=int(request.POST.get('truck_first_free_limit') or 0),
        )

        # QR
        if request.FILES.get('qr_code_image'):
            parking.qr_code_image = request.FILES['qr_code_image']
            parking.save()

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

        # QR
        if request.FILES.get('qr_code_image'):
            parking.qr_code_image = request.FILES['qr_code_image']
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
    bookings = Booking.objects.filter(parking__provider=request.user, is_active=True)
    return render(request, 'provider_bookings.html', {'bookings': bookings})


# ===================== PROVIDER EARNINGS ===================== #
@login_required
def provider_earnings(request):
    bookings = Booking.objects.filter(parking__provider=request.user, is_active=True)
    total_earnings = bookings.aggregate(Sum('total_price'))['total_price__sum'] or 0

    return render(request, 'provider_earning.html', {
        'total_earnings': total_earnings,
        'bookings': bookings
    })


# ===================== PAYMENT SYSTEM ===================== #

@login_required
def payment_qr(request, booking_id):
    booking = get_object_or_404(Booking, id=booking_id, user=request.user)

    payment, created = Payment.objects.get_or_create(
        booking=booking,
        defaults={'total_amount': booking.total_price}
    )

    if payment.status == 'completed':
        messages.info(request, "This booking is already paid!")
        return redirect('my_bookings')

    if request.method == "POST":
        import time
        time.sleep(1)

        # Create transaction
        transaction = PaymentTransaction.objects.create(
            payment=payment,
            amount=payment.total_amount,
            transaction_type='deposit',
            status='success',
            transaction_id=f"QR-{uuid.uuid4().hex[:12].upper()}",
            payment_method='qr_code'
        )

        # Update payment
        payment.status = 'completed'
        payment.payment_method = 'qr_code'
        payment.save()

        # Generate receipt number (PDF optional)
        pdf_buffer, receipt_number = generate_receipt_pdf(booking, transaction)

        # ✅ CREATE RECEIPT (FIXED INDENTATION)
        receipt = Receipt.objects.create(
            booking=booking,
            receipt_number=receipt_number,
            total_amount=transaction.amount,
            amount=int(transaction.amount),
            payment_method='qr_code',
            transaction_id=transaction.transaction_id
        )

        messages.success(request, f"✅ Payment successful! ₹{payment.total_amount} paid via QR Code.")

        # ✅ REDIRECT WITH RECEIPT ID
        return redirect('payment_success', receipt_id=receipt.id)

    context = {
        'booking': booking,
        'payment': payment,
        'has_qr': bool(booking.parking.qr_code_image),
    }
    return render(request, 'payment_qr.html', context)
# ===================== EXTENSION PAYMENT ===================== #
@login_required
def payment_extension(request, booking_id):
    booking = get_object_or_404(
        Booking, id=booking_id, user=request.user
    )

    if request.method == "POST":
        hours = int(request.POST.get("extension_hours", 1))

        rate = booking.parking.get_price(booking.vehicle_type)
        total = rate * hours

        with transaction.atomic():

            booking.hours += hours
            booking.end_time += timedelta(hours=hours)
            booking.save()

            receipt_number = f"RCP-{uuid.uuid4().hex[:8]}"
            txn_id = f"EXT-{uuid.uuid4().hex[:12].upper()}"

            receipt = Receipt.objects.create(
                booking=booking,
                receipt_number=receipt_number,
                total_amount=total,
                amount=int(total),
                payment_method='qr_code',
                transaction_id=txn_id
            )

        return redirect("payment_success", receipt_id=receipt.id)

    return render(request, "payment_extension.html", {"booking": booking})
# ===================== DOWNLOAD RECEIPT ===================== #
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from django.http import HttpResponse
from django.shortcuts import get_object_or_404

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
def payment_success(request, receipt_id):
    receipt = get_object_or_404(Receipt, id=receipt_id)
    return render(request, "payment_success.html", {"receipt": receipt})