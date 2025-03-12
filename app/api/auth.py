from flask import jsonify, request, current_app
from werkzeug.security import generate_password_hash
from app import db
from app.api import bp
from app.models import User, UserSettings
import jwt
from datetime import datetime, timedelta
from functools import wraps

def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        if 'Authorization' in request.headers:
            token = request.headers['Authorization'].split(' ')[1]
        
        if not token:
            return jsonify({'message': 'Token is missing'}), 401
        
        try:
            data = jwt.decode(token, current_app.config['JWT_SECRET_KEY'], algorithms=['HS256'])
            current_user = User.query.get(data['user_id'])
        except:
            return jsonify({'message': 'Token is invalid'}), 401
        
        return f(current_user, *args, **kwargs)
    
    return decorated

@bp.route('/auth/register', methods=['POST'])
def register():
    data = request.get_json()
    
    # Validate required fields
    required_fields = ['username', 'email', 'password', 'full_name']
    for field in required_fields:
        if field not in data:
            return jsonify({'message': f'{field} is required'}), 400
    
    # Check if user already exists
    if User.query.filter_by(username=data['username']).first():
        return jsonify({'message': 'Username already exists'}), 400
    
    if User.query.filter_by(email=data['email']).first():
        return jsonify({'message': 'Email already exists'}), 400
    
    # Create new user
    user = User(
        username=data['username'],
        email=data['email'],
        full_name=data['full_name'],
        specialty=data.get('specialty', ''),
        profile_photo=data.get('profile_photo', '')
    )
    user.set_password(data['password'])
    
    # Create default user settings
    settings = UserSettings(
        primary_language='en',
        translation_languages='yo,ha,ig',
        notification_preferences={
            'email_notifications': True,
            'sound_notifications': True
        },
        voice_command_settings={
            'enabled': True,
            'sensitivity': 0.75
        }
    )
    
    try:
        db.session.add(user)
        db.session.flush()  # Get user.id before committing
        
        settings.user_id = user.id
        db.session.add(settings)
        db.session.commit()
        
        return jsonify({
            'message': 'User registered successfully',
            'user': {
                'id': user.id,
                'username': user.username,
                'email': user.email,
                'full_name': user.full_name
            }
        }), 201
    
    except Exception as e:
        db.session.rollback()
        return jsonify({'message': 'Error creating user', 'error': str(e)}), 500

@bp.route('/auth/login', methods=['POST'])
def login():
    data = request.get_json()
    
    if not data or not data.get('username') or not data.get('password'):
        return jsonify({'message': 'Username and password are required'}), 400
    
    user = User.query.filter_by(username=data['username']).first()
    
    if not user or not user.check_password(data['password']):
        return jsonify({'message': 'Invalid username or password'}), 401
    
    # Generate JWT token
    token = jwt.encode({
        'user_id': user.id,
        'username': user.username,
        'exp': datetime.utcnow() + timedelta(hours=24)
    }, current_app.config['JWT_SECRET_KEY'])
    
    return jsonify({
        'token': token,
        'user': {
            'id': user.id,
            'username': user.username,
            'email': user.email,
            'full_name': user.full_name,
            'specialty': user.specialty
        }
    }), 200

@bp.route('/auth/verify-token', methods=['GET'])
@token_required
def verify_token(current_user):
    return jsonify({
        'message': 'Token is valid',
        'user': {
            'id': current_user.id,
            'username': current_user.username,
            'email': current_user.email,
            'full_name': current_user.full_name
        }
    }), 200

@bp.route('/auth/change-password', methods=['POST'])
@token_required
def change_password(current_user):
    data = request.get_json()
    
    if not data or not data.get('current_password') or not data.get('new_password'):
        return jsonify({'message': 'Current and new passwords are required'}), 400
    
    if not current_user.check_password(data['current_password']):
        return jsonify({'message': 'Current password is incorrect'}), 401
    
    current_user.set_password(data['new_password'])
    
    try:
        db.session.commit()
        return jsonify({'message': 'Password updated successfully'}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'message': 'Error updating password', 'error': str(e)}), 500

@bp.route('/auth/forgot-password', methods=['POST'])
def forgot_password():
    data = request.get_json()
    
    if not data or not data.get('email'):
        return jsonify({'message': 'Email is required'}), 400
    
    user = User.query.filter_by(email=data['email']).first()
    
    if not user:
        return jsonify({'message': 'No user found with this email'}), 404
    
    # Generate password reset token
    reset_token = jwt.encode({
        'user_id': user.id,
        'exp': datetime.utcnow() + timedelta(hours=1)
    }, current_app.config['JWT_SECRET_KEY'])
    
    # TODO: Send reset password email
    # This would typically involve sending an email with a reset link
    
    return jsonify({
        'message': 'Password reset instructions sent to email',
        'reset_token': reset_token  # In production, this would only be sent via email
    }), 200

@bp.route('/auth/reset-password', methods=['POST'])
def reset_password():
    data = request.get_json()
    
    if not data or not data.get('reset_token') or not data.get('new_password'):
        return jsonify({'message': 'Reset token and new password are required'}), 400
    
    try:
        token_data = jwt.decode(data['reset_token'], current_app.config['JWT_SECRET_KEY'], algorithms=['HS256'])
        user = User.query.get(token_data['user_id'])
        
        if not user:
            return jsonify({'message': 'User not found'}), 404
        
        user.set_password(data['new_password'])
        db.session.commit()
        
        return jsonify({'message': 'Password reset successfully'}), 200
    
    except jwt.ExpiredSignatureError:
        return jsonify({'message': 'Reset token has expired'}), 401
    except jwt.InvalidTokenError:
        return jsonify({'message': 'Invalid reset token'}), 401
    except Exception as e:
        db.session.rollback()
        return jsonify({'message': 'Error resetting password', 'error': str(e)}), 500
