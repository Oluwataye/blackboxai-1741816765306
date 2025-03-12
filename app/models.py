from datetime import datetime
from app import db
from werkzeug.security import generate_password_hash, check_password_hash

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128))
    full_name = db.Column(db.String(120))
    specialty = db.Column(db.String(120))
    profile_photo = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    consultations = db.relationship('Consultation', backref='doctor', lazy='dynamic')
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Patient(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    patient_id = db.Column(db.String(20), unique=True, nullable=False)
    age = db.Column(db.Integer)
    gender = db.Column(db.String(10))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    consultations = db.relationship('Consultation', backref='patient', lazy='dynamic')

class Consultation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    doctor_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    patient_id = db.Column(db.Integer, db.ForeignKey('patient.id'), nullable=False)
    start_time = db.Column(db.DateTime, default=datetime.utcnow)
    end_time = db.Column(db.DateTime)
    transcription_text = db.Column(db.Text)
    translation_text = db.Column(db.Text)
    source_language = db.Column(db.String(10))
    target_language = db.Column(db.String(10))
    status = db.Column(db.String(20), default='active')  # active, completed, archived
    media_files = db.relationship('MediaFile', backref='consultation', lazy='dynamic')
    version_history = db.relationship('ConsultationVersion', backref='consultation', lazy='dynamic')

class ConsultationVersion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    consultation_id = db.Column(db.Integer, db.ForeignKey('consultation.id'), nullable=False)
    version_number = db.Column(db.Integer, nullable=False)
    transcription_text = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

class MediaFile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    consultation_id = db.Column(db.Integer, db.ForeignKey('consultation.id'), nullable=False)
    file_name = db.Column(db.String(200), nullable=False)
    file_type = db.Column(db.String(50))
    file_path = db.Column(db.String(500))
    upload_date = db.Column(db.DateTime, default=datetime.utcnow)
    tags = db.Column(db.String(200))
    uploaded_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

class UserSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), unique=True, nullable=False)
    primary_language = db.Column(db.String(10), default='en')
    translation_languages = db.Column(db.String(200))  # Comma-separated list of language codes
    auto_save_interval = db.Column(db.Integer, default=300)  # in seconds
    theme_preference = db.Column(db.String(20), default='light')
    notification_preferences = db.Column(db.JSON)
    voice_command_settings = db.Column(db.JSON)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

# Association table for custom folders and media files
media_folder_association = db.Table('media_folder_association',
    db.Column('folder_id', db.Integer, db.ForeignKey('media_folder.id')),
    db.Column('media_file_id', db.Integer, db.ForeignKey('media_file.id'))
)

class MediaFolder(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    parent_folder_id = db.Column(db.Integer, db.ForeignKey('media_folder.id'))
    files = db.relationship('MediaFile', secondary=media_folder_association, backref='folders')
