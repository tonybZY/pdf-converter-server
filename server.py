#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
os.environ['PYTHONIOENCODING'] = 'utf-8'

from flask import Flask, request, jsonify, Response, send_file
from flask_cors import CORS
import uuid
from datetime import datetime, timedelta
import io
import base64
from functools import wraps
import mimetypes
import sys

# Forcer UTF-8 partout
if sys.version_info[0] >= 3:
    import locale
    locale.setlocale(locale.LC_ALL, 'C.UTF-8')

app = Flask(__name__)
CORS(app)

# Configuration
PRIMARY_API_KEY = os.environ.get('PRIMARY_API_KEY', 'pk_live_mega_converter_primary_key_2024_super_secure_token_xyz789')
SECONDARY_API_KEY = os.environ.get('SECONDARY_API_KEY', 'sk_live_mega_converter_secondary_key_2024_ultra_secure_token_abc456')
MAX_FILE_SIZE = int(os.environ.get('MAX_FILE_SIZE', 180 * 1024 * 1024))  # 180MB par défaut
FILE_EXPIRY_HOURS = int(os.environ.get('FILE_EXPIRY_HOURS', 24))
BASE_URL = os.environ.get('BASE_URL', 'https://pdf-converter-server-production.up.railway.app')

# Stockage temporaire en mémoire
TEMP_STORAGE = {}

# Tous les formats acceptés
ALLOWED_EXTENSIONS = {
    'png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp', 'ico', 'svg', 'tiff', 'tif',
    'pdf', 'txt', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'odt', 'ods', 'odp',
    'html', 'htm', 'css', 'js', 'json', 'xml',
    'csv', 'md', 'rtf', 'tex',
    'zip', 'rar', '7z', 'tar', 'gz',
    'mp4', 'avi', 'mov', 'wmv', 'flv', 'webm', 'mkv', 'm4v',
    'mp3', 'wav', 'flac', 'aac', 'ogg', 'wma', 'm4a',
    'exe', 'dmg', 'apk', 'deb', 'rpm'
}

def cleanup_old_files():
    """Nettoie les fichiers expires"""
    current_time = datetime.now()
    expired_keys = []
    
    for key, data in TEMP_STORAGE.items():
        if current_time > data['expiry']:
            expired_keys.append(key)
    
    for key in expired_keys:
        del TEMP_STORAGE[key]
        print(f"[DELETE] Fichier expire supprime: {key}")

def require_api_key(f):
    """Verification des cles API"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = request.headers.get('X-API-Key')
        if not api_key:
            api_key = request.args.get('api_key')
        if not api_key and request.form:
            api_key = request.form.get('api_key')
        
        if api_key not in [PRIMARY_API_KEY, SECONDARY_API_KEY]:
            return jsonify({
                "error": "Cle API invalide ou manquante",
                "message": "Utilisez une des deux cles API valides"
            }), 401
        
        request.api_key_type = "primary" if api_key == PRIMARY_API_KEY else "secondary"
        return f(*args, **kwargs)
    return decorated_function

def store_file(content, filename, content_type=None):
    """Stocke n'importe quel fichier et retourne une URL"""
    cleanup_old_files()
    
    file_id = str(uuid.uuid4())
    expiry = datetime.now() + timedelta(hours=FILE_EXPIRY_HOURS)
    
    if not content_type:
        content_type = mimetypes.guess_type(filename)[0] or 'application/octet-stream'
    
    TEMP_STORAGE[file_id] = {
        'content': base64.b64encode(content).decode('utf-8') if isinstance(content, bytes) else content,
        'filename': filename,
        'content_type': content_type,
        'expiry': expiry,
        'created': datetime.now(),
        'size': len(content)
    }
    
    return f"{BASE_URL}/download/{file_id}"

def get_file_extension(filename):
    if not filename or '.' not in filename:
        return None
    return filename.rsplit('.', 1)[1].lower()

@app.route('/')
def home():
    """Page d'accueil"""
    cleanup_old_files()
    
    return jsonify({
        "service": "File Storage API - Stockage de fichiers avec URLs",
        "version": "1.0",
        "status": "Operationnel",
        "description": "Upload n'importe quel fichier et obtenez une URL de telechargement",
        "features": {
            "file_storage": "Stockage de tous types de fichiers",
            "temporary_urls": "URLs temporaires securisees",
            "all_formats": "Images, PDF, videos, documents, etc.",
            "dual_api_keys": "Primary & Secondary keys",
            "auto_cleanup": f"Suppression apres {FILE_EXPIRY_HOURS}h",
            "max_file_size": f"Jusqu'a {MAX_FILE_SIZE / (1024*1024)}MB"
        },
        "endpoints": {
            "POST /upload": "Upload un fichier",
            "POST /convert": "Upload un fichier (alias)",
            "GET /download/{id}": "Telecharger un fichier",
            "GET /info/{id}": "Infos sur un fichier",
            "GET /health": "Verification sante",
            "GET /status": "Statut du service"
        }
    })

@app.route('/health')
def health():
    """Verification sante"""
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "storage_count": len(TEMP_STORAGE)
    })

@app.route('/upload', methods=['POST'])
@app.route('/convert', methods=['POST'])
@require_api_key
def upload_file():
    """Upload n'importe quel fichier et retourne une URL"""
    try:
        if 'file' not in request.files:
            return jsonify({"error": "Aucun fichier fourni"}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({"error": "Nom de fichier vide"}), 400
        
        file_content = file.read()
        if len(file_content) > MAX_FILE_SIZE:
            return jsonify({
                "error": "Fichier trop volumineux",
                "max_size_mb": MAX_FILE_SIZE / (1024 * 1024)
            }), 413
        
        filename = file.filename
        file_ext = get_file_extension(filename)
        
        if file_ext and file_ext not in ALLOWED_EXTENSIONS:
            print(f"[WARNING] Extension non standard: {file_ext}")
        
        download_url = store_file(file_content, filename, file.content_type)
        
        file_info = {
            "success": True,
            "filename": filename,
            "download_url": download_url,
            "direct_url": download_url,
            "file_id": download_url.split('/')[-1],
            "format": file_ext or "unknown",
            "size_bytes": len(file_content),
            "size_mb": round(len(file_content) / (1024 * 1024), 2),
            "content_type": file.content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream",
            "uploaded_at": datetime.now().isoformat(),
            "expires_at": (datetime.now() + timedelta(hours=FILE_EXPIRY_HOURS)).isoformat(),
            "expiry_hours": FILE_EXPIRY_HOURS,
            "api_key_used": request.api_key_type,
            "message": f"Fichier uploade! URL valide pendant {FILE_EXPIRY_HOURS}h"
        }
        
        return jsonify(file_info)
        
    except Exception as e:
        print(f"[ERROR] Erreur upload: {str(e)}")
        return jsonify({"error": f"Erreur: {str(e)}"}), 500

@app.route('/download/<file_id>')
def download(file_id):
    """Telecharge un fichier stocke"""
    try:
        cleanup_old_files()
        
        if file_id not in TEMP_STORAGE:
            return jsonify({"error": "Fichier non trouve ou expire"}), 404
        
        file_data = TEMP_STORAGE[file_id]
        
        if datetime.now() > file_data['expiry']:
            del TEMP_STORAGE[file_id]
            return jsonify({"error": "Fichier expire"}), 404
        
        content = base64.b64decode(file_data['content'])
        
        response = Response(
            content,
            mimetype=file_data['content_type'],
            headers={
                'Content-Disposition': f'attachment; filename="{file_data["filename"]}"',
                'Content-Length': str(len(content)),
                'Content-Type': file_data['content_type'],
                'Cache-Control': 'public, max-age=3600'
            }
        )
        
        return response
    except Exception as e:
        print(f"[ERROR] Erreur download: {str(e)}")
        return jsonify({"error": "Erreur serveur interne"}), 500

@app.route('/info/<file_id>')
def file_info(file_id):
    """Retourne les infos sur un fichier"""
    if file_id not in TEMP_STORAGE:
        return jsonify({"error": "Fichier non trouve"}), 404
    
    file_data = TEMP_STORAGE[file_id]
    time_left = file_data['expiry'] - datetime.now()
    
    return jsonify({
        "filename": file_data['filename'],
        "content_type": file_data['content_type'],
        "size_bytes": file_data['size'],
        "size_mb": round(file_data['size'] / (1024 * 1024), 2),
        "created": file_data['created'].isoformat(),
        "expires_at": file_data['expiry'].isoformat(),
        "expires_in_hours": max(0, time_left.total_seconds() / 3600),
        "download_url": f"{BASE_URL}/download/{file_id}"
    })

@app.route('/status')
def status():
    """Statut du service"""
    cleanup_old_files()
    
    total_size = sum(data['size'] for data in TEMP_STORAGE.values())
    
    files_list = []
    for file_id, data in TEMP_STORAGE.items():
        time_left = data['expiry'] - datetime.now()
        files_list.append({
            "id": file_id,
            "filename": data['filename'],
            "size_mb": round(data['size'] / (1024 * 1024), 2),
            "type": data['content_type'],
            "expires_in_hours": max(0, time_left.total_seconds() / 3600)
        })
    
    return jsonify({
        "status": "operational",
        "version": "1.0",
        "storage": {
            "files_count": len(TEMP_STORAGE),
            "total_size_mb": round(total_size / (1024 * 1024), 2),
            "files": files_list[:20]
        },
        "limits": {
            "max_file_size_mb": MAX_FILE_SIZE / (1024 * 1024),
            "file_expiry_hours": FILE_EXPIRY_HOURS,
            "supported_formats": len(ALLOWED_EXTENSIONS)
        },
        "timestamp": datetime.now().isoformat()
    })

@app.route('/qrcode', methods=['POST'])
@require_api_key
def qrcode_compat():
    """Compatibilite avec l'ancienne API"""
    return jsonify({
        "error": "Cette fonctionnalite n'est plus disponible",
        "message": "Utilisez /upload pour stocker n'importe quel fichier"
    }), 501

@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Endpoint non trouve"}), 404

@app.errorhandler(500)
def server_error(e):
    return jsonify({"error": "Erreur serveur interne"}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    
    print("="*60)
    print("FILE STORAGE SERVER - Serveur de stockage de fichiers")
    print("="*60)
    print(f"Port: {port}")
    print(f"Taille max: {MAX_FILE_SIZE / (1024*1024)} MB")
    print(f"Expiration: {FILE_EXPIRY_HOURS} heures")
    print(f"Formats: {len(ALLOWED_EXTENSIONS)}+ formats acceptes")
    print(f"URL de base: {BASE_URL}")
    print("="*60)
    print("CLES API:")
    print(f"   Primary: {PRIMARY_API_KEY[:30]}...")
    print(f"   Secondary: {SECONDARY_API_KEY[:30]}...")
    print("="*60)
    print("Endpoints:")
    print("   POST /upload - Upload un fichier")
    print("   GET  /download/{id} - Telecharger")
    print("   GET  /info/{id} - Infos fichier")
    print("   GET  /status - Voir tous les fichiers")
    print("="*60)
    
    app.run(host='0.0.0.0', port=port, debug=False)
