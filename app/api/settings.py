from flask import jsonify, request, current_app
from app import db
from app.api import bp
from app.api.auth import token_required
from app.models import UserSettings, User
import json

@bp.route('/settings', methods=['GET'])
@token_required
def get_settings(current_user):
    settings = UserSettings.query.filter_by(user_id=current_user.id).first()
    
    if not settings:
        return jsonify({'message': 'Settings not found'}), 404
    
    return jsonify({
        'primary_language': settings.primary_language,
        'translation_languages': settings.translation_languages.split(',') if settings.translation_languages else [],
        'auto_save_interval': settings.auto_save_interval,
        'theme_preference': settings.theme_preference,
        'notification_preferences': settings.notification_preferences,
        'voice_command_settings': settings.voice_command_settings
    }), 200

@bp.route('/settings', methods=['PUT'])
@token_required
def update_settings(current_user):
    settings = UserSettings.query.filter_by(user_id=current_user.id).first()
    
    if not settings:
        return jsonify({'message': 'Settings not found'}), 404
    
    data = request.get_json()
    
    try:
        # Update primary language
        if 'primary_language' in data:
            if data['primary_language'] not in current_app.config['SUPPORTED_LANGUAGES']:
                return jsonify({'message': 'Unsupported language'}), 400
            settings.primary_language = data['primary_language']
        
        # Update translation languages
        if 'translation_languages' in data:
            # Validate languages
            for lang in data['translation_languages']:
                if lang not in current_app.config['SUPPORTED_LANGUAGES']:
                    return jsonify({'message': f'Unsupported language: {lang}'}), 400
            settings.translation_languages = ','.join(data['translation_languages'])
        
        # Update auto-save interval
        if 'auto_save_interval' in data:
            interval = int(data['auto_save_interval'])
            if interval < 60 or interval > 3600:  # Between 1 minute and 1 hour
                return jsonify({'message': 'Auto-save interval must be between 60 and 3600 seconds'}), 400
            settings.auto_save_interval = interval
        
        # Update theme preference
        if 'theme_preference' in data:
            if data['theme_preference'] not in ['light', 'dark']:
                return jsonify({'message': 'Invalid theme preference'}), 400
            settings.theme_preference = data['theme_preference']
        
        # Update notification preferences
        if 'notification_preferences' in data:
            required_keys = {'email_notifications', 'sound_notifications'}
            if not all(key in data['notification_preferences'] for key in required_keys):
                return jsonify({'message': 'Missing notification preferences'}), 400
            settings.notification_preferences = data['notification_preferences']
        
        # Update voice command settings
        if 'voice_command_settings' in data:
            required_keys = {'enabled', 'sensitivity'}
            if not all(key in data['voice_command_settings'] for key in required_keys):
                return jsonify({'message': 'Missing voice command settings'}), 400
            
            sensitivity = float(data['voice_command_settings']['sensitivity'])
            if sensitivity < 0 or sensitivity > 1:
                return jsonify({'message': 'Sensitivity must be between 0 and 1'}), 400
            
            settings.voice_command_settings = data['voice_command_settings']
        
        db.session.commit()
        return jsonify({'message': 'Settings updated successfully'}), 200
    
    except Exception as e:
        db.session.rollback()
        return jsonify({'message': 'Error updating settings', 'error': str(e)}), 500

@bp.route('/settings/profile', methods=['PUT'])
@token_required
def update_profile(current_user):
    data = request.get_json()
    
    try:
        # Update user profile
        if 'full_name' in data:
            current_user.full_name = data['full_name']
        
        if 'specialty' in data:
            current_user.specialty = data['specialty']
        
        if 'email' in data:
            # Check if email is already taken
            existing_user = User.query.filter_by(email=data['email']).first()
            if existing_user and existing_user.id != current_user.id:
                return jsonify({'message': 'Email already in use'}), 400
            current_user.email = data['email']
        
        db.session.commit()
        return jsonify({
            'message': 'Profile updated successfully',
            'user': {
                'id': current_user.id,
                'username': current_user.username,
                'email': current_user.email,
                'full_name': current_user.full_name,
                'specialty': current_user.specialty
            }
        }), 200
    
    except Exception as e:
        db.session.rollback()
        return jsonify({'message': 'Error updating profile', 'error': str(e)}), 500

@bp.route('/settings/security', methods=['PUT'])
@token_required
def update_security_settings(current_user):
    data = request.get_json()
    settings = UserSettings.query.filter_by(user_id=current_user.id).first()
    
    if not settings:
        return jsonify({'message': 'Settings not found'}), 404
    
    try:
        # Update security preferences
        security_settings = settings.notification_preferences.get('security', {})
        
        if 'two_factor_auth' in data:
            security_settings['two_factor_auth'] = bool(data['two_factor_auth'])
        
        if 'session_timeout' in data:
            timeout = int(data['session_timeout'])
            if timeout < 300 or timeout > 3600:  # Between 5 minutes and 1 hour
                return jsonify({'message': 'Session timeout must be between 300 and 3600 seconds'}), 400
            security_settings['session_timeout'] = timeout
        
        settings.notification_preferences['security'] = security_settings
        db.session.commit()
        
        return jsonify({
            'message': 'Security settings updated successfully',
            'security_settings': security_settings
        }), 200
    
    except Exception as e:
        db.session.rollback()
        return jsonify({'message': 'Error updating security settings', 'error': str(e)}), 500

@bp.route('/settings/voice-commands', methods=['GET'])
@token_required
def get_voice_commands(current_user):
    settings = UserSettings.query.filter_by(user_id=current_user.id).first()
    
    if not settings or not settings.voice_command_settings:
        return jsonify({'message': 'Voice command settings not found'}), 404
    
    # Get custom voice commands
    voice_commands = settings.voice_command_settings.get('custom_commands', {})
    
    # Add default commands
    default_commands = {
        'save_note': 'Save note',
        'delete_last_line': 'Delete last line',
        'insert_image': 'Insert image',
        'end_consultation': 'End consultation'
    }
    
    return jsonify({
        'default_commands': default_commands,
        'custom_commands': voice_commands
    }), 200

@bp.route('/settings/voice-commands', methods=['POST'])
@token_required
def add_voice_command(current_user):
    data = request.get_json()
    
    if not data or 'command' not in data or 'phrase' not in data:
        return jsonify({'message': 'Command and phrase are required'}), 400
    
    settings = UserSettings.query.filter_by(user_id=current_user.id).first()
    
    if not settings:
        return jsonify({'message': 'Settings not found'}), 404
    
    try:
        voice_commands = settings.voice_command_settings.get('custom_commands', {})
        voice_commands[data['command']] = data['phrase']
        settings.voice_command_settings['custom_commands'] = voice_commands
        
        db.session.commit()
        return jsonify({
            'message': 'Voice command added successfully',
            'command': {
                'command': data['command'],
                'phrase': data['phrase']
            }
        }), 201
    
    except Exception as e:
        db.session.rollback()
        return jsonify({'message': 'Error adding voice command', 'error': str(e)}), 500

@bp.route('/settings/export', methods=['GET'])
@token_required
def export_settings(current_user):
    settings = UserSettings.query.filter_by(user_id=current_user.id).first()
    
    if not settings:
        return jsonify({'message': 'Settings not found'}), 404
    
    settings_data = {
        'primary_language': settings.primary_language,
        'translation_languages': settings.translation_languages.split(',') if settings.translation_languages else [],
        'auto_save_interval': settings.auto_save_interval,
        'theme_preference': settings.theme_preference,
        'notification_preferences': settings.notification_preferences,
        'voice_command_settings': settings.voice_command_settings
    }
    
    return jsonify(settings_data), 200

@bp.route('/settings/import', methods=['POST'])
@token_required
def import_settings(current_user):
    data = request.get_json()
    
    if not data:
        return jsonify({'message': 'No settings data provided'}), 400
    
    settings = UserSettings.query.filter_by(user_id=current_user.id).first()
    
    if not settings:
        return jsonify({'message': 'Settings not found'}), 404
    
    try:
        # Validate and import settings
        if 'primary_language' in data:
            if data['primary_language'] not in current_app.config['SUPPORTED_LANGUAGES']:
                return jsonify({'message': 'Unsupported primary language'}), 400
            settings.primary_language = data['primary_language']
        
        if 'translation_languages' in data:
            for lang in data['translation_languages']:
                if lang not in current_app.config['SUPPORTED_LANGUAGES']:
                    return jsonify({'message': f'Unsupported language: {lang}'}), 400
            settings.translation_languages = ','.join(data['translation_languages'])
        
        if 'auto_save_interval' in data:
            interval = int(data['auto_save_interval'])
            if interval < 60 or interval > 3600:
                return jsonify({'message': 'Invalid auto-save interval'}), 400
            settings.auto_save_interval = interval
        
        if 'theme_preference' in data:
            if data['theme_preference'] not in ['light', 'dark']:
                return jsonify({'message': 'Invalid theme preference'}), 400
            settings.theme_preference = data['theme_preference']
        
        if 'notification_preferences' in data:
            settings.notification_preferences = data['notification_preferences']
        
        if 'voice_command_settings' in data:
            settings.voice_command_settings = data['voice_command_settings']
        
        db.session.commit()
        return jsonify({'message': 'Settings imported successfully'}), 200
    
    except Exception as e:
        db.session.rollback()
        return jsonify({'message': 'Error importing settings', 'error': str(e)}), 500
