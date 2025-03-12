from flask import jsonify, request, current_app, send_file
from app import db
from app.api import bp
from app.api.auth import token_required
from app.models import MediaFile, MediaFolder, Consultation
from werkzeug.utils import secure_filename
from datetime import datetime
import os
import magic
from PIL import Image
import io
from google.cloud import storage

def allowed_file(filename, allowed_extensions):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in allowed_extensions

def get_file_type(file_path):
    """Determine file type using python-magic"""
    mime = magic.Magic(mime=True)
    return mime.from_file(file_path)

def optimize_image(file_path):
    """Optimize image for web use"""
    try:
        with Image.open(file_path) as img:
            # Convert to RGB if necessary
            if img.mode in ('RGBA', 'P'):
                img = img.convert('RGB')
            
            # Calculate new dimensions while maintaining aspect ratio
            max_size = (1920, 1080)
            img.thumbnail(max_size, Image.LANCZOS)
            
            # Save optimized image
            output = io.BytesIO()
            img.save(output, format='JPEG', quality=85, optimize=True)
            output.seek(0)
            
            # Save back to file
            with open(file_path, 'wb') as f:
                f.write(output.getvalue())
            
            return True
    except Exception as e:
        print(f"Error optimizing image: {str(e)}")
        return False

def upload_to_cloud_storage(file_path, destination_blob_name):
    """Upload file to Google Cloud Storage"""
    storage_client = storage.Client()
    bucket = storage_client.bucket(current_app.config['CLOUD_STORAGE_BUCKET'])
    blob = bucket.blob(destination_blob_name)
    
    blob.upload_from_filename(file_path)
    return blob.public_url

@bp.route('/media/upload', methods=['POST'])
@token_required
def upload_file(current_user):
    if 'file' not in request.files:
        return jsonify({'message': 'No file provided'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'message': 'No selected file'}), 400
    
    consultation_id = request.form.get('consultation_id')
    if consultation_id:
        consultation = Consultation.query.get_or_404(consultation_id)
        if consultation.doctor_id != current_user.id:
            return jsonify({'message': 'Unauthorized access'}), 403
    
    if file and allowed_file(file.filename, current_app.config['ALLOWED_IMAGE_EXTENSIONS']):
        filename = secure_filename(file.filename)
        file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
        
        try:
            # Save file locally
            file.save(file_path)
            
            # Get file type
            file_type = get_file_type(file_path)
            
            # Optimize image if it's an image file
            if file_type.startswith('image/'):
                optimize_image(file_path)
            
            # Upload to cloud storage
            cloud_path = f"user_{current_user.id}/{datetime.now().strftime('%Y%m%d_%H%M%S')}_{filename}"
            public_url = upload_to_cloud_storage(file_path, cloud_path)
            
            # Create media file record
            media_file = MediaFile(
                consultation_id=consultation_id if consultation_id else None,
                file_name=filename,
                file_type=file_type,
                file_path=public_url,
                uploaded_by=current_user.id,
                tags=request.form.get('tags', '')
            )
            
            # Add to folder if specified
            folder_id = request.form.get('folder_id')
            if folder_id:
                folder = MediaFolder.query.get_or_404(folder_id)
                if folder.created_by != current_user.id:
                    return jsonify({'message': 'Unauthorized access to folder'}), 403
                media_file.folders.append(folder)
            
            db.session.add(media_file)
            db.session.commit()
            
            # Clean up local file
            os.remove(file_path)
            
            return jsonify({
                'message': 'File uploaded successfully',
                'file': {
                    'id': media_file.id,
                    'file_name': media_file.file_name,
                    'file_type': media_file.file_type,
                    'file_path': media_file.file_path,
                    'upload_date': media_file.upload_date.isoformat()
                }
            }), 201
            
        except Exception as e:
            if os.path.exists(file_path):
                os.remove(file_path)
            return jsonify({'message': 'Error uploading file', 'error': str(e)}), 500
    
    return jsonify({'message': 'File type not allowed'}), 400

@bp.route('/media/folders', methods=['POST'])
@token_required
def create_folder(current_user):
    data = request.get_json()
    
    if not data or not data.get('name'):
        return jsonify({'message': 'Folder name is required'}), 400
    
    folder = MediaFolder(
        name=data['name'],
        created_by=current_user.id,
        parent_folder_id=data.get('parent_folder_id')
    )
    
    try:
        db.session.add(folder)
        db.session.commit()
        return jsonify({
            'message': 'Folder created successfully',
            'folder': {
                'id': folder.id,
                'name': folder.name,
                'created_at': folder.created_at.isoformat()
            }
        }), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({'message': 'Error creating folder', 'error': str(e)}), 500

@bp.route('/media/folders', methods=['GET'])
@token_required
def get_folders(current_user):
    folders = MediaFolder.query.filter_by(created_by=current_user.id).all()
    
    return jsonify([{
        'id': f.id,
        'name': f.name,
        'created_at': f.created_at.isoformat(),
        'parent_folder_id': f.parent_folder_id,
        'file_count': len(f.files)
    } for f in folders]), 200

@bp.route('/media/folders/<int:id>', methods=['GET'])
@token_required
def get_folder_contents(current_user, id):
    folder = MediaFolder.query.get_or_404(id)
    
    if folder.created_by != current_user.id:
        return jsonify({'message': 'Unauthorized access'}), 403
    
    return jsonify({
        'folder': {
            'id': folder.id,
            'name': folder.name,
            'created_at': folder.created_at.isoformat(),
            'parent_folder_id': folder.parent_folder_id
        },
        'files': [{
            'id': f.id,
            'file_name': f.file_name,
            'file_type': f.file_type,
            'file_path': f.file_path,
            'upload_date': f.upload_date.isoformat(),
            'tags': f.tags
        } for f in folder.files]
    }), 200

@bp.route('/media/files', methods=['GET'])
@token_required
def get_files(current_user):
    # Get query parameters
    consultation_id = request.args.get('consultation_id')
    file_type = request.args.get('file_type')
    tags = request.args.get('tags')
    
    # Base query
    query = MediaFile.query.filter_by(uploaded_by=current_user.id)
    
    # Apply filters
    if consultation_id:
        query = query.filter_by(consultation_id=consultation_id)
    if file_type:
        query = query.filter_by(file_type=file_type)
    if tags:
        query = query.filter(MediaFile.tags.contains(tags))
    
    files = query.order_by(MediaFile.upload_date.desc()).all()
    
    return jsonify([{
        'id': f.id,
        'file_name': f.file_name,
        'file_type': f.file_type,
        'file_path': f.file_path,
        'upload_date': f.upload_date.isoformat(),
        'tags': f.tags,
        'consultation_id': f.consultation_id
    } for f in files]), 200

@bp.route('/media/files/<int:id>', methods=['DELETE'])
@token_required
def delete_file(current_user, id):
    file = MediaFile.query.get_or_404(id)
    
    if file.uploaded_by != current_user.id:
        return jsonify({'message': 'Unauthorized access'}), 403
    
    try:
        # Delete from cloud storage
        storage_client = storage.Client()
        bucket = storage_client.bucket(current_app.config['CLOUD_STORAGE_BUCKET'])
        blob = bucket.blob(file.file_path.split('/')[-1])
        blob.delete()
        
        # Delete from database
        db.session.delete(file)
        db.session.commit()
        
        return jsonify({'message': 'File deleted successfully'}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'message': 'Error deleting file', 'error': str(e)}), 500

@bp.route('/media/files/<int:id>/tags', methods=['PUT'])
@token_required
def update_file_tags(current_user, id):
    file = MediaFile.query.get_or_404(id)
    
    if file.uploaded_by != current_user.id:
        return jsonify({'message': 'Unauthorized access'}), 403
    
    data = request.get_json()
    if not data or 'tags' not in data:
        return jsonify({'message': 'Tags are required'}), 400
    
    try:
        file.tags = data['tags']
        db.session.commit()
        return jsonify({'message': 'Tags updated successfully'}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'message': 'Error updating tags', 'error': str(e)}), 500
