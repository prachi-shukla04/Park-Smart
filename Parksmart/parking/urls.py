from django.urls import path
from . import views
from django.conf import settings
from django.conf.urls.static import static



urlpatterns = [
    path('', views.home, name='home'),

    # Authentication
    path('register/', views.register, name='register'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),

    # Dashboards
    path('provider/dashboard/', views.parking_provider, name='parking_provider'),
    path('user/dashboard/', views.user_dashboard, name='user_dashboard'),

    # Provider Features
    path('add_parking/', views.add_parking, name='add_parking'),
    path('my_parking/', views.my_parking, name='my_parking'),
    path('edit_parking/<int:id>/', views.edit_parking, name='edit_parking'),
    path('delete_parking/<int:id>/', views.delete_parking, name='delete_parking'),
    path('delete_image/<int:image_id>/', views.delete_image, name='delete_image'),
    path('provider/bookings/', views.provider_bookings, name='provider_bookings'),
    path('provider/earnings/', views.provider_earnings, name='provider_earnings'),
    path('provider/mark-exit/<int:booking_id>/', views.mark_vehicle_exit, name='mark_vehicle_exit'),
    path('provider/scan-qr/<int:booking_id>/', views.scan_qr, name='scan_qr'),
    # User Features
    path('book-parking/<int:parking_id>/', views.book_parking, name='book_parking'),
    path('my-bookings/', views.my_bookings, name='my_bookings'),
    path('cancel-booking/<int:booking_id>/', views.cancel_booking, name='cancel_booking'),
    path('view-slots/<int:parking_id>/', views.view_slots, name='view_slots'),
    path('extend-booking/<int:booking_id>/', views.extend_booking, name='extend_booking'),
    path('early-exit/<int:booking_id>/', views.early_exit, name='early_exit'),
    path('submit-rating/<int:booking_id>/', views.submit_rating, name='submit_rating'),

    # Favorites
    path('add-favorite/<int:parking_id>/', views.add_favorite, name='add_favorite'),
    path('remove-favorite/<int:parking_id>/', views.remove_favorite, name='remove_favorite'),

    # Payment System (Razorpay)
    path('payment/qr/<int:booking_id>/', views.payment_qr, name='payment_qr'),
    path('payment/verify/<int:booking_id>/', views.verify_payment, name='verify_payment'),
    path('payment/failed/<int:booking_id>/', views.payment_failed, name='payment_failed'),
    path('payment/extension/<int:booking_id>/', views.payment_extension, name='payment_extension'),
    path('payment/verify-extension/<int:booking_id>/', views.verify_extension, name='verify_extension'),
    path('payment/success/<int:receipt_id>/', views.payment_success, name='payment_success'),

    # Receipts
    path('receipt/<int:receipt_id>/', views.download_receipt, name='download_receipt'),
    path('receipt/generate/<int:booking_id>/', views.receipt_generation, name='receipt_generation'),    
]

urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)