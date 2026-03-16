import os
import sqlite3
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import uuid

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///instant_call_center.db'
app.config['UPLOAD_FOLDER'] = 'uploads'

# Initialize database
db = SQLAlchemy(app)

# Initialize login manager
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# User model
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    is_staff = db.Column(db.Boolean, default=False)
    group_id = db.Column(db.Integer, db.ForeignKey('group.id'), nullable=True)
    
    # Relationships
    # Cases created by the user
    cases = db.relationship('Case', back_populates='user', lazy=True, foreign_keys='Case.user_id')
    # Cases assigned to the user
    assigned_cases = db.relationship('Case', back_populates='assigned_to', lazy=True, foreign_keys='Case.assigned_to_id')
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

# Group model
class Group(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    users = db.relationship('User', backref='group', lazy=True)
    
    def __repr__(self):
        return f'<Group {self.name}>'

# Case model
class Case(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    created_date = db.Column(db.DateTime, default=datetime.utcnow)
    resolved_date = db.Column(db.DateTime)
    status = db.Column(db.String(50), default='open')
    case_type = db.Column(db.String(100))
    category = db.Column(db.String(100))
    assignment_group_id = db.Column(db.Integer, db.ForeignKey('group.id'), nullable=True)
    assigned_to_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    
    # Relationships
    assignment_group = db.relationship('Group', foreign_keys=[assignment_group_id])
    assigned_to = db.relationship('User', foreign_keys=[assigned_to_id], back_populates='assigned_cases')
    user = db.relationship('User', back_populates='cases', foreign_keys=[user_id])
    comments = db.relationship('Comment', backref='case', lazy=True, cascade='all, delete-orphan')
    attachments = db.relationship('Attachment', backref='case', lazy=True, cascade='all, delete-orphan')

# Comment model
class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    created_date = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    case_id = db.Column(db.Integer, db.ForeignKey('case.id'), nullable=False)
    
    # Relationships
    user = db.relationship('User')

# Attachment model
class Attachment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(200), nullable=False)
    filepath = db.Column(db.String(300), nullable=False)
    uploaded_date = db.Column(db.DateTime, default=datetime.utcnow)
    case_id = db.Column(db.Integer, db.ForeignKey('case.id'), nullable=False)

# Create tables and initial data
with app.app_context():
    # Create tables if they don't exist
    db.create_all()
    
    # Check if the 'Triage' group exists; create if not
    if not Group.query.filter_by(name='Triage').first():
        triage_group = Group(name='Triage', description='Initial case handling group')
        db.session.add(triage_group)
        db.session.commit()
    else:
        triage_group = Group.query.filter_by(name='Triage').first()
    
    # Check if admin user exists; create if not
    if not User.query.filter_by(username='admin').first():
        admin_user = User(username='admin', email='admin@example.com', is_staff=True)
        admin_user.set_password('admin123')
        admin_user.group = triage_group
        db.session.add(admin_user)
        db.session.commit()

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Routes
@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid username or password')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        # Check if user already exists
        if User.query.filter_by(username=username).first() or User.query.filter_by(email=email).first():
            flash('Username or email already exists')
            return render_template('register.html')
        # Create new user
        user = User(username=username, email=email)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        flash('Registration successful. Please login.')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/dashboard')
@login_required
def dashboard():
    if current_user.is_staff:
        # Staff view - show assigned cases and unassigned cases in their group
        assigned_cases = Case.query.filter_by(assigned_to_id=current_user.id).all()
        unassigned_cases = Case.query.filter_by(assignment_group_id=current_user.group_id, assigned_to_id=None).all()
        return render_template('staff_dashboard.html',
                               assigned_cases=assigned_cases,
                               unassigned_cases=unassigned_cases)
    else:
        # User view - show their cases
        user_cases = Case.query.filter_by(user_id=current_user.id).all()
        return render_template('user_dashboard.html', cases=user_cases)

@app.route('/submit_case', methods=['GET', 'POST'])
@login_required
def submit_case():
    if request.method == 'POST':
        title = request.form['title']
        description = request.form['description']
        case_type = request.form['case_type']
        category = request.form['category']
        # Create new case
        case = Case(
            title=title,
            description=description,
            case_type=case_type,
            category=category,
            user_id=current_user.id,
            assignment_group_id=1  # Default to triage group
        )
        db.session.add(case)
        db.session.commit()
        flash('Case submitted successfully')
        return redirect(url_for('dashboard'))
    return render_template('submit_case.html')

@app.route('/case/<int:case_id>')
@login_required
def view_case(case_id):
    case = Case.query.get_or_404(case_id)
    # Check if user has access to this case
    if not current_user.is_staff and case.user_id != current_user.id:
        flash('Access denied')
        return redirect(url_for('dashboard'))
    return render_template('view_case.html', case=case)

@app.route('/case/<int:case_id>/comment', methods=['POST'])
@login_required
def add_comment(case_id):
    case = Case.query.get_or_404(case_id)
    # Check if user has access to this case
    if not current_user.is_staff and case.user_id != current_user.id:
        flash('Access denied')
        return redirect(url_for('dashboard'))
    content = request.form['content']
    comment = Comment(content=content, user_id=current_user.id, case_id=case_id)
    db.session.add(comment)
    db.session.commit()
    flash('Comment added successfully')
    return redirect(url_for('view_case', case_id=case_id))

@app.route('/case/<int:case_id>/assign', methods=['POST'])
@login_required
def assign_case(case_id):
    if not current_user.is_staff:
        flash('Access denied')
        return redirect(url_for('dashboard'))
    case = Case.query.get_or_404(case_id)
    assigned_to_id = request.form['assigned_to']
    # Validate user
    user = User.query.get(assigned_to_id)
    if user and user.group_id == current_user.group_id:
        case.assigned_to_id = assigned_to_id
        db.session.commit()
        flash('Case assigned successfully')
    else:
        flash('Invalid assignment')
    return redirect(url_for('dashboard'))

@app.route('/case/<int:case_id>/resolve', methods=['POST'])
@login_required
def resolve_case(case_id):
    case = Case.query.get_or_404(case_id)
    # Only assigned staff or admin can resolve
    if current_user.is_staff and (case.assigned_to_id == current_user.id or current_user.is_staff):
        case.resolved_date = datetime.utcnow()
        case.status = 'resolved'
        db.session.commit()
        flash('Case resolved successfully')
    else:
        flash('Access denied')
    return redirect(url_for('dashboard'))

@app.route('/upload_attachment/<int:case_id>', methods=['POST'])
@login_required
def upload_attachment(case_id):
    case = Case.query.get_or_404(case_id)
    # Check if user has access
    if not current_user.is_staff and case.user_id != current_user.id:
        flash('Access denied')
        return redirect(url_for('dashboard'))
    if 'file' not in request.files:
        flash('No file selected')
        return redirect(url_for('view_case', case_id=case_id))
    file = request.files['file']
    if file.filename == '':
        flash('No file selected')
        return redirect(url_for('view_case', case_id=case_id))
    if file:
        filename = secure_filename(file.filename)
        unique_filename = str(uuid.uuid4()) + '_' + filename
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
        file.save(filepath)
        # Save attachment to database
        attachment = Attachment(filename=filename, filepath=filepath, case_id=case_id)
        db.session.add(attachment)
        db.session.commit()
        flash('File uploaded successfully')
    return redirect(url_for('view_case', case_id=case_id))

@app.route('/download/<int:attachment_id>')
@login_required
def download_attachment(attachment_id):
    attachment = Attachment.query.get_or_404(attachment_id)
    case = Case.query.get_or_404(attachment.case_id)
    # Check access
    if not current_user.is_staff and case.user_id != current_user.id:
        flash('Access denied')
        return redirect(url_for('dashboard'))
    return send_file(attachment.filepath, as_attachment=True)

@app.route('/api/cases')
@login_required
def api_cases():
    """API endpoint for cases (for future expansion)"""
    if current_user.is_staff:
        cases = Case.query.filter_by(assignment_group_id=current_user.group_id).all()
    else:
        cases = Case.query.filter_by(user_id=current_user.id).all()
    return jsonify([{
        'id': case.id,
        'title': case.title,
        'description': case.description,
        'created_date': case.created_date.isoformat(),
        'status': case.status,
        'assigned_to': case.assigned_to.username if case.assigned_to else None
    } for case in cases])

if __name__ == '__main__':
    app.run(debug=True)