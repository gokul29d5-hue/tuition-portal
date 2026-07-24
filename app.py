import os
import io
from datetime import datetime
from flask import Flask, render_template_string, request, redirect, url_for, flash, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from reportlab.pdfgen import canvas

app = Flask(__name__)
app.config['SECRET_KEY'] = 'production_super_secret_key_98765'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///tuition_system.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# ==========================================
# 1. PERMANENT DATABASE MODELS
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

class StudyMaterial(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    file_type = db.Column(db.String(50), nullable=False)

class SystemConfig(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    upi_id = db.Column(db.String(100), default='teacher@upi')

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ==========================================
# 2. HTML WEBPAGE TEMPLATES
# ==========================================

LOGIN_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Tuition Portal</title>
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
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; background: #fafafa; }
        .container { max-width: 850px; margin: auto; background: white; padding: 25px; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }
        .badge-paid { color: green; font-weight: bold; background: #e6ffe6; padding: 5px 10px; border-radius: 4px; }
        .badge-unpaid { color: red; font-weight: bold; background: #ffe6e6; padding: 5px 10px; border-radius: 4px; }
        .btn { padding: 8px 15px; background: #007bff; color: white; text-decoration: none; border-radius: 4px; display: inline-block; cursor: pointer; border: none; }
        .btn-pay { background: #28a745; }
        .header { display: flex; justify-content: space-between; align-items: center; border-bottom: 2px solid #eee; padding-bottom: 15px; }
        table { width: 100%; border-collapse: collapse; margin-top: 15px; }
        th, td { border: 1px solid #ddd; padding: 12px; text-align: left; }
        th { background: #f8f9fa; }
        .modal { display: none; position: fixed; z-index: 10; left: 0; top: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.5); }
        .modal-content { background: white; margin: 10% auto; padding: 25px; border-radius: 8px; width: 330px; text-align: center; }
        .qr-img { border: 2px solid #ddd; padding: 10px; border-radius: 8px; margin: 15px 0; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h2>Welcome, {{ current_user.name }}!</h2>
            <a href="/logout" style="color: red; text-decoration: none; font-weight: bold;">Log Out</a>
        </div>

        <h3>Monthly Fee Status & History Chart</h3>
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
                        <a href="/download-receipt/{{ record.id }}" class="btn">Download Receipt (PDF)</a>
                    {% else %}
                        <button class="btn btn-pay" onclick="openPaymentModal({{ record.id }}, '{{ record.month }}', {{ record.amount }})">Pay Fee via QR</button>
                    {% endif %}
                </td>
            </tr>
            {% endfor %}
        </table>

        <h3 style="margin-top: 35px;">Classroom Study Materials</h3>
        <ul>
            {% for item in materials %}
                <li><b>{{ item.title }}</b> - <i>[{{ item.file_type }}]</i></li>
            {% empty %}
                <li>No materials posted yet.</li>
            {% endfor %}
        </ul>
    </div>

    <div id="payModal" class="modal">
        <div class="modal-content">
            <h3>Scan QR Code to Pay</h3>
            <p>Paying for: <b id="payMonth"></b></p>
            <p>Fee Allocated: <b id="payAmount"></b></p>
            <img id="qrImage" class="qr-img" src="" alt="UPI QR Code" width="200" height="200">
            <p><small>Scan with Google Pay, PhonePe, or Paytm</small></p>
            <form action="/pay-fee" method="POST">
                <input type="hidden" id="recordId" name="record_id">
                <button type="submit" class="btn btn-pay" style="width: 100%;">I Have Completed Payment</button>
            </form>
            <button onclick="closePaymentModal()" style="margin-top: 10px; background: none; border: none; color: gray; cursor: pointer;">Cancel</button>
        </div>
    </div>

    <script>
        function openPaymentModal(recId, month, amount) {
            document.getElementById('payMonth').innerText = month;
            document.getElementById('payAmount').innerText = 'Rs. ' + amount;
            document.getElementById('recordId').value = recId;
            var upiId = "{{ upi_id }}";
            var qrUrl = "https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=upi://pay?pa=" + encodeURIComponent(upiId) + "%26pn=TuitionFee%26am=" + amount + "%26cu=INR";
            document.getElementById('qrImage').src = qrUrl;
            document.getElementById('payModal').style.display = 'block';
        }
        function closePaymentModal() { document.getElementById('payModal').style.display = 'none'; }
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
        .container { max-width: 1000px; margin: auto; background: white; padding: 25px; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }
        .header { display: flex; justify-content: space-between; align-items: center; border-bottom: 2px solid #eee; padding-bottom: 15px; }
        table { width: 100%; border-collapse: collapse; margin-top: 15px; }
        th, td { border: 1px solid #ddd; padding: 10px; text-align: left; }
        th { background: #f8f9fa; }
        .form-box { background: #f8f9fa; padding: 18px; margin-top: 20px; border-radius: 5px; border: 1px solid #e9ecef; }
        input { padding: 8px; margin: 5px 0; }
        button { padding: 8px 12px; background: #007bff; color: white; border: none; border-radius: 4px; cursor: pointer; }
        .btn-delete { background: #dc3545; }
        .status-paid { color: green; font-weight: bold; }
        .status-unpaid { color: red; font-weight: bold; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h2>Teacher Control Panel</h2>
            <a href="/logout" style="color: red; text-decoration: none; font-weight: bold;">Log Out</a>
        </div>

        <div class="form-box" style="background: #eaf4ff; border-color: #b8daff;">
            <h3>Configure Your Payment UPI ID</h3>
            <form action="/update-upi" method="POST" style="display: flex; gap: 10px; align-items: center;">
                <input type="text" name="upi_id" value="{{ config.upi_id }}" placeholder="e.g. yourname@upi" style="width: 250px;" required>
                <button type="submit" style="background: #28a745;">Save UPI ID</button>
            </form>
        </div>

        <h3>Live Student Fee Management & Monthly Charts</h3>
        <table>
            <tr>
                <th>Student Name</th>
                <th>Email</th>
                <th>Current Fee</th>
                <th>Fee History Tracking</th>
                <th>Edit Fee</th>
                <th>Action</th>
            </tr>
            {% for student in students %}
            <tr>
                <td><b>{{ student.name }}</b></td>
                <td>{{ student.email }}</td>
                <td>Rs. {{ student.monthly_fee }}</td>
                <td>
                    {% for rec in student.fee_records %}
                        <small><b>{{ rec.month }}:</b> 
                        {% if rec.is_paid %}<span class="status-paid">PAID</span>{% else %}<span class="status-unpaid">UNPAID</span>{% endif %}</small><br>
                    {% endfor %}
                </td>
                <td>
                    <form action="/update-fee" method="POST" style="display:inline;">
                        <input type="hidden" name="user_id" value="{{ student.id }}">
                        <input type="number" name="new_fee" placeholder="New Fee" style="width: 80px;" required>
                        <button type="submit">Update</button>
                    </form>
                </td>
                <td>
                    <form action="/delete-student" method="POST" style="display:inline;" onsubmit="return confirm('Are you sure you want to delete this student?');">
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
                <input type="number" name="fee" placeholder="Monthly Fee (Rs.)" required>
                <input type="password" name="password" placeholder="Assign Password" required>
                <button type="submit" style="background: #28a745;">Add Student</button>
            </form>
        </div>

        <div class="form-box">
            <h3>Upload Homework / Study Materials</h3>
            <form action="/add-material" method="POST">
                <input type="text" name="title" placeholder="Material Title" required>
                <input type="text" name="type" placeholder="Type (PDF, Image, Notes)" required>
                <button type="submit">Post Material</button>
            </form>
        </div>
    </div>
</body>
</html>
"""

# ==========================================
# 3. CONTROLLER ROUTES
# ==========================================

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
    materials = StudyMaterial.query.all()
    config = SystemConfig.query.first()
    return render_template_string(STUDENT_DASHBOARD_HTML, materials=materials, upi_id=config.upi_id)

@app.route('/admin-dashboard')
@login_required
def admin_dashboard():
    if current_user.role != 'admin':
        return redirect(url_for('student_dashboard'))
    students = User.query.filter_by(role='student').all()
    config = SystemConfig.query.first()
    return render_template_string(ADMIN_DASHBOARD_HTML, students=students, config=config)

@app.route('/update-upi', methods=['POST'])
@login_required
def update_upi():
    if current_user.role == 'admin':
        config = SystemConfig.query.first()
        config.upi_id = request.form.get('upi_id')
        db.session.commit()
    return redirect(url_for('admin_dashboard'))

@app.route('/pay-fee', methods=['POST'])
@login_required
def pay_fee():
    rec_id = request.form.get('record_id')
    record = FeeRecord.query.get(rec_id)
    if record and record.user_id == current_user.id:
        record.is_paid = True
        record.payment_date = datetime.now().strftime('%d-%b-%Y')
        db.session.commit()
    return redirect(url_for('student_dashboard'))

@app.route('/update-fee', methods=['POST'])
@login_required
def update_fee():
    if current_user.role == 'admin':
        user = User.query.get(request.form.get('user_id'))
        new_fee = int(request.form.get('new_fee'))
        if user:
            user.monthly_fee = new_fee
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

@app.route('/download-receipt/<int:record_id>')
@login_required
def download_receipt(record_id):
    rec = FeeRecord.query.get_or_404(record_id)
    if rec.user_id != current_user.id or not rec.is_paid:
        return "Unauthorized", 403
        
    buffer = io.BytesIO()
    p = canvas.Canvas(buffer)
    p.setFont("Helvetica-Bold", 18)
    p.drawString(200, 800, "OFFICIAL TUITION RECEIPT")
    p.line(100, 780, 500, 780)
    p.setFont("Helvetica", 12)
    p.drawString(100, 740, f"Receipt Date: {rec.payment_date}")
    p.drawString(100, 710, f"Student Name: {current_user.name}")
    p.drawString(100, 680, f"Fee Month: {rec.month}")
    p.drawString(100, 650, f"Amount Paid: Rs. {rec.amount}")
    p.drawString(100, 620, "Status: PAID (Verified Online)")
    p.showPage()
    p.save()
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name=f"Receipt_{current_user.name}_{rec.month}.pdf", mimetype='application/pdf')

@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('login'))

# Initialize Database & Default Admin Account
with app.app_context():
    db.create_all()
    if not SystemConfig.query.first():
        db.session.add(SystemConfig(upi_id='teacher@upi'))
    if not User.query.filter_by(email='admin@tuition.com').first():
        admin = User(email='admin@tuition.com', password='admin123', name='Teacher Admin', role='admin')
        db.session.add(admin)
    db.session.commit()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)