from flask import Flask, render_template, request, redirect, session, flash, send_file, url_for
from werkzeug.utils import secure_filename
import mongoengine as me
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, date
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors
from reportlab.platypus import TableStyle
from bson import ObjectId  

# import razorpay

import os
import qrcode
from io import BytesIO
import base64
import json

app = Flask(__name__)
app.secret_key = "supersecretkey"

# ================= ELITE SERVICES =================
@app.route("/luxe_stay")
def luxe_stay():
    return render_template("client/services/luxe_stay.html")

@app.route("/fine_dining")
def fine_dining():
    return render_template("client/services/fine_dining.html")

@app.route("/private_cab")
def private_cab():
    return render_template("client/services/private_cab.html")

@app.route("/guides")
def guides():
    return render_template("client/services/guides.html")

# ================= MONGODB CONFIG =================
me.connect(db="tour_bharat", host="localhost", port=27017)

GST_PERCENT = 18
UPLOAD_FOLDER = 'static/images'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# ================= HELPER =================

from flask import abort

def get_or_404(model, **kwargs):
    obj = model.objects(**kwargs).first()
    if not obj:
        abort(404)
    return obj

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

    # Elite Add-ons
    add_luxe_stay    = me.BooleanField(default=False)
    add_fine_dining  = me.BooleanField(default=False)
    add_private_cab  = me.BooleanField(default=False)
    add_guides       = me.BooleanField(default=False)
    services_total   = me.IntField(default=0)

    meta = {"collection": "bookings"}

class Discount(me.Document):
    package = me.ReferenceField(Package)
    percentage = me.IntField()
    valid_from = me.DateField()
    valid_to = me.DateField()

    meta = {"collection": "discounts"}
 
class Review(me.Document):
    user = me.ReferenceField(User)
    package = me.ReferenceField(Package)
    rating = me.IntField()
    comment = me.StringField()

    meta = {"collection": "reviews"}
    
class Destination(me.Document):
    name = me.StringField()
    state = me.StringField()
    description = me.StringField()

    meta = {"collection": "destinations"}
    
    
   
@app.route("/admin/add_discount", methods=["GET", "POST"])
def add_discount():
    if not session.get("admin"):
        return redirect("/admin/login")

    if request.method == "POST":
        Discount(
            package=Package.objects.get(id=request.form["package_id"]),
            percentage=int(request.form["percentage"]),
            valid_from=request.form["valid_from"],
            valid_to=request.form["valid_to"]
        ).save()

        flash("Discount Added Successfully", "success")
        return redirect("/admin/dashboard")

    packages = Package.objects.all()
    return render_template("admin/add_discount.html", packages=packages)

@app.route("/admin/reviews")
def admin_reviews():
    if not session.get("admin"):
        return redirect("/admin/login")

    reviews = Review.objects.all()
    return render_template("admin/reviews.html", reviews=reviews)

# ================= HOME =================

@app.route("/")
def index():
    packages = Package.objects().limit(6)
    stats = {
        "tours": Package.objects.count(),
        "users": User.objects.count(),
        "locations": len(set(Package.objects.only("location").values_list("location")))
    }
    return render_template("client/index.html", packages=packages, stats=stats)


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
    
    # AJAX support: if request is JSON or has ajax=1 param, return partial data
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.args.get('ajax'):
        packages_list = []
        for pkg in packages:
            packages_list.append({
                "id": str(pkg.id),
                "title": pkg.title,
                "price": pkg.price,
                "days": pkg.days,
                "location": pkg.location,
                "image": pkg.image
            })
        return {"packages": packages_list}

    return render_template("client/tours.html", packages=packages)


@app.route("/package/<string:id>")
def package_detail(id):
    package    = get_or_404(Package, id=id)
    room_types = RoomType.objects.filter(package=package)
    reviews    = Review.objects.filter(package=package).order_by('-id')
    today      = date.today().isoformat()

    itinerary_data = None
    try:
        itinerary_data = json.loads(package.itinerary)
    except:
        itinerary_data = None

    return render_template(
        "client/package_detail.html",
        package=package,
        room_types=room_types,
        reviews=reviews,
        today=today,
        itinerary_data=itinerary_data
    )


@app.route("/add_review/<string:package_id>", methods=["POST"])
def add_review(package_id):
    if "user_id" not in session:
        flash("Please login to share your experience", "warning")
        return redirect("/auth")

    package = get_or_404(Package, id=package_id)
    user = User.objects.get(id=ObjectId(session["user_id"]))

    Review(
        user=user,
        package=package,
        rating=int(request.form.get("rating", 5)),
        comment=request.form.get("comment")
    ).save()

    flash("Feedback Narrative Recorded. Thank you for sharing your journey! ✨", "success")
    return redirect(f"/package/{package_id}")


# ================= PROFILE =================

# @app.route("/profile")
# def profile():
#     if "user_id" not in session:
#         return redirect("/auth")

#     # user = get_or_404(User, id=session["user_id"])
#     user = get_or_404(User, id=ObjectId(session["user_id"]))

#     paid_bookings = Booking.objects.filter(
#     user=user,
#     payment_status="Paid"
# )

#     pending_bookings = Booking.objects.filter(
#     user=user,
#     payment_status__ne="Paid"
# )
#     return render_template(
#         "client/profile.html",
#         user=user,
#         paid_bookings=paid_bookings,
#         pending_bookings=pending_bookings
#     )
@app.route("/profile")
def profile():
    if "user_id" not in session:
        return redirect("/auth")

    user = get_or_404(User, id=session["user_id"])

    paid_bookings = Booking.objects.filter(
        user=user,
        payment_status="Paid"
    )

    pending_bookings = Booking.objects.filter(
        user=user,
        payment_status__ne="Paid"
    )

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
        username = request.form.get("username")
        password = request.form.get("password")
        
        if User.objects(username=username).first():
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return {"status": "error", "message": "User already exists!"}, 400
            flash("User already exists", "danger")
            return redirect("/register")

        User(
            username=username,
            password=generate_password_hash(password)
        ).save()
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return {"status": "success", "message": "Registered Successfully! Redirecting...", "redirect": "/auth"}
            
        flash("Registered Successfully", "success")
        return redirect("/auth")
        
    return render_template("client/register.html")


@app.route("/auth", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        
        user = User.objects(username=username).first()
        if user and check_password_hash(user.password, password):
            session["user_id"] = str(user.id)
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return {"status": "success", "redirect": "/"}
            return redirect("/")
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return {"status": "error", "message": "Invalid Credentials"}, 401
        flash("Invalid Credentials", "danger")
        
    return render_template("client/auth.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


# ================= ADMIN =================

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if session.get("admin"):
        return redirect("/admin/dashboard")

    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        if username == "admin" and password == "admin123":
            session["admin"] = True
            return redirect("/admin/dashboard")
        flash("Sovereign Authentication Failed: Invalid Credentials", "danger")
    return render_template("admin/login.html")


@app.route("/admin/dashboard")
def admin_dashboard():
    if not session.get("admin"):
        return redirect("/admin/login")

    users    = User.objects.all()
    packages = Package.objects.all()
    bookings = Booking.objects.all()

    paid_bookings = Booking.objects.filter(payment_status="Paid")
    total_revenue = sum(b.total_price for b in paid_bookings)

    pending_payments = Booking.objects.filter(payment_status="Verification Pending")
    pending_refunds  = Booking.objects.filter(payment_status="Refund Requested")
    booking_requests = Booking.objects.filter(payment_status="Awaiting Approval")

    return render_template(
        "admin/dashboard.html",
        users=users,
        packages=packages,
        bookings=bookings,
        total_revenue=total_revenue,
        pending_payments=pending_payments,
        pending_refunds=pending_refunds,
        booking_requests=booking_requests
    )


@app.route("/admin/logout")
def admin_logout():
    session.pop("admin", None)
    return redirect("/admin/login")


# ================= BOOKING =================

@app.route("/book/<string:package_id>", methods=["POST"])
def book(package_id):
    if "user_id" not in session:
        return redirect("/auth")

    package = get_or_404(Package, id=package_id)
    room    = get_or_404(RoomType, id=request.form["room_type_id"])

    travel_date      = datetime.strptime(request.form["travel_date"], "%Y-%m-%d").date()
    adults           = int(request.form["adults"])
    children_under8  = int(request.form.get("child_under8", 0))
    children_under18 = int(request.form.get("child_under18", 0))
    male_count       = int(request.form.get("male_count", 0))
    female_count     = int(request.form.get("female_count", 0))
    full_names       = request.form.get("full_names", "")
    mobile           = request.form.get("mobile", "")
    alternate_mobile = request.form.get("alternate_mobile", "")
    payment_method   = request.form["payment_method"]

    # Room price based on duration
    if package.days == 1:
        price = room.one_night_price
    elif package.days == 2:
        price = room.two_night_price
    else:
        price = room.three_night_price

    # Elite Add-ons capture
    add_luxe_stay    = request.form.get("add_luxe_stay") == "on"
    add_fine_dining  = request.form.get("add_fine_dining") == "on"
    add_private_cab  = request.form.get("add_private_cab") == "on"
    add_guides       = request.form.get("add_guides") == "on"

    services_price = 0
    if add_luxe_stay:   services_price += 5000
    if add_fine_dining: services_price += 2000
    if add_private_cab: services_price += 3000
    if add_guides:      services_price += 2000

    # Pricing: children under 8 free, under 18 at 50%
    adult_total    = price * adults
    child_50_total = (price * 0.5) * children_under18
    base_subtotal  = adult_total + child_50_total
    
    subtotal       = base_subtotal + services_price
    gst            = subtotal * GST_PERCENT / 100
    total          = subtotal + gst

    # user = User.objects.get(id=session["user_id"])
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
        payment_status   = "Awaiting Approval",
        # Save Add-ons
        add_luxe_stay    = add_luxe_stay,
        add_fine_dining  = add_fine_dining,
        add_private_cab  = add_private_cab,
        add_guides       = add_guides,
        services_total   = services_price
    )
    booking.save()

    msg = "Sovereign Request Logged: Your journey is awaiting administrative clearance."
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return {"status": "success", "message": msg, "redirect": "/profile"}

    flash(msg, "info")
    return redirect("/profile")


# ================= PAYMENT =================

@app.route("/upi_qr/<string:booking_id>")
def upi_qr(booking_id):
    booking = get_or_404(Booking, id=booking_id)

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

# ================= PAYMENT PAGE =================

@app.route("/pay/<string:booking_id>")
def pay(booking_id):

    if "user_id" not in session:
        return redirect("/auth")

    booking = get_or_404(Booking, id=booking_id)

    if booking.payment_status == "Paid":
        flash("Already Paid ✅", "success")
        return redirect("/profile")

    return render_template("client/payment.html", booking=booking)


# ================= PROCESS PAYMENT =================

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

    # Only owner can request refund
    if str(booking.user.id) != session.get("user_id"):
        flash("Unauthorized action", "danger")
        return redirect("/profile")

    booking.refund_requested = True
    booking.payment_status = "Refund Requested"
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


@app.route("/admin/approve/<string:booking_id>")
def approve_payment(booking_id):
    if not session.get("admin"):
        return redirect("/admin/login")

    booking = get_or_404(Booking, id=booking_id)
    
    # Logic for initial booking approval
    if booking.payment_status == "Awaiting Approval":
        if booking.payment_method == "UPI":
            booking.payment_status = "Pending Payment"
            flash("Tour Request Approved. Awaiting Explorer Remittance.", "success")
        else:
            booking.payment_status = "COD Approved"
            flash("Tour Request Approved. Cash on Arrival Authorized.", "success")
    else:
        # Final settlement approval
        booking.payment_status = "Paid"
        flash("Settlement Authenticated. Expedition Confirmed. ✅", "success")
    
    booking.save()
    return redirect("/admin/dashboard")


@app.route("/admin/approve_refund/<string:booking_id>")
def approve_refund(booking_id):
    if not session.get("admin"):
        return redirect("/admin/login")

    booking = get_or_404(Booking, id=booking_id)
    booking.payment_status = "Refunded"
    booking.refund_requested = False
    booking.save()

    flash("Refund Authorized. Explorer Reimbursement Finalized. 💰", "success")
    return redirect("/admin/bookings")


# @app.route("/confirm_payment/<string:booking_id>")
# def confirm_payment(booking_id):
#     booking = get_or_404(Booking, id=booking_id)

#     # Security: only the owner can confirm their own booking
#     if str(booking.user.id) != session.get("user_id"):
#         flash("Unauthorized action.", "danger")
#         return redirect("/profile")

#     booking.payment_status = "Paid"
#     booking.save()

#     flash("Payment Marked as Successful 🎉", "success")
#     return redirect("/profile")


# ================= INVOICE =================

@app.route("/download_invoice/<string:booking_id>")
def download_invoice(booking_id):
    booking   = get_or_404(Booking, id=booking_id)
    file_path = f"invoice_{str(booking.id)}.pdf"

    doc      = SimpleDocTemplate(file_path)
    elements = []
    styles   = getSampleStyleSheet()

    elements.append(Paragraph("Tour Bharat Invoice", styles["Title"]))
    elements.append(Spacer(1, 12))

    total_children = (booking.children_under8 or 0) + (booking.children_under18 or 0)

    data = [
        ["Travel Date", str(booking.travel_date)],
        ["Nights",      booking.nights],
        ["Adults",      booking.adults],
        ["Children",    total_children],
        ["Grand Base",  f"Rs.{booking.base_price}"],
        ["GST (18%)",   f"Rs.{booking.gst_amount}"],
        ["TOTAL",       f"Rs.{booking.total_price}"]
    ]

    # Add services if any
    if booking.add_luxe_stay:   data.insert(-3, ["Luxe Stay", "Included"])
    if booking.add_fine_dining: data.insert(-3, ["Fine Dining", "Included"])
    if booking.add_private_cab: data.insert(-3, ["Private Cab", "Included"])
    if booking.add_guides:      data.insert(-3, ["Elite Guides", "Included"])

    table = Table(data)
    table.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))

    elements.append(table)
    doc.build(elements)

    return send_file(file_path, as_attachment=True)


# ================= ADMIN PACKAGE MGMT =================

@app.route("/admin/packages")
def admin_packages():
    if not session.get("admin"):
        return redirect("/admin/login")
    packages = Package.objects.all()
    return render_template("admin/packages.html", packages=packages)


@app.route("/admin/edit_package/<string:id>", methods=["GET", "POST"])
def edit_package(id):
    if not session.get("admin"):
        return redirect("/admin/login")

    package = get_or_404(Package, id=id)

    if request.method == "POST":
        package.title       = request.form["title"]
        package.price       = int(request.form["price"])
        package.days        = int(request.form["days"])
        package.location    = request.form["location"]
        package.description = request.form["description"]
        package.itinerary   = request.form["itinerary"]

        # Handle Image Upload
        file = request.files.get("image_file")
        if file and file.filename != '' and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            # Ensure unique filename to prevent overwrites
            unique_filename = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{filename}"
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], unique_filename))
            package.image = unique_filename
        elif request.form.get("image_text"):
            package.image = request.form["image_text"]

        package.save()
        
        flash("Tour Record Synchronized Successfully 🎉", "success")
        return redirect("/admin/packages")

    return render_template("admin/edit_package.html", package=package)


@app.route("/admin/delete_package/<string:id>")
def delete_package(id):
    if not session.get("admin"):
        return redirect("/admin/login")

    package = get_or_404(Package, id=id)
    package.delete()
    
    flash("Expedition Terminated Successfully 🗑️", "success")
    return redirect("/admin/packages")


@app.route("/admin/add_package", methods=["GET", "POST"])
def add_package():
    if not session.get("admin"):
        return redirect("/admin/login")

    if request.method == "POST":
        image_name = "default_tour.jpg"
        file = request.files.get("image_file")
        if file and file.filename != '' and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            image_name = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{filename}"
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], image_name))
        elif request.form.get("image_text"):
            image_name = request.form["image_text"]

        new_package = Package(
            title       = request.form["title"],
            price       = int(request.form["price"]),
            days        = int(request.form["days"]),
            location    = request.form["location"],
            image       = image_name,
            description = request.form["description"],
            itinerary   = request.form["itinerary"]
        )
        new_package.save()
        flash("New Signature Tour Published 🎉", "success")
        return redirect("/admin/dashboard")

    return render_template("admin/add_package.html")


@app.route("/admin/users")
def admin_users():
    if not session.get("admin"):
        return redirect("/admin/login")
    users = User.objects.all()
    return render_template("admin/users.html", users=users)


@app.route("/admin/bookings")
def admin_bookings():
    if not session.get("admin"):
        return redirect("/admin/login")
    bookings = Booking.objects.all()
    return render_template("admin/bookings.html", bookings=bookings)


@app.route("/admin/delete_user/<string:id>")
def delete_user(id):
    if not session.get("admin"):
        return redirect("/admin/login")
    user = get_or_404(User, id=id)
    user.delete()
    flash("Explorer Identity Terminated Successfully 🗑️", "success")
    return redirect("/admin/users")


@app.route("/admin/edit_booking/<string:id>", methods=["GET", "POST"])
def edit_booking(id):
    if not session.get("admin"):
        return redirect("/admin/login")
    booking = get_or_404(Booking, id=id)
    if request.method == "POST":
        booking.payment_status = request.form["payment_status"]
        booking.total_price = int(request.form["total_price"])
        booking.save()
        flash("Reservation Records Updated. Elite Audit Complete. ✅", "success")
        return redirect("/admin/bookings")
    return render_template("admin/edit_booking.html", booking=booking)


@app.route("/admin/delete_booking/<string:id>")
def delete_booking(id):
    if not session.get("admin"):
        return redirect("/admin/login")
    booking = get_or_404(Booking, id=id)
    booking.delete()
    flash("Reservation Record Purged Successfully 🗑️", "success")
    return redirect("/admin/bookings")


@app.route("/admin/delete_review/<string:id>")
def delete_review(id):
    if not session.get("admin"):
        return redirect("/admin/login")
    review = get_or_404(Review, id=id)
    review.delete()
    flash("Feedback Narrative Moderated Successfully 🗑️", "success")
    return redirect("/admin/reviews")


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


@app.route("/chatbot", methods=["POST"])
def chatbot():
    data = request.json
    msg = data.get("message", "").lower()
    
    reply = "I'm not sure about that. Can you ask about tours, price, or contact?"
    button = None
    
    if "hello" in msg or "hi" in msg:
        reply = "Namaste! 🙏 I'm your Tour Bharat assistant. How can I help you today?"
    elif "tour" in msg or "package" in msg:
        reply = "We have many exciting tours! You can check them in our Explore section."
        button = {"text": "Explore Tours", "url": "/tours"}
    elif "price" in msg or "cost" in msg:
        reply = "Our tour prices start from ₹23,975. You can view details for each package."
    elif "contact" in msg or "call" in msg:
        reply = "You can contact us at astha@tourbharat.com or WhatsApp us."
        button = {"text": "WhatsApp Now", "url": "https://wa.me/919313868893"}

    return {"reply": reply, "button": button}


# ================= RUN =================

if __name__ == "__main__":
    seed_data()
    app.run(debug=True)