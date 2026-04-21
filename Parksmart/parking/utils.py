from io import BytesIO
from reportlab.pdfgen import canvas

def generate_receipt_pdf(booking, transaction):
    buffer = BytesIO()

    p = canvas.Canvas(buffer)

    p.drawString(100, 800, "Park Smart Receipt")
    p.drawString(100, 780, f"Booking Code: {booking.booking_code}")
    p.drawString(100, 760, f"Parking: {booking.parking.parking_name}")
    p.drawString(100, 740, f"Vehicle: {booking.vehicle_type}")
    p.drawString(100, 720, f"Amount: ₹{transaction.amount}")

    p.save()

    buffer.seek(0)

    receipt_number = f"RCP-{booking.id}"

    return buffer, receipt_number