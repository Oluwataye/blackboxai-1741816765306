from flask import jsonify, request, current_app
from app import db
from app.api import bp
from app.api.auth import token_required
from app.models import Consultation, Patient, ConsultationVersion, MediaFile
from datetime import datetime
import speech_recognition as sr
from google.cloud import speech, translate
import json
import os

def transcribe_audio(audio_file, language_code='en-US'):
    """Transcribe audio using Google Cloud Speech-to-Text"""
    client = speech.SpeechClient()
    
    with open(audio_file, 'rb') as audio:
        content = audio.read()
    
    audio = speech.RecognitionAudio(content=content)
    config = speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
        sample_rate_hertz=16000,
        language_code=language_code,
        enable_automatic_punctuation=True,
        model='medical_conversation'
    )
    
    response = client.recognize(config=config, audio=audio)
    return ' '.join(result.alternatives[0].transcript for result in response.results)

def translate_text(text, target_language):
    """Translate text using Google Cloud Translate"""
    client = translate.TranslationServiceClient()
    project_id = current_app.config['GOOGLE_CLOUD_PROJECT']
    location = 'global'
    parent = f"projects/{project_id}/locations/{location}"
    
    response = client.translate_text(
        request={
            "parent": parent,
            "contents": [text],
            "mime_type": "text/plain",
            "target_language_code": target_language,
        }
    )
    
    return response.translations[0].translated_text

@bp.route('/consultations', methods=['POST'])
@token_required
def create_consultation(current_user):
    data = request.get_json()
    
    # Validate required fields
    if not data or not data.get('patient_id'):
        return jsonify({'message': 'Patient ID is required'}), 400
    
    # Check if patient exists
    patient = Patient.query.filter_by(patient_id=data['patient_id']).first()
    if not patient:
        return jsonify({'message': 'Patient not found'}), 404
    
    # Create new consultation
    consultation = Consultation(
        doctor_id=current_user.id,
        patient_id=patient.id,
        source_language=data.get('source_language', 'en'),
        target_language=data.get('target_language'),
        status='active'
    )
    
    try:
        db.session.add(consultation)
        db.session.commit()
        
        return jsonify({
            'message': 'Consultation created successfully',
            'consultation': {
                'id': consultation.id,
                'start_time': consultation.start_time.isoformat(),
                'status': consultation.status
            }
        }), 201
    
    except Exception as e:
        db.session.rollback()
        return jsonify({'message': 'Error creating consultation', 'error': str(e)}), 500

@bp.route('/consultations/<int:id>/transcribe', methods=['POST'])
@token_required
def transcribe_consultation(current_user, id):
    if 'audio' not in request.files:
        return jsonify({'message': 'No audio file provided'}), 400
    
    consultation = Consultation.query.get_or_404(id)
    
    # Verify user has access to this consultation
    if consultation.doctor_id != current_user.id:
        return jsonify({'message': 'Unauthorized access'}), 403
    
    audio_file = request.files['audio']
    
    # Save audio file temporarily
    temp_path = os.path.join(current_app.config['UPLOAD_FOLDER'], f'temp_{id}_{datetime.now().timestamp()}.wav')
    audio_file.save(temp_path)
    
    try:
        # Transcribe audio
        transcription = transcribe_audio(temp_path, consultation.source_language)
        
        # Translate if target language is specified
        translation = None
        if consultation.target_language:
            translation = translate_text(transcription, consultation.target_language)
        
        # Update consultation
        consultation.transcription_text = (consultation.transcription_text or '') + '\\n' + transcription
        if translation:
            consultation.translation_text = (consultation.translation_text or '') + '\\n' + translation
        
        # Create version history
        version = ConsultationVersion(
            consultation_id=consultation.id,
            version_number=consultation.version_history.count() + 1,
            transcription_text=consultation.transcription_text,
            created_by=current_user.id
        )
        
        db.session.add(version)
        db.session.commit()
        
        # Clean up temporary file
        os.remove(temp_path)
        
        return jsonify({
            'message': 'Transcription successful',
            'transcription': transcription,
            'translation': translation
        }), 200
        
    except Exception as e:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        return jsonify({'message': 'Error processing audio', 'error': str(e)}), 500

@bp.route('/consultations/<int:id>', methods=['GET'])
@token_required
def get_consultation(current_user, id):
    consultation = Consultation.query.get_or_404(id)
    
    # Verify user has access to this consultation
    if consultation.doctor_id != current_user.id:
        return jsonify({'message': 'Unauthorized access'}), 403
    
    return jsonify({
        'id': consultation.id,
        'patient': {
            'id': consultation.patient.id,
            'name': consultation.patient.name,
            'patient_id': consultation.patient.patient_id
        },
        'start_time': consultation.start_time.isoformat(),
        'end_time': consultation.end_time.isoformat() if consultation.end_time else None,
        'transcription_text': consultation.transcription_text,
        'translation_text': consultation.translation_text,
        'source_language': consultation.source_language,
        'target_language': consultation.target_language,
        'status': consultation.status,
        'media_files': [{
            'id': file.id,
            'file_name': file.file_name,
            'file_type': file.file_type,
            'upload_date': file.upload_date.isoformat()
        } for file in consultation.media_files]
    }), 200

@bp.route('/consultations/<int:id>', methods=['PUT'])
@token_required
def update_consultation(current_user, id):
    consultation = Consultation.query.get_or_404(id)
    
    # Verify user has access to this consultation
    if consultation.doctor_id != current_user.id:
        return jsonify({'message': 'Unauthorized access'}), 403
    
    data = request.get_json()
    
    # Update allowed fields
    if 'transcription_text' in data:
        consultation.transcription_text = data['transcription_text']
        
        # Create new version
        version = ConsultationVersion(
            consultation_id=consultation.id,
            version_number=consultation.version_history.count() + 1,
            transcription_text=consultation.transcription_text,
            created_by=current_user.id
        )
        db.session.add(version)
    
    if 'status' in data:
        consultation.status = data['status']
        if data['status'] == 'completed':
            consultation.end_time = datetime.utcnow()
    
    try:
        db.session.commit()
        return jsonify({'message': 'Consultation updated successfully'}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'message': 'Error updating consultation', 'error': str(e)}), 500

@bp.route('/consultations/<int:id>/versions', methods=['GET'])
@token_required
def get_consultation_versions(current_user, id):
    consultation = Consultation.query.get_or_404(id)
    
    # Verify user has access to this consultation
    if consultation.doctor_id != current_user.id:
        return jsonify({'message': 'Unauthorized access'}), 403
    
    versions = consultation.version_history.order_by(ConsultationVersion.version_number.desc()).all()
    
    return jsonify([{
        'version_number': v.version_number,
        'created_at': v.created_at.isoformat(),
        'created_by': v.created_by,
        'transcription_text': v.transcription_text
    } for v in versions]), 200

@bp.route('/consultations/<int:id>/restore/<int:version>', methods=['POST'])
@token_required
def restore_consultation_version(current_user, id, version):
    consultation = Consultation.query.get_or_404(id)
    
    # Verify user has access to this consultation
    if consultation.doctor_id != current_user.id:
        return jsonify({'message': 'Unauthorized access'}), 403
    
    version_record = ConsultationVersion.query.filter_by(
        consultation_id=id,
        version_number=version
    ).first_or_404()
    
    # Create new version with restored content
    new_version = ConsultationVersion(
        consultation_id=consultation.id,
        version_number=consultation.version_history.count() + 1,
        transcription_text=version_record.transcription_text,
        created_by=current_user.id
    )
    
    consultation.transcription_text = version_record.transcription_text
    
    try:
        db.session.add(new_version)
        db.session.commit()
        return jsonify({'message': 'Consultation version restored successfully'}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'message': 'Error restoring version', 'error': str(e)}), 500

@bp.route('/consultations', methods=['GET'])
@token_required
def get_consultations(current_user):
    # Get query parameters for filtering
    status = request.args.get('status')
    patient_id = request.args.get('patient_id')
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    
    # Base query
    query = Consultation.query.filter_by(doctor_id=current_user.id)
    
    # Apply filters
    if status:
        query = query.filter_by(status=status)
    if patient_id:
        patient = Patient.query.filter_by(patient_id=patient_id).first()
        if patient:
            query = query.filter_by(patient_id=patient.id)
    if date_from:
        query = query.filter(Consultation.start_time >= datetime.fromisoformat(date_from))
    if date_to:
        query = query.filter(Consultation.start_time <= datetime.fromisoformat(date_to))
    
    # Order by start time descending
    consultations = query.order_by(Consultation.start_time.desc()).all()
    
    return jsonify([{
        'id': c.id,
        'patient': {
            'id': c.patient.id,
            'name': c.patient.name,
            'patient_id': c.patient.patient_id
        },
        'start_time': c.start_time.isoformat(),
        'end_time': c.end_time.isoformat() if c.end_time else None,
        'status': c.status,
        'media_count': c.media_files.count()
    } for c in consultations]), 200
