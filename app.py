import os
import io
import hmac
import hashlib
from datetime import datetime
from flask import Flask, render_template_string, request, redirect, url_for, flash, send_file, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
import razorpay
from reportlab.pdfgen import canvas

app = Flask(__name__)

# Secret keys and database path configuration
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'production_super_secret_key_98765')
db_path = os.path.join('/tmp', 'tuition_system.db')
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# Razorpay API Credentials (Set via environment variables or replace with test keys)
RAZORPAY_KEY_ID = os.environ.get('RAZORPAY_KEY_ID', 'rzp_test_YOUR_KEY_ID')
RAZORPAY_KEY_SECRET = os.environ.get('RAZORPAY_KEY_SECRET', 'YOUR_KEY_SECRET')
razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))

# ==========================================
# 1. DATABASE MODELS
# ==========================================

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(100), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    role = db.Column(db.String(20), default='student')  # 'admin' or 'student'
    monthly_fee = db.Column(db.Integer, default=1500)
    fee_records = db.relationship('FeeRecord', backref='student', lazy=True, cascade="all, delete-orphan")

class FeeRecord(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    month = db.Column(db.String(50), nullable=False)
    amount = db.Column(db.Integer, nullable=False)
    is_paid = db.Column(db.Boolean, default=False)
    payment_date = db.Column(db.String(50), default='-')
    razorpay_order_id = db.Column(db.String(100), nullable=True)
    razorpay_payment_id = db.Column(db.String(100), nullable=True)

class StudyMaterial(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    file_type = db.Column(db.String(50), nullable=False)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ==========================================
# 2. HTML TEMPLATES
# ==========================================

LOGIN_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Tuition Portal Login</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body { font-family: Arial, sans-serif; background: #f4f7f6; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; }
        .card { background: white; padding: 35px; border-radius: 10px; box-shadow: 0 4px 15px rgba(0,0,0,0.1); width: 320px; text-align: center; }
        input { width: 90%; padding: 12px; margin: 10px 0; border: 1px solid #ccc; border-radius: 5px; font-size: 14px; box-sizing: border-box; }
        button { width: 90%; padding: 12px; background: #28a745; color: white; border: none; border-radius: 5px; font-size: 16px; cursor: pointer; font-weight: bold; }
        .error { color: red; font-size: 14px; margin-bottom: 10px; }
    </style>
</head>
<body>
    <div class="card">
        <h2>Tuition Portal Login</h2>
        {% with messages = get_flashed_messages() %}
            {% if messages %}<p class="error">{{ messages[0] }}</p>{% endif %}
        {% endwith %}
        <form method="POST">
            <input type="email" name="email" placeholder="Email Address" required><br>
            <input type="password" name="password" placeholder="Password" required><br>
            <button type="submit">Log In</button>
        </form>
    </div>
</body>
</html>
"""

STUDENT_DASHBOARD_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Student Dashboard</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <script src="https://checkout.razorpay.com/v1/checkout.js"></script>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; background: #fafafa; }
        .container { max-width: 850px; margin: auto; background: white; padding: 25px; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }
        .badge-paid { color: green; font-weight: bold; background: #e6ffe6; padding: 5px 10px; border-radius: 4px; }
        .badge-unpaid { color: red; font-weight: bold; background: #ffe6e6; padding: 5px 10px; border-radius: 4px; }
        .btn { padding: 8px 15px; background: #007bff; color: white; text-decoration: none; border-radius: 4px; display: inline-block; cursor: pointer; border: none; }
        .btn-pay { background: #28a745; font-weight: bold; }
        .header { display: flex; justify-content: space-between; align-items: center; border-bottom: 2px solid #eee; padding-bottom: 15px; }
        table { width: 100%; border-collapse: collapse; margin-top: 15px; }
        th, td { border: 1px solid #ddd; padding: 12px; text-align: left; }
        th { background: #f8f9fa; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h2>Welcome, {{ current_user.name }}!</h2>
            <a href="/logout" style="color: red; text-decoration: none; font-weight: bold;">Log Out</a>
        </div>

        <h3>Monthly Fee Payment Status</h3>
        <table>
            <tr>
                <th>Month</th>
                <th>Fee Allocated</th>
                <th>Status</th>
                <th>Payment Date</th>
                <th>Action</th>
            </tr>
            {% for record in current_user.fee_records %}
            <tr>
                <td><b>{{ record.month }}</b></td>
                <td>Rs. {{ record.amount }}</td>
                <td>
                    {% if record.is_paid %}
                        <span class="badge-paid">PAID ✅</span>
                    {% else %}
                        <span class="badge-unpaid">UNPAID ❌</span>
                    {% endif %}
                </td>
                <td>{{ record.payment_date }}</td>
                <td>
                    {% if record.is_paid %}
                        <a href="/download-receipt/{{ record.id }}" class="btn">Download PDF Receipt</a>
                    {% else %}
                        <button class="btn btn-pay" onclick="initiatePayment({{ record.id }})">Pay Fee Online</button>
                    {% endif %}
                </td>
            </tr>
            {% else %}
            <tr>
                <td colspan="5" style="text-align: center;">No fee records assigned by Admin yet.</td>
            </tr>
            {% endfor %}
        </table>

        <h3 style="margin-top: 35px;">Classroom Study Materials</h3>
        <ul>
            {% for item in materials %}
                <li><b>{{ item.title }}</b> - <i>[{{ item.file_type }}]</i></li>
            {% else %}
                <li>No materials posted yet.</li>
            {% endfor %}
        </ul>
    </div>

    <script>
        function initiatePayment(recordId) {
            fetch('/create-razorpay-order', {
                method: 'POST',
                headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                body: 'record_id=' + recordId
            })
            .then(response => response.json())
            .then(data => {
                if (data.error) {
                    alert(data.error);
                    return;
                }
                var options = {
                    "key": data.key_id,
                    "amount": data.amount,
                    "currency": "INR",
                    "name": "Tuition Fee Payment",
                    "description": "Fee for " + data.month,
                    "order_id": data.order_id,
                    "handler": function (response) {
                        verifyPayment(response, recordId);
                    },
                    "prefill": {
                        "name": "{{ current_user.name }}",
                        "email": "{{ current_user.email }}"
                    },
                    "theme": { "color": "#28a745" }
                };
                var rzp1 = new Razorpay(options);
                rzp1.open();
            });
        }

        function verifyPayment(paymentResponse, recordId) {
            fetch('/verify-payment', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    razorpay_order_id: paymentResponse.razorpay_order_id,
                    razorpay_payment_id: paymentResponse.razorpay_payment_id,
                    razorpay_signature: paymentResponse.razorpay_signature,
                    record_id: recordId
                })
            })
            .then(res => res.json())
            .then(data => {
                if (data.status === 'success') {
                    alert('Payment Verified Successfully!');
                    window.location.reload();
                } else {
                    alert('Payment Verification Failed!');
                }
            });
        }
    </script>
</body>
</html>
"""

ADMIN_DASHBOARD_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Teacher Admin Control</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; background: #f4f7f6; }
        .container { max-width: 1050px; margin: auto; background: white; padding: 25px; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }
        .header { display: flex; justify-content: space-between; align-items: center; border-bottom: 2px solid #eee; padding-bottom: 15px; }
        table { width: 100%; border-collapse: collapse; margin-top: 15px; }
        th, td { border: 1px solid #ddd; padding: 10px; text-align: left; }
        th { background: #f8f9fa; }
        .form-box { background: #f8f9fa; padding: 18px; margin-top: 20px; border-radius: 5px; border: 1px solid #e9ecef; }
        input { padding: 8px; margin: 5px 0; }
        button { padding: 8px 12px; background: #007bff; color: white; border: none; border-radius: 4px; cursor: pointer; }
        .btn-delete { background: #dc3545; }
        .status-paid { color: green; font-weight: bold; background: #e6ffe6; padding: 3px 6px; border-radius: 3px; }
        .status-unpaid { color: red; font-weight: bold; background: #ffe6e6; padding: 3px 6px; border-radius: 3px; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h2>Teacher Control Panel</h2>
            <a href="/logout" style="color: red; text-decoration: none; font-weight: bold;">Log Out</a>
        </div>

        <h3>Monthly Fee Monitoring & Student Allocation</h3>
        <table>
            <tr>
                <th>Student Name</th>
                <th>Email</th>
                <th>Current Assigned Fee</th>
                <th>Monthly Payment Audit Trail</th>
                <th>Assign New Fee</th>
                <th>Action</th>
            </tr>
            {% for student in students %}
            <tr>
                <td><b>{{ student.name }}</b></td>
                <td>{{ student.email }}</td>
                <td><b>Rs. {{ student.monthly_fee }}</b></td>
                <td>
                    {% for rec in student.fee_records %}
                        <div style="margin-bottom: 5px;">
                            <b>{{ rec.month }}:</b>
                            {% if rec.is_paid %}
                                <span class="status-paid">PAID (Rs. {{ rec.amount }})</span>
                            {% else %}
                                <span class="status-unpaid">UNPAID (Rs. {{ rec.amount }})</span>
                            {% endif %}
                        </div>
                    {% else %}
                        <small style="color:gray;">No fee record created</small>
                    {% endfor %}
                </td>
                <td>
                    <form action="/update-fee" method="POST" style="display:inline;">
                        <input type="hidden" name="user_id" value="{{ student.id }}">
                        <input type="number" name="new_fee" placeholder="Fee (Rs.)" style="width: 80px;" required>
                        <button type="submit">Update Fee</button>
                    </form>
                </td>
                <td>
                    <form action="/delete-student" method="POST" style="display:inline;" onsubmit="return confirm('Delete this student?');">
                        <input type="hidden" name="user_id" value="{{ student.id }}">
                        <button type="submit" class="btn-delete">Delete</button>
                    </form>
                </td>
            </tr>
            {% endfor %}
        </table>

        <div class="form-box">
            <h3>Add New Student Account</h3>
            <form action="/add-student" method="POST">
                <input type="text" name="name" placeholder="Student Name" required>
                <input type="email" name="email" placeholder="Gmail Address" required>
                <input type="number" name="fee" placeholder="Initial Fee (Rs.)" required>
                <input type="password" name="password" placeholder="Assign Password" required>
                <button type="submit" style="background: #28a745;">Create Student Account</button>
            </form>
        </div>

        <div class="form-box">
            <h3>Post Homework / Classroom Material</h3>
            <form action="/add-material" method="POST">
                <input type="text" name="title" placeholder="Material Title" required>
                <input type="text" name="type" placeholder="Type (PDF, Image, Notes)" required>
                <button type="submit">Publish Material</button>
            </form>
        </div>
    </div>
</body>
</html>
"""

# ==========================================
# 3. ROUTES & CONTROLLERS
# ==========================================

@app.before_request
def setup_db():
    db.create_all()
    if not User.query.filter_by(email='admin@tuition.com').first():
        admin = User(email='admin@tuition.com', password='admin123', name='Teacher Admin', role='admin')
        db.session.add(admin)
        db.session.commit()

@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        user = User.query.filter_by(email=email).first()

        if user and user.password == password:
            login_user(user)
            if user.role == 'admin':
                return redirect(url_for('admin_dashboard'))
            return redirect(url_for('student_dashboard'))
        
        flash('Invalid Email or Password!')
    return render_template_string(LOGIN_HTML)

@app.route('/student-dashboard')
@login_required
def student_dashboard():
    if current_user.role == 'admin':
        return redirect(url_for('admin_dashboard'))
    
    if not current_user.fee_records:
        curr_month = datetime.now().strftime('%B %Y')
        rec = FeeRecord(user_id=current_user.id, month=curr_month, amount=current_user.monthly_fee, is_paid=False)
        db.session.add(rec)
        db.session.commit()

    materials = StudyMaterial.query.all()
    return render_template_string(STUDENT_DASHBOARD_HTML, materials=materials)

@app.route('/admin-dashboard')
@login_required
def admin_dashboard():
    if current_user.role != 'admin':
        return redirect(url_for('student_dashboard'))
    students = User.query.filter_by(role='student').all()
    return render_template_string(ADMIN_DASHBOARD_HTML, students=students)

@app.route('/update-fee', methods=['POST'])
@login_required
def update_fee():
    if current_user.role == 'admin':
        user = User.query.get(request.form.get('user_id'))
        new_fee = int(request.form.get('new_fee'))
        if user:
            user.monthly_fee = new_fee
            # Update the fee amount for all current unpaid records instantly
            for rec in user.fee_records:
                if not rec.is_paid:
                    rec.amount = new_fee
            db.session.commit()
    return redirect(url_for('admin_dashboard'))

@app.route('/add-student', methods=['POST'])
@login_required
def add_student():
    if current_user.role == 'admin':
        name = request.form['name']
        email = request.form['email']
        fee = int(request.form['fee'])
        password = request.form['password']
        
        new_user = User(email=email, password=password, name=name, monthly_fee=fee, role='student')
        db.session.add(new_user)
        db.session.commit()
        
        curr_month = datetime.now().strftime('%B %Y')
        initial_record = FeeRecord(user_id=new_user.id, month=curr_month, amount=fee, is_paid=False)
        db.session.add(initial_record)
        db.session.commit()
        
    return redirect(url_for('admin_dashboard'))

@app.route('/delete-student', methods=['POST'])
@login_required
def delete_student():
    if current_user.role == 'admin':
        user = User.query.get(request.form.get('user_id'))
        if user:
            db.session.delete(user)
            db.session.commit()
    return redirect(url_for('admin_dashboard'))

@app.route('/add-material', methods=['POST'])
@login_required
def add_material():
    if current_user.role == 'admin':
        mat = StudyMaterial(title=request.form['title'], file_type=request.form['type'])
        db.session.add(mat)
        db.session.commit()
    return redirect(url_for('admin_dashboard'))

# ==========================================
# 4. PAYMENT & VERIFICATION ENGINE
# ==========================================

@app.route('/create-razorpay-order', methods=['POST'])
@login_required
def create_razorpay_order():
    rec_id = request.form.get('record_id')
    record = FeeRecord.query.get_or_404(rec_id)
    
    if record.user_id != current_user.id or record.is_paid:
        return jsonify({'error': 'Invalid fee record'}), 400

    order_amount = record.amount * 100  # Convert to Paise
    order_data = {
        'amount': order_amount,
        'currency': 'INR',
        'receipt': f'rcpt_{record.id}',
        'payment_capture': '1'
    }
    
    order = razorpay_client.order.create(data=order_data)
    record.razorpay_order_id = order['id']
    db.session.commit()

    return jsonify({
        'order_id': order['id'],
        'amount': order_amount,
        'key_id': RAZORPAY_KEY_ID,
        'month': record.month
    })

@app.route('/verify-payment', methods=['POST'])
@login_required
def verify_payment():
    data = request.get_json()
    record = FeeRecord.query.get_or_404(data['record_id'])

    params_dict = {
        'razorpay_order_id': data['razorpay_order_id'],
        'razorpay_payment_id': data['razorpay_payment_id'],
        'razorpay_signature': data['razorpay_signature']
    }

    try:
        razorpay_client.utility.verify_payment_signature(params_dict)
        record.is_paid = True
        record.payment_date = datetime.now().strftime('%d-%b-%Y')
        record.razorpay_payment_id = data['razorpay_payment_id']
        db.session.commit()
        return jsonify({'status': 'success'})
    except razorpay.errors.SignatureVerificationError:
        return jsonify({'status': 'failure'}), 400

@app.route('/download-receipt/<int:record_id>')
@login_required
def download_receipt(record_id):
    rec = FeeRecord.query.get_or_404(record_id)
    if rec.user_id != current_user.id or not rec.is_paid:
        return "Unauthorized action.", 403
        
    buffer = io.BytesIO()
    p = canvas.Canvas(buffer)
    
    p.setFont("Helvetica-Bold", 18)
    p.drawString(180, 800, "OFFICIAL TUITION FEE RECEIPT")
    p.line(100, 780, 500, 780)
    
    p.setFont("Helvetica", 12)
    p.drawString(100, 740, f"Receipt Date: {rec.payment_date}")
    p.drawString(100, 710, f"Transaction ID: {rec.razorpay_payment_id or 'TXN_VERIFIED'}")
    p.drawString(100, 680, f"Student Name: {current_user.name}")
    p.drawString(100, 650, f"Fee Period: {rec.month}")
    p.drawString(100, 620, f"Amount Paid: Rs. {rec.amount}")
    p.drawString(100, 590, "Payment Method: Razorpay Online (Verified)")
    
    p.showPage()
    p.save()
    
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name=f"Receipt_{current_user.name}_{rec.month}.pdf", mimetype='application/pdf')

@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
