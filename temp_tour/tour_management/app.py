from flask import Flask, render_template, request, redirect, session, flash, send_file
import mongoengine as me
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, date
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors
from reportlab.platypus import TableStyle
from bson import ObjectId

import os
import qrcode
from io import BytesIO
import base64
import json

from flask import abort

app = Flask(__name__)
app.secret_key = "supersecretkey"

# ================= MONGODB CONFIG =================
me.connect(db="tour_bharat", host="localhost", port=27017)

GST_PERCENT = 5

# ================= HELPER =================

def get_or_404(model, **kwargs):
    obj = model.objects(**kwargs).first()
    if not obj:
        abort(404)
    return obj

def admin_required():
    """Returns redirect if not admin, else None."""
    if not session.get("admin"):
        return redirect("/admin/login")
    return None

# ================= MODELS =================

class User(me.Document):
    username = me.StringField(max_length=100, unique=True, required=True)
    password = me.StringField(max_length=200, required=True)
    meta = {"collection": "users"}

# ================= GLOBAL USER CONTEXT =================

@app.context_processor
def inject_user():
    user = None
    if "user_id" in session:
        try:
            user = User.objects(id=ObjectId(session["user_id"])).first()
        except:
            user = None
    return dict(user=user)

class Package(me.Document):
    title       = me.StringField(max_length=200)
    price       = me.IntField()
    days        = me.IntField()
    location    = me.StringField(max_length=200)
    image       = me.StringField(max_length=500)
    description = me.StringField()
    itinerary   = me.StringField()
    meta = {"collection": "packages"}


class RoomType(me.Document):
    package           = me.ReferenceField(Package)
    name              = me.StringField(max_length=100)
    one_night_price   = me.IntField()
    two_night_price   = me.IntField()
    three_night_price = me.IntField()
    meta = {"collection": "room_types"}


class Booking(me.Document):
    user             = me.ReferenceField(User, required=True)
    package          = me.ReferenceField(Package, required=True)
    room_type        = me.ReferenceField(RoomType)

    travel_date      = me.DateField()
    nights           = me.IntField()

    adults           = me.IntField()
    male_count       = me.IntField(default=0)
    female_count     = me.IntField(default=0)

    children_under8  = me.IntField(default=0)
    children_under18 = me.IntField(default=0)

    full_names       = me.StringField()
    mobile           = me.StringField(max_length=10)
    alternate_mobile = me.StringField(max_length=10)
    payment_method   = me.StringField(max_length=50)
    payment_proof    = me.StringField()

    base_price       = me.IntField()
    gst_amount       = me.IntField()
    total_price      = me.IntField()

    payment_status   = me.StringField(default="Pending")
    refund_requested = me.BooleanField(default=False)
    booking_date     = me.DateTimeField(default=datetime.utcnow)

    meta = {"collection": "bookings"}

class Discount(me.Document):
    package    = me.ReferenceField(Package)
    percentage = me.IntField()
    valid_from = me.DateField()
    valid_to   = me.DateField()
    meta = {"collection": "discounts"}

class Review(me.Document):
    user    = me.ReferenceField(User)
    package = me.ReferenceField(Package)
    rating  = me.IntField()
    comment = me.StringField()
    meta = {"collection": "reviews"}

class Destination(me.Document):
    name        = me.StringField()
    state       = me.StringField()
    description = me.StringField()
    meta = {"collection": "destinations"}


# ================= HOME =================

@app.route("/")
def home():
    packages = Package.objects.all()
    today    = date.today()

    active_discounts = Discount.objects.filter(
        valid_from__lte=today,
        valid_to__gte=today
    )
    discount_map = {str(d.package.id): d for d in active_discounts}

    return render_template("client/index.html", packages=packages,
                           today=today.isoformat(), discount_map=discount_map)


@app.route("/tours")
def tours():
    search    = request.args.get("search")
    min_price = request.args.get("min_price")
    max_price = request.args.get("max_price")

    query = Package.objects

    if search:
        query = query.filter(title__icontains=search)
    if min_price:
        query = query.filter(price__gte=int(min_price))
    if max_price:
        query = query.filter(price__lte=int(max_price))

    packages = query.all()

    # Build a dict: package_id -> active discount (if any)
    today = date.today()
    active_discounts = Discount.objects.filter(
        valid_from__lte=today,
        valid_to__gte=today
    )
    discount_map = {str(d.package.id): d for d in active_discounts}

    return render_template("client/tours.html", packages=packages, discount_map=discount_map)


@app.route("/package/<string:id>")
def package_detail(id):
    package    = get_or_404(Package, id=id)
    room_types = RoomType.objects.filter(package=package)
    today      = date.today().isoformat()
    reviews    = Review.objects.filter(package=package)

    # Fetch active discount for this package (valid today)
    discount = Discount.objects.filter(
        package=package,
        valid_from__lte=date.today(),
        valid_to__gte=date.today()
    ).first()

    itinerary_data = None
    try:
        itinerary_data = json.loads(package.itinerary)
    except:
        itinerary_data = None

    return render_template(
        "client/package_detail.html",
        package=package,
        room_types=room_types,
        today=today,
        itinerary_data=itinerary_data,
        reviews=reviews,
        discount=discount
    )


# ================= REVIEWS (Client) =================

@app.route("/review/<string:package_id>", methods=["POST"])
def add_review(package_id):
    if "user_id" not in session:
        return redirect("/auth")

    package = get_or_404(Package, id=package_id)
    user    = User.objects.get(id=ObjectId(session["user_id"]))

    Review(
        user=user,
        package=package,
        rating=int(request.form.get("rating", 5)),
        comment=request.form.get("comment", "")
    ).save()

    flash("Review submitted!", "success")
    return redirect(f"/package/{package_id}")


# ================= PROFILE =================

@app.route("/profile")
def profile():
    if "user_id" not in session:
        return redirect("/auth")

    user = get_or_404(User, id=session["user_id"])

    paid_bookings = Booking.objects.filter(user=user, payment_status="Paid")
    pending_bookings = Booking.objects.filter(user=user, payment_status__ne="Paid")

    return render_template(
        "client/profile.html",
        user=user,
        paid_bookings=paid_bookings,
        pending_bookings=pending_bookings
    )


# ================= AUTH =================

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        user = User(
            username=request.form["username"],
            password=generate_password_hash(request.form["password"])
        )
        user.save()
        flash("Registered Successfully", "success")
        return redirect("/auth")
    return render_template("client/register.html")


@app.route("/auth", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = User.objects(username=request.form["username"]).first()
        if user and check_password_hash(user.password, request.form["password"]):
            session["user_id"] = str(user.id)
            return redirect("/")
        flash("Invalid Credentials", "danger")
    return render_template("client/auth.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


# ================= ADMIN AUTH =================

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        if username == "admin" and password == "admin123":
            session["admin"] = True
            return redirect("/admin/dashboard")
        flash("Invalid Admin Credentials", "danger")
    return render_template("admin/login.html")


@app.route("/admin/logout")
def admin_logout():
    session.pop("admin", None)
    return redirect("/admin/login")


# ================= ADMIN DASHBOARD =================

@app.route("/admin/dashboard")
def admin_dashboard():
    redir = admin_required()
    if redir: return redir

    users    = User.objects.all()
    packages = Package.objects.all()
    bookings = Booking.objects.all()
    paid_bookings = Booking.objects.filter(payment_status="Paid")
    total_revenue = sum(b.total_price for b in paid_bookings)
    pending_count = Booking.objects.filter(payment_status="Verification Pending").count()
    refund_count  = Booking.objects.filter(payment_status="Refund Requested").count()

    return render_template(
        "admin/dashboard.html",
        users=users,
        packages=packages,
        bookings=bookings,
        total_revenue=total_revenue,
        pending_count=pending_count,
        refund_count=refund_count
    )


# ================= ADMIN — PACKAGES =================

@app.route("/admin/packages")
def admin_packages():
    redir = admin_required()
    if redir: return redir
    packages = Package.objects.all()
    return render_template("admin/packages.html", packages=packages)


@app.route("/admin/add_package", methods=["GET", "POST"])
def add_package():
    redir = admin_required()
    if redir: return redir

    if request.method == "POST":
        new_package = Package(
            title       = request.form["title"],
            price       = int(request.form["price"]),
            days        = int(request.form["days"]),
            location    = request.form["location"],
            image       = request.form["image"],
            description = request.form["description"],
            itinerary   = request.form["itinerary"]
        )
        new_package.save()

        # Save room types submitted with the form
        room_names  = request.form.getlist("room_name")
        one_night   = request.form.getlist("one_night_price")
        two_night   = request.form.getlist("two_night_price")
        three_night = request.form.getlist("three_night_price")

        for i in range(len(room_names)):
            if room_names[i].strip():
                RoomType(
                    package           = new_package,
                    name              = room_names[i],
                    one_night_price   = int(one_night[i] or 0),
                    two_night_price   = int(two_night[i] or 0),
                    three_night_price = int(three_night[i] or 0)
                ).save()

        flash("New Tour Package Added Successfully 🎉", "success")
        return redirect("/admin/packages")

    return render_template("admin/add_package.html")


@app.route("/admin/edit_package/<string:package_id>", methods=["GET", "POST"])
def edit_package(package_id):
    redir = admin_required()
    if redir: return redir

    package    = get_or_404(Package, id=package_id)
    room_types = RoomType.objects.filter(package=package)

    if request.method == "POST":
        package.title       = request.form["title"]
        package.price       = int(request.form["price"])
        package.days        = int(request.form["days"])
        package.location    = request.form["location"]
        package.image       = request.form["image"]
        package.description = request.form["description"]
        package.itinerary   = request.form["itinerary"]
        package.save()

        # Update existing room types
        for room in room_types:
            key = str(room.id)
            room.name              = request.form.get(f"room_name_{key}", room.name)
            room.one_night_price   = int(request.form.get(f"one_night_{key}", room.one_night_price) or 0)
            room.two_night_price   = int(request.form.get(f"two_night_{key}", room.two_night_price) or 0)
            room.three_night_price = int(request.form.get(f"three_night_{key}", room.three_night_price) or 0)
            room.save()

        flash("Package Updated Successfully ✅", "success")
        return redirect("/admin/packages")

    return render_template("admin/edit_package.html", package=package, room_types=room_types)


@app.route("/admin/delete_package/<string:package_id>")
def delete_package(package_id):
    redir = admin_required()
    if redir: return redir

    package = get_or_404(Package, id=package_id)
    RoomType.objects.filter(package=package).delete()
    package.delete()
    flash("Package Deleted Successfully", "warning")
    return redirect("/admin/packages")


# ================= ADMIN — USERS =================

@app.route("/admin/users")
def admin_users():
    redir = admin_required()
    if redir: return redir
    users = User.objects.all()
    # Attach booking counts
    user_data = []
    for u in users:
        count = Booking.objects.filter(user=u).count()
        user_data.append({"user": u, "booking_count": count})
    return render_template("admin/users.html", user_data=user_data)


# ================= ADMIN — BOOKINGS =================

@app.route("/admin/bookings")
def admin_bookings():
    redir = admin_required()
    if redir: return redir
    bookings = Booking.objects.all().order_by("-booking_date")
    return render_template("admin/bookings.html", bookings=bookings)


@app.route("/admin/approve/<string:booking_id>")
def approve_payment(booking_id):
    redir = admin_required()
    if redir: return redir

    booking = get_or_404(Booking, id=booking_id)

    if booking.payment_status == "Pending Approval":
        # Step 1→2: Admin approves booking, user can now pay
        booking.payment_status = "Approved"
        flash("Booking Approved ✅ — User can now proceed to payment.", "success")

    elif booking.payment_status == "Verification Pending":
        # Step 3→4: Admin verified the payment proof, mark as fully Paid
        booking.payment_status = "Paid"
        flash("Payment Verified & Marked as Paid ✅", "success")

    else:
        flash("No action needed for this booking status.", "info")

    booking.save()
    return redirect("/admin/bookings")


@app.route("/admin/approve_refund/<string:booking_id>")
def approve_refund(booking_id):
    redir = admin_required()
    if redir: return redir

    booking = get_or_404(Booking, id=booking_id)
    booking.payment_status = "Refunded"
    booking.save()
    flash("Refund Approved ✅", "success")
    return redirect("/admin/bookings")


# ================= ADMIN — DISCOUNTS =================

@app.route("/admin/discounts")
def admin_discounts():
    redir = admin_required()
    if redir: return redir
    discounts = Discount.objects.all()
    today = date.today().isoformat()
    return render_template("admin/discounts.html", discounts=discounts, today=today)


@app.route("/admin/add_discount", methods=["GET", "POST"])
def add_discount():
    redir = admin_required()
    if redir: return redir

    if request.method == "POST":
        Discount(
            package    = Package.objects.get(id=request.form["package_id"]),
            percentage = int(request.form["percentage"]),
            valid_from = request.form["valid_from"],
            valid_to   = request.form["valid_to"]
        ).save()
        flash("Discount Added Successfully ✅", "success")
        return redirect("/admin/discounts")

    packages = Package.objects.all()
    return render_template("admin/add_discount.html", packages=packages)


@app.route("/admin/delete_discount/<string:discount_id>")
def delete_discount(discount_id):
    redir = admin_required()
    if redir: return redir
    get_or_404(Discount, id=discount_id).delete()
    flash("Discount Deleted", "warning")
    return redirect("/admin/discounts")


# ================= ADMIN — DESTINATIONS =================

@app.route("/admin/destinations", methods=["GET", "POST"])
def admin_destinations():
    redir = admin_required()
    if redir: return redir

    if request.method == "POST":
        Destination(
            name        = request.form["name"],
            state       = request.form["state"],
            description = request.form["description"]
        ).save()
        flash("Destination Added ✅", "success")
        return redirect("/admin/destinations")

    destinations = Destination.objects.all()
    return render_template("admin/destinations.html", destinations=destinations)


@app.route("/admin/delete_destination/<string:dest_id>")
def delete_destination(dest_id):
    redir = admin_required()
    if redir: return redir
    get_or_404(Destination, id=dest_id).delete()
    flash("Destination Deleted", "warning")
    return redirect("/admin/destinations")


# ================= ADMIN — REVIEWS =================

@app.route("/admin/reviews")
def admin_reviews():
    redir = admin_required()
    if redir: return redir
    reviews = Review.objects.all()
    return render_template("admin/reviews.html", reviews=reviews)


@app.route("/admin/delete_review/<string:review_id>")
def delete_review(review_id):
    redir = admin_required()
    if redir: return redir
    get_or_404(Review, id=review_id).delete()
    flash("Review Deleted", "warning")
    return redirect("/admin/reviews")


# ================= BOOKING =================

@app.route("/book/<string:package_id>", methods=["POST"])
def book(package_id):
    if "user_id" not in session:
        return redirect("/auth")

    package = get_or_404(Package, id=package_id)
    room    = get_or_404(RoomType, id=request.form["room_type_id"])

    travel_date      = datetime.strptime(request.form["travel_date"], "%Y-%m-%d").date()
    adults           = int(request.form["adults"])
    children_under8  = int(request.form.get("children_under8", 0))
    children_under18 = int(request.form.get("children_under18", 0))
    male_count       = int(request.form.get("male_count", 0))
    female_count     = int(request.form.get("female_count", 0))
    full_names       = request.form.get("full_names", "")
    mobile           = request.form.get("mobile", "")
    alternate_mobile = request.form.get("alternate_mobile", "")
    payment_method   = request.form.get("payment_method", "UPI")

    # Room price based on package duration
    if package.days <= 1:
        price = room.one_night_price
    elif package.days == 2:
        price = room.two_night_price
    else:
        price = room.three_night_price

    # Pricing: children under 8 free, under 18 at 50%
    adult_total    = price * adults
    child_50_total = (price * 0.5) * children_under18
    subtotal       = adult_total + child_50_total
    gst            = subtotal * GST_PERCENT / 100
    total          = subtotal + gst

    user = User.objects.get(id=ObjectId(session["user_id"]))

    booking = Booking(
        user             = user,
        package          = package,
        room_type        = room,
        travel_date      = travel_date,
        nights           = package.days,
        adults           = adults,
        male_count       = male_count,
        female_count     = female_count,
        children_under8  = children_under8,
        children_under18 = children_under18,
        full_names       = full_names,
        mobile           = mobile,
        alternate_mobile = alternate_mobile,
        payment_method   = payment_method,
        base_price       = int(subtotal),
        gst_amount       = int(gst),
        total_price      = int(total),
        payment_status   = "Pending Approval"   # wait for admin to approve
    )
    booking.save()

    flash("✅ Booking submitted! You'll receive payment link once admin approves it.", "success")
    return redirect("/profile")


# ================= PAYMENT =================

@app.route("/upi_qr/<string:booking_id>")
def upi_qr(booking_id):
    if "user_id" not in session:
        return redirect("/auth")
    booking = get_or_404(Booking, id=booking_id)

    # Only allow access after admin approval
    if booking.payment_status not in ("Approved", "Verification Pending"):
        flash("Payment is not available yet. Please wait for admin approval.", "warning")
        return redirect("/profile")

    upi_id  = "raoaastha1805@okhdfcbank"
    name    = "Tour Bharat"
    amount  = booking.total_price
    upi_url = f"upi://pay?pa={upi_id}&pn={name}&am={amount}&cu=INR"

    qr     = qrcode.make(upi_url)
    buffer = BytesIO()
    qr.save(buffer, format="PNG")
    buffer.seek(0)
    img_base64 = base64.b64encode(buffer.getvalue()).decode()

    return render_template("client/upi_payment.html", booking=booking, qr_code=img_base64)



@app.route("/pay/<string:booking_id>")
def pay(booking_id):
    if "user_id" not in session:
        return redirect("/auth")

    booking = get_or_404(Booking, id=booking_id)

    if booking.payment_status == "Paid":
        flash("Already Paid ✅", "success")
        return redirect("/profile")

    return render_template("client/payment.html", booking=booking)


@app.route("/process_payment/<string:booking_id>", methods=["POST"])
def process_payment(booking_id):
    booking = get_or_404(Booking, id=booking_id)

    if request.form.get("upi_id"):
        booking.payment_method = "UPI ID"
    elif request.form.get("card_number"):
        booking.payment_method = "Card"
    elif request.form.get("bank"):
        booking.payment_method = "Net Banking"
    else:
        booking.payment_method = "Unknown"

    booking.payment_status = "Paid"
    booking.save()

    flash("Payment Successful 🎉", "success")
    return redirect("/profile")


@app.route("/upload_proof/<string:booking_id>", methods=["POST"])
def upload_proof(booking_id):
    booking = get_or_404(Booking, id=booking_id)

    file = request.files["screenshot"]
    os.makedirs("static/payment_proofs", exist_ok=True)

    filename = f"{str(booking.id)}_{file.filename}"
    filepath = os.path.join("static/payment_proofs", filename)
    file.save(filepath)

    booking.payment_proof  = filename
    booking.payment_method = "UPI"
    booking.payment_status = "Verification Pending"
    booking.save()

    flash("Screenshot Uploaded. Waiting for Admin Approval.", "success")
    return redirect("/profile")


@app.route("/request_refund/<string:booking_id>")
def request_refund(booking_id):
    if "user_id" not in session:
        return redirect("/auth")

    booking = get_or_404(Booking, id=booking_id)

    if str(booking.user.id) != session.get("user_id"):
        flash("Unauthorized action", "danger")
        return redirect("/profile")

    booking.refund_requested = True
    booking.payment_status   = "Refund Requested"
    booking.save()

    flash("Refund request submitted.", "info")
    return redirect("/profile")


@app.route("/cod/<string:booking_id>")
def cash_on_delivery(booking_id):
    booking = get_or_404(Booking, id=booking_id)
    booking.payment_method = "Cash on Arrival"
    booking.payment_status = "COD Pending"
    booking.save()
    flash("Booking Confirmed with Cash on Arrival", "success")
    return redirect("/profile")


# ================= INVOICE =================

@app.route("/download_invoice/<string:booking_id>")
def download_invoice(booking_id):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import cm
    from reportlab.pdfgen import canvas as rl_canvas

    booking   = get_or_404(Booking, id=booking_id)
    file_path = f"invoice_{str(booking.id)}.pdf"

    W, H = A4   # 595 x 842 pts
    c = rl_canvas.Canvas(file_path, pagesize=A4)

    # ── HEADER BAR ──────────────────────────────────────────
    c.setFillColor(colors.HexColor("#1a3a4a"))
    c.rect(0, H - 90, W, 90, fill=1, stroke=0)

    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 22)
    c.drawString(2*cm, H - 45, "Tour Bharat")
    c.setFont("Helvetica", 10)
    c.drawString(2*cm, H - 62, "Your Travel Partner Across India")

    # Invoice label on right
    c.setFont("Helvetica-Bold", 14)
    c.drawRightString(W - 2*cm, H - 40, "INVOICE")
    c.setFont("Helvetica", 9)
    c.drawRightString(W - 2*cm, H - 55, f"Invoice #: TBR-{str(booking.id)[-6:].upper()}")
    c.drawRightString(W - 2*cm, H - 68, f"Date: {booking.booking_date.strftime('%d %b %Y') if booking.booking_date else 'N/A'}")

    # ── CUSTOMER INFO ────────────────────────────────────────
    y = H - 120
    c.setFillColor(colors.HexColor("#f1f5f9"))
    c.rect(2*cm, y - 10, W - 4*cm, 60, fill=1, stroke=0)

    c.setFillColor(colors.HexColor("#1a3a4a"))
    c.setFont("Helvetica-Bold", 10)
    c.drawString(2.4*cm, y + 32, "Bill To:")
    c.setFont("Helvetica", 10)
    c.setFillColor(colors.black)
    c.drawString(2.4*cm, y + 18, f"Customer: {booking.user.username}")
    c.drawString(2.4*cm, y + 4,  f"Mobile:   {booking.mobile or 'N/A'}")
    if booking.alternate_mobile:
        c.drawString(2.4*cm, y - 10, f"Alt. Mobile: {booking.alternate_mobile}")

    # ── BOOKING DETAILS SECTION TITLE ───────────────────────
    y -= 30
    c.setFillColor(colors.HexColor("#1a3a4a"))
    c.setFont("Helvetica-Bold", 11)
    c.drawString(2*cm, y - 20, "Booking Details")
    c.setLineWidth(0.5)
    c.setStrokeColor(colors.HexColor("#1a3a4a"))
    c.line(2*cm, y - 24, W - 2*cm, y - 24)

    # Key-value rows
    y -= 42
    details = [
        ("Package",       booking.package.title),
        ("Travel Date",   str(booking.travel_date)),
        ("Duration",      f"{booking.nights} Night(s)"),
        ("Room Type",     booking.room_type.name if booking.room_type else "N/A"),
        ("Adults",        str(booking.adults)),
        ("Children < 8",  str(booking.children_under8 or 0)),
        ("Children < 18", str(booking.children_under18 or 0)),
        ("Passengers",    (booking.full_names or "N/A")),
        ("Payment Mode",  booking.payment_method or "N/A"),
    ]

    for i, (label, value) in enumerate(details):
        row_y = y - (i * 18)
        if i % 2 == 0:
            c.setFillColor(colors.HexColor("#f8fafc"))
            c.rect(2*cm, row_y - 5, W - 4*cm, 18, fill=1, stroke=0)
        c.setFillColor(colors.HexColor("#475569"))
        c.setFont("Helvetica-Bold", 9)
        c.drawString(2.4*cm, row_y + 4, label)
        c.setFont("Helvetica", 9)
        c.setFillColor(colors.black)
        c.drawString(9*cm, row_y + 4, value)

    # ── PRICE BREAKDOWN TABLE ────────────────────────────────
    y -= (len(details) * 18) + 30
    c.setFillColor(colors.HexColor("#1a3a4a"))
    c.setFont("Helvetica-Bold", 11)
    c.drawString(2*cm, y, "Price Breakdown")
    c.line(2*cm, y - 4, W - 2*cm, y - 4)

    # Table header
    y -= 22
    c.setFillColor(colors.HexColor("#1a3a4a"))
    c.rect(2*cm, y - 4, W - 4*cm, 18, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(2.4*cm,   y + 7, "Description")
    c.drawRightString(W - 2.4*cm, y + 7, "Amount (Rs.)")

    price_rows = [
        ("Base Fare (adults + children)", str(booking.base_price)),
        ("GST @ 5%",                      str(booking.gst_amount)),
    ]

    for i, (desc, amt) in enumerate(price_rows):
        row_y = y - 18 - (i * 18)
        if i % 2 == 0:
            c.setFillColor(colors.HexColor("#f1f5f9"))
            c.rect(2*cm, row_y - 4, W - 4*cm, 18, fill=1, stroke=0)
        c.setFillColor(colors.black)
        c.setFont("Helvetica", 9)
        c.drawString(2.4*cm, row_y + 7, desc)
        c.drawRightString(W - 2.4*cm, row_y + 7, f"Rs. {amt}")

    # Total row
    y -= 18 + (len(price_rows) * 18)
    c.setFillColor(colors.HexColor("#f59e0b"))
    c.rect(2*cm, y - 6, W - 4*cm, 22, fill=1, stroke=0)
    c.setFillColor(colors.HexColor("#1a3a4a"))
    c.setFont("Helvetica-Bold", 11)
    c.drawString(2.4*cm, y + 7, "TOTAL AMOUNT")
    c.drawRightString(W - 2.4*cm, y + 7, f"Rs. {booking.total_price}")

    # ── STATUS BADGE ─────────────────────────────────────────
    y -= 40
    c.setFillColor(colors.HexColor("#d1fae5"))
    c.roundRect(2*cm, y - 6, 120, 22, 4, fill=1, stroke=0)
    c.setFillColor(colors.HexColor("#065f46"))
    c.setFont("Helvetica-Bold", 9)
    c.drawString(2.4*cm, y + 7, f"Status: {booking.payment_status}")

    # ── FOOTER ───────────────────────────────────────────────
    c.setFillColor(colors.HexColor("#1a3a4a"))
    c.rect(0, 0, W, 40, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("Helvetica", 8)
    c.drawCentredString(W/2, 24, "Tour Bharat — Your Journey, Our Responsibility")
    c.drawCentredString(W/2, 12, "This is a computer-generated invoice. No signature required.")

    c.save()
    return send_file(file_path, as_attachment=True)



# ================= SEED DATA =================

def seed_data():
    if Package.objects.count() > 0:
        return

    tours = [
        ("Rann Utsav Special",      "ranUtsav.jpg"),
        ("Manali Snow Adventure",   "manali.jpg"),
        ("Goa Beach Party",         "goa.jpg"),
        ("Kerala Special Tour",     "kerala.jpg"),
        ("Kashmir Heaven",          "kashmir.jpg"),
        ("Leh Ladakh Adventure",    "ladakh.jpg"),
        ("Rajasthan Royal Tour",    "rajasthan.jpg"),
        ("Andaman Island Trip",     "andaman.jpg"),
        ("Sikkim Nature Tour",      "sikkim.jpg"),
        ("Udaipur Romantic Escape", "udaipur.jpg"),
        ("Shimla Holiday",          "shimla.jpg"),
        ("Ooty Hill Station",       "ooty.jpg")
    ]

    for title, image_name in tours:
        pkg = Package(
            title       = title,
            price       = 23975,
            days        = 5,
            location    = "India",
            image       = image_name,
            description = "Luxury stay with cultural programs.",
            itinerary   = "Day 1: Arrival\nDay 2: Sightseeing\nDay 3: Cultural Program"
        )
        pkg.save()

        RoomType(
            package           = pkg,
            name              = "Super Premium Tent",
            one_night_price   = 9900,
            two_night_price   = 19000,
            three_night_price = 27500
        ).save()

        RoomType(
            package           = pkg,
            name              = "Premium Tent",
            one_night_price   = 8900,
            two_night_price   = 17000,
            three_night_price = 25000
        ).save()


# ================= UNIQUE ITINERARIES MAP =================

PACKAGE_ITINERARIES = {
    "Rann Utsav Special": [
        "Arrive at Bhuj by flight or train. Transfer to the Rann resort. Check-in and freshen up. Evening welcome with cultural folk music and dinner under the stars.",
        "After breakfast, explore the white salt desert on a guided jeep safari. Visit artisan Kutchi villages and shop for handcrafted embroidery. Watch the mesmerising sunset.",
        "Full-day visit to Dholavira — the ancient Harappan UNESCO heritage site. Walk the ruins and museum. Evening camel ride along the Rann edge with bonfire and folk songs.",
        "Visit Bhuj city — Aina Mahal palace, Prag Mahal, and the local textile market. Afternoon leisure or optional spa. Cultural folk dance performance in the evening.",
        "Sunrise photography at the white Rann. Breakfast at resort. Check-out and transfer to Bhuj for your onward journey. Farewell with local Kutchi snacks."
    ],
    "Manali Snow Adventure": [
        "Arrive at Manali. Check into a mountain-view hotel. Evening stroll along Mall Road and Manu temple. Welcome dinner with traditional Himachali cuisine.",
        "Drive to Rohtang Pass (or Solang Valley if closed). Snow activities — skiing, snowboarding, and snow sledging all day. Return to hotel by evening.",
        "Visit Hadimba Devi temple, Vashisht hot springs, and Tibetan monastery. Afternoon river rafting on the Beas River. Evening bonfire at camp.",
        "Full-day excursion to Naggar Castle and vineyard village. Optional trek to Jana Waterfall. Evening leisure in the Old Manali market for local shopping.",
        "Morning yoga session by the river. Check-out after breakfast. Drive through the scenic Kullu Valley to Bhunter airport or Chandigarh for your onward journey."
    ],
    "Goa Beach Party": [
        "Arrive at Goa airport. Transfer to beach resort in North Goa. Check-in and relax. Sunset at Calangute or Baga beach — drinks and fresh seafood dinner at a shack.",
        "Morning visit to Fort Aguada and Chapora Fort (Dil Chahta Hai fame). Afternoon beach hopping — Anjuna, Vagator, and Ashwem beaches. Evening pub crawl in Anjuna.",
        "Guided boat trip with dolphin spotting, snorkeling at Grand Island, and BBQ lunch on the boat. Evening at Arpora Saturday Night Market for shopping.",
        "Day trip to South Goa — Colva, Benaulim, and the stunning Palolem beach. Clean waters and hammock relaxation by the sea. Fresh seafood dinner.",
        "Morning beach walk and souvenir shopping at Mapusa market. Check-out after brunch. Transfer to Goa airport or train station. Departure with beach memories."
    ],
    "Kerala Special Tour": [
        "Arrive at Kochi airport. Visit Fort Kochi — Chinese fishing nets, St. Francis Church, and Jew Town spice market. Evening Kathakali dance performance.",
        "Morning Ayurvedic wellness session. Drive to Munnar (3 hrs). Walk through tea plantations and visit the tea museum. Check-in at a tea estate resort.",
        "Drive to Alleppey (Alappuzha). Board a private houseboat. Cruise through scenic backwaters, visit coir villages, and enjoy Kerala fish curry lunch on board.",
        "Morning at Alleppey local market. Drive to Kovalam beach. Sunset at the Lighthouse beach. Ayurvedic massage at a beach resort. Seafood dinner.",
        "Morning beach yoga. Explore Trivandrum — Padmanabhaswamy temple exterior and the state museum. Afternoon departure from Trivandrum international airport."
    ],
    "Kashmir Heaven": [
        "Arrive at Srinagar airport. Transfer to a traditional Shikara houseboat on Dal Lake. Shikara ride at sunset through the lake. Dinner on the houseboat.",
        "Morning Shikara ride to the floating vegetable market. Drive to Gulmarg. Gondola cable car to Apharwat Peak (4,200 m). Snow activities and Himalayan panoramas.",
        "Drive to Sonmarg — meadow of gold. Horse ride to Thajiwas Glacier. Lunch amidst the glacier. Return to Srinagar. Evening at Lal Chowk market.",
        "Day excursion to Pahalgam via Lidder River Valley. Visit Betaab Valley and Aru Valley. Horse ride through alpine meadows. Evening at Pahalgam local market.",
        "Morning visit to Shalimar Bagh and Nishat Bagh Mughal gardens by Dal Lake. Shopping for Pashmina shawls and Kashmiri dry fruits. Afternoon departure from Srinagar."
    ],
    "Leh Ladakh Adventure": [
        "Arrive at Leh airport (3,500 m). Full rest day for acclimatisation — absolutely crucial. Short walk to Leh palace and the local market. Light dinner.",
        "Drive to Nubra Valley via Khardung La (5,359 m — world's highest motorable road). Double-hump Bactrian camel ride at Hunder Sand Dunes. Night camp in Nubra.",
        "Drive to Turtuk village — last accessible Indian village near Pakistan border. Return to Leh via Diskit monastery and the spectacular wind-eroded landscape.",
        "Drive to Pangong Tso Lake (4,350 m) — the iconic blue lake from the film 3 Idiots. Camp by the lake overnight. Breathtaking stargazing at night.",
        "Sunrise photography at Pangong Lake. Drive back to Leh. Visit Hemis monastery, Thiksey monastery, and Shey Palace. Evening departure from Leh airport."
    ],
    "Rajasthan Royal Tour": [
        "Arrive at Jaipur — the Pink City. Visit Hawa Mahal and Jantar Mantar. Evening at Johari Bazaar for jewellery. Rooftop haveli dinner.",
        "Morning Amer Fort jeep or elephant ride. City Palace museum visit. Drive to Jodhpur (Blue City). Heritage hotel check-in with Mehrangarh Fort views.",
        "Explore Jodhpur — Mehrangarh Fort, Jaswant Thada, and blue old city lanes. Drive to Jaisalmer. Evening at Sam Sand Dunes — camel safari and desert sunset.",
        "Jaisalmer Golden Fort, Patwon ki Haveli, and Gadisar Lake. Drive to Udaipur. Check-in with lake view. Boat ride on Lake Pichola with City Palace lit up at night.",
        "Morning visit to Saheliyon ki Bari garden and Jagdish Temple. Shopping for Mewar miniature paintings and silver. Departure from Udaipur airport."
    ],
    "Andaman Island Trip": [
        "Arrive at Port Blair. Visit the historic Cellular Jail. Evening Light and Sound show on the freedom struggle. Dinner at a harbour seafood restaurant.",
        "Ferry to Havelock Island. Check-in at a beach resort. Afternoon at Radhanagar Beach — repeatedly voted Asia's best beach. Sunset by the turquoise sea.",
        "Scuba diving or snorkeling at Elephant Beach reef. Glass-bottom boat for non-swimmers. Afternoon at Kalapathar beach. Beach bonfire dinner at night.",
        "Ferry to Neil Island. Visit the Natural Bridge rock formation. Cycling across the peaceful island. Sunset at Natural Bridge. Night camp by the beach.",
        "Return to Port Blair. Visit Corbyn's Cove beach, Samudrika marine museum, and the local shell market. Souvenirs. Evening departure from Port Blair airport."
    ],
    "Sikkim Nature Tour": [
        "Arrive at Bagdogra / NJP. Drive to Gangtok (4 hrs) through the Teesta valley. Check in. Evening at Mall Road — try local momos, thukpa, and Sikkim culture.",
        "Day excursion to Tsomgo (Changu) Lake (3,753 m) and Baba Mandir. Snow and mountain views. Optional yak ride at the lake. Return to Gangtok.",
        "Drive to Pelling. En route visit Rumtek monastery — the main seat of the Kagyupa Buddhist sect. Check-in at Pelling with Kangchenjunga views.",
        "Pelling sightseeing — Rabdentse ruins, wish-fulfilling Khecheopalri lake, and Pemayangtse monastery. Visit Singshore bridge (second highest in Asia).",
        "Drive back to Bagdogra via Jorethang. Optional stop at Namchi (Siddheshwar Dham). Departure from Bagdogra airport with mountain memories."
    ],
    "Udaipur Romantic Escape": [
        "Arrive at Udaipur — City of Lakes. Check-in at a heritage haveli hotel. Sunset boat cruise on Lake Pichola with views of the City Palace. Candlelit lakeside dinner.",
        "Visit City Palace museum, Jagdish Temple, and old city havelis. Afternoon Rajasthani cooking class — dal bati churma. Evening at Fateh Sagar Lake.",
        "Day trip to Kumbhalgarh Fort (Great Wall of India) and Ranakpur Jain temples (1,444 carved pillars). Return to Udaipur. Rooftop sunset drink.",
        "Leisure morning at a rooftop café with lake views. Rajasthani puppet show and folk dance. Shopping — Mewar paintings, leheriya textiles, and silver jewellery.",
        "Morning at Saheliyon ki Bari garden and Bagore ki Haveli museum. Afternoon spa. Check-out and transfer to Udaipur airport for departure."
    ],
    "Shimla Holiday": [
        "Arrive at Shimla via bus from Chandigarh or the iconic Kalka-Shimla toy train. Check-in at a colonial hotel. Mall Road walk and Christ Church. Café dinner.",
        "Visit Jakhu Hill temple (Lord Hanuman) with panoramic Shimla views. Explore Gorton Castle and Gaiety Theatre. Lunch at the historic Indian Coffee House.",
        "Day excursion to Kufri — snow activities and horse riding. Visit the Himalayan Nature Park with rare wildlife. Return to Shimla for the local market.",
        "Drive to Chail — world's highest cricket ground. Visit Chail Wildlife Sanctuary and the royal Chail Palace. Picnic lunch in the pine forest.",
        "Morning visit to the Viceregal Lodge (IIAS) — stunning Elizabethan architecture with beautiful gardens. Toy train back to Kalka or drive to Chandigarh for departure."
    ],
    "Ooty Hill Station": [
        "Arrive at Coimbatore. Drive to Ooty (2 hrs) via 36 dramatic hairpin bends in the Nilgiris. Check-in. Visit Government Rose Garden and Botanical Garden.",
        "Ride the UNESCO Nilgiri Mountain Railway toy train from Ooty to Coonoor and back — through 16 tunnels and lush tea estates. Visit Sims Park in Coonoor.",
        "Drive to Doddabetta Peak (2,637 m — highest in Nilgiris). Visit a Toda tribal village with unique barrel-shaped huts. Evening boating at Ooty Lake.",
        "Day trip to Mudumalai National Park — jeep safari to spot wild elephants, gaur, spotted deer, and possibly leopards. Nature walk on a spice estate.",
        "Morning visit to a Nilgiri tea and chocolate factory. Shop for fresh teas, homemade chocolates, and eucalyptus oil at Ooty market. Drive to Coimbatore for departure."
    ],
}


@app.route("/admin/fix_itineraries")
def admin_fix_itineraries():
    redir = admin_required()
    if redir: return redir
    updated = 0
    for package in Package.objects.all():
        lines = PACKAGE_ITINERARIES.get(package.title)
        if lines:
            package.itinerary = "\n".join(lines)
            package.save()
            updated += 1
    flash(f"\u2705 Updated itineraries for {updated} packages!", "success")
    return redirect("/admin/packages")


# ================= RUN =================

if __name__ == "__main__":
    seed_data()
    app.run(debug=True)