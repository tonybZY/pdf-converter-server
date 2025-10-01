#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from flask import Flask, request, jsonify, Response, send_file
from flask_cors import CORS
import os
import uuid
from datetime import datetime, timedelta
import io
import base64
from functools import wraps
import mimetypes
import unicodedata
import re
import requests
from PIL import Image
import tempfile

app = Flask(__name__)
CORS(app)

# Configuration
PRIMARY_API_KEY = os.environ.get('PRIMARY_API_KEY', 'pk_live_mega_converter_primary_key_2024_super_secure_token_xyz789')
SECONDARY_API_KEY = os.environ.get('SECONDARY_API_KEY', 'sk_live_mega_converter_secondary_key_2024_ultra_secure_token_abc456')

# NOUVELLES LIMITES PLUS GRANDES
MAX_FILE_SIZE = int(os.environ.get('MAX_FILE_SIZE', 500 * 1024 * 1024))  # 500MB par défaut
MAX_IMAGE_SIZE = int(os.environ.get('MAX_IMAGE_SIZE', 1000 * 1024 * 1024))  # 1GB pour images
AUTO_COMPRESS_IMAGES = os.environ.get('AUTO_COMPRESS_IMAGES', 'true').lower() == 'true'
MAX_IMAGE_DIMENSION = int(os.environ.get('MAX_IMAGE_DIMENSION', 80000))  # 80000px max par côté

FILE_EXPIRY_HOURS = int(os.environ.get('FILE_EXPIRY_HOURS', 24))
BASE_URL = os.environ.get('BASE_URL', 'https://pdf-converter-server-production.up.railway.app')

# Stockage temporaire en mémoire
TEMP_STORAGE = {}

# Tous les formats acceptés
ALLOWED_EXTENSIONS = {
    # Images
    'png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp', 'ico', 'svg', 'tiff', 'tif',
    # Documents
    'pdf', 'txt', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'odt', 'ods', 'odp',
    # Web
    'html', 'htm', 'css', 'js', 'json', 'xml',
    # Fichiers
    'csv', 'md', 'rtf', 'tex',
    # Archives
    'zip', 'rar', '7z', 'tar', 'gz',
    # Vidéos
    'mp4', 'avi', 'mov', 'wmv', 'flv', 'webm', 'mkv', 'm4v',
    # Audio
    'mp3', 'wav', 'flac', 'aac', 'ogg', 'wma', 'm4a',
    # Autres
    'exe', 'dmg', 'apk', 'deb', 'rpm'
}

IMAGE_FORMATS = {'png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp', 'tiff', 'tif'}

def sanitize_filename(filename):
    """Nettoie le nom de fichier pour éviter les problèmes"""
    if '.' in filename:
        name, ext = filename.rsplit('.', 1)
    else:
        name, ext = filename, ''
    
    name = unicodedata.normalize('NFKD', name)
    name = ''.join([c for c in name if not unicodedata.combining(c)])
    name = re.sub(r'[^\w\s-]', '', name)
    name = re.sub(r'[-\s]+', '_', name)
    name = name[:50]
    
    if ext:
        return f"{name}.{ext}"
    return name

def compress_image(image_content, filename, quality=85, max_dimension=None):
    """Compresse une image pour réduire sa taille"""
    try:
        print(f"[COMPRESS] Tentative de compression: {filename}")
        
        # Ouvrir l'image
        img = Image.open(io.BytesIO(image_content))
        original_format = img.format or 'PNG'
        original_size = len(image_content)
        
        print(f"[COMPRESS] Format: {original_format}, Taille: {img.size}, {original_size/1024/1024:.2f}MB")
        
        # Redimensionner si trop grande
        if max_dimension:
            width, height = img.size
            if width > max_dimension or height > max_dimension:
                ratio = min(max_dimension / width, max_dimension / height)
                new_size = (int(width * ratio), int(height * ratio))
                print(f"[COMPRESS] Redimensionnement de {img.size} vers {new_size}")
                img = img.resize(new_size, Image.Resampling.LANCZOS)
        
        # Convertir en RGB si nécessaire (pour JPEG)
        if img.mode in ('RGBA', 'LA', 'P'):
            background = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'P':
                img = img.convert('RGBA')
            background.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
            img = background
        
        # Sauvegarder compressé
        output = io.BytesIO()
        save_format = 'JPEG' if original_format in ('JPEG', 'JPG') else 'PNG'
        
        if save_format == 'JPEG':
            img.save(output, format=save_format, quality=quality, optimize=True)
        else:
            img.save(output, format=save_format, optimize=True, compress_level=9)
        
        compressed_content = output.getvalue()
        compressed_size = len(compressed_content)
        
        compression_ratio = (1 - compressed_size / original_size) * 100
        print(f"[COMPRESS] Compressé: {compressed_size/1024/1024:.2f}MB (gain: {compression_ratio:.1f}%)")
        
        # Retourner la version compressée seulement si gain > 10%
        if compression_ratio > 10:
            return compressed_content, True
        else:
            print(f"[COMPRESS] Compression insuffisante, garde l'original")
            return image_content, False
            
    except Exception as e:
        print(f"[COMPRESS] Erreur compression: {e}")
        return image_content, False

def cleanup_old_files():
    """Nettoie les fichiers expirés"""
    current_time = datetime.now()
    expired_keys = []
    
    for key, data in TEMP_STORAGE.items():
        if current_time > data['expiry']:
            expired_keys.append(key)
    
    for key in expired_keys:
        del TEMP_STORAGE[key]
        print(f"[DELETE] Fichier expire supprime: {key}")

def require_api_key(f):
    """Vérification des clés API"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = request.headers.get('X-API-Key')
        if not api_key:
            api_key = request.args.get('api_key')
        if not api_key and request.form:
            api_key = request.form.get('api_key')
        
        if api_key not in [PRIMARY_API_KEY, SECONDARY_API_KEY]:
            return jsonify({
                "error": "Clé API invalide ou manquante",
                "message": "Utilisez une des deux clés API valides"
            }), 401
        
        request.api_key_type = "primary" if api_key == PRIMARY_API_KEY else "secondary"
        return f(*args, **kwargs)
    return decorated_function

def store_file(content, filename, content_type=None, metadata=None):
    """Stocke n'importe quel fichier et retourne une URL"""
    cleanup_old_files()
    
    file_id = str(uuid.uuid4())
    expiry = datetime.now() + timedelta(hours=FILE_EXPIRY_HOURS)
    
    clean_filename = sanitize_filename(filename)
    print(f"[INFO] Nom original: {filename}")
    print(f"[INFO] Nom nettoye: {clean_filename}")
    
    if not content_type:
        content_type = mimetypes.guess_type(clean_filename)[0] or 'application/octet-stream'
    
    storage_data = {
        'content': base64.b64encode(content).decode('utf-8') if isinstance(content, bytes) else content,
        'filename': clean_filename,
        'original_filename': filename,
        'content_type': content_type,
        'expiry': expiry,
        'created': datetime.now(),
        'size': len(content)
    }
    
    # Ajouter metadata si fournie
    if metadata:
        storage_data.update(metadata)
    
    TEMP_STORAGE[file_id] = storage_data
    
    return f"{BASE_URL}/download/{file_id}"

def get_file_extension(filename):
    if not filename or '.' not in filename:
        return None
    return filename.rsplit('.', 1)[1].lower()

# ===== ROUTES =====

@app.route('/')
def home():
    """Page d'accueil"""
    cleanup_old_files()
    
    return jsonify({
        "service": "[FILE] Storage API - Stockage GROS FICHIERS avec compression",
        "version": "2.0",
        "status": "[OK] Operationnel",
        "description": "Upload de TRES GROS fichiers avec compression automatique",
        "features": {
            "large_files": f"[OK] Jusqu'a {MAX_FILE_SIZE/(1024*1024)}MB",
            "huge_images": f"[OK] Images jusqu'a {MAX_IMAGE_SIZE/(1024*1024)}MB",
            "auto_compress": f"[{'OK' if AUTO_COMPRESS_IMAGES else 'OFF'}] Compression auto images",
            "max_dimension": f"[OK] Max {MAX_IMAGE_DIMENSION}px par côté",
            "all_formats": "[OK] Images, PDF, videos, documents, etc.",
            "url_download": "[OK] Telechargement depuis URL externe",
            "return_binary": "[OK] Option retour binaire direct",
            "dual_api_keys": "[OK] Primary & Secondary keys",
            "auto_cleanup": f"[OK] Suppression apres {FILE_EXPIRY_HOURS}h"
        },
        "endpoints": {
            "POST /upload": "Upload un fichier (compression auto si image)",
            "POST /upload-from-url": "Telecharger depuis URL",
            "GET /download/{id}": "Telecharger un fichier",
            "GET /info/{id}": "Infos sur un fichier",
            "GET /health": "Verification sante",
            "GET /status": "Statut du service"
        }
    })

@app.route('/health')
def health():
    """Vérification santé"""
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "storage_count": len(TEMP_STORAGE),
        "max_file_size_mb": MAX_FILE_SIZE / (1024 * 1024),
        "max_image_size_mb": MAX_IMAGE_SIZE / (1024 * 1024)
    })

@app.route('/upload', methods=['POST'])
@app.route('/convert', methods=['POST'])
@require_api_key
def upload_file():
    """Upload n'importe quel fichier avec compression automatique pour images"""
    try:
        if 'file' not in request.files:
            return jsonify({"error": "Aucun fichier fourni"}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({"error": "Nom de fichier vide"}), 400
        
        filename = file.filename
        file_ext = get_file_extension(filename)
        is_image = file_ext in IMAGE_FORMATS
        
        # Lire le fichier
        file_content = file.read()
        original_size = len(file_content)
        
        print(f"[UPLOAD] Fichier: {filename}, Taille: {original_size/1024/1024:.2f}MB, Image: {is_image}")
        
        # Vérifier la taille selon le type
        max_size = MAX_IMAGE_SIZE if is_image else MAX_FILE_SIZE
        
        if original_size > max_size:
            return jsonify({
                "error": "Fichier trop volumineux",
                "file_size_mb": round(original_size / (1024 * 1024), 2),
                "max_size_mb": round(max_size / (1024 * 1024), 2),
                "file_type": "image" if is_image else "file"
            }), 413
        
        # Compression automatique pour les images si activée
        was_compressed = False
        compression_info = {}
        
        if is_image and AUTO_COMPRESS_IMAGES and original_size > 5 * 1024 * 1024:  # > 5MB
            print(f"[UPLOAD] Image volumineuse, tentative de compression...")
            file_content, was_compressed = compress_image(
                file_content, 
                filename,
                quality=85,
                max_dimension=MAX_IMAGE_DIMENSION
            )
            
            if was_compressed:
                new_size = len(file_content)
                compression_info = {
                    "compressed": True,
                    "original_size_mb": round(original_size / (1024 * 1024), 2),
                    "compressed_size_mb": round(new_size / (1024 * 1024), 2),
                    "compression_ratio": round((1 - new_size / original_size) * 100, 1)
                }
                print(f"[UPLOAD] Compression reussie: {compression_info}")
        
        # Stocker le fichier
        metadata = {'was_compressed': was_compressed}
        if compression_info:
            metadata['compression_info'] = compression_info
        
        download_url = store_file(file_content, filename, file.content_type, metadata)
        
        # Infos de retour
        file_info = {
            "success": True,
            "filename": sanitize_filename(filename),
            "original_filename": filename,
            "download_url": download_url,
            "file_id": download_url.split('/')[-1],
            "format": file_ext or "unknown",
            "size_bytes": len(file_content),
            "size_mb": round(len(file_content) / (1024 * 1024), 2),
            "content_type": file.content_type or mimetypes.guess_type(filename)[0],
            "uploaded_at": datetime.now().isoformat(),
            "expires_at": (datetime.now() + timedelta(hours=FILE_EXPIRY_HOURS)).isoformat(),
            "expiry_hours": FILE_EXPIRY_HOURS,
            "api_key_used": request.api_key_type,
            "is_image": is_image
        }
        
        if was_compressed:
            file_info["compression"] = compression_info
            file_info["message"] = f"[OK] Image compressée et uploadée! Gain: {compression_info['compression_ratio']}%"
        else:
            file_info["message"] = f"[OK] Fichier uploadé! URL valide pendant {FILE_EXPIRY_HOURS}h"
        
        return jsonify(file_info)
        
    except Exception as e:
        print(f"[ERROR] Erreur upload: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"Erreur: {str(e)}"}), 500

@app.route('/upload-from-url', methods=['POST'])
@require_api_key
def upload_from_url():
    """Télécharge un fichier depuis une URL externe"""
    try:
        content_type = request.headers.get('Content-Type', '')
        if 'application/json' in content_type:
            data = request.get_json()
        else:
            data = request.form.to_dict()
        
        if not data or 'url' not in data:
            return jsonify({"error": "URL manquante"}), 400
        
        file_url = data['url']
        return_binary = data.get('return_binary', False)
        if isinstance(return_binary, str):
            return_binary = return_binary.lower() in ['true', '1', 'yes']
        
        if not file_url.startswith(('http://', 'https://')):
            return jsonify({"error": "URL invalide"}), 400
        
        print(f"[URL] Telechargement: {file_url}")
        
        # Télécharger
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        response = requests.get(file_url, headers=headers, timeout=60, stream=True)
        response.raise_for_status()
        
        # Nom du fichier
        filename = 'download'
        if 'content-disposition' in response.headers:
            match = re.search(r'filename[^;=\n]*=([\'\"]?)([^\'\"\n]*)\1', response.headers['content-disposition'])
            if match:
                filename = match.group(2)
        
        if filename == 'download':
            url_path = file_url.split('?')[0]
            url_filename = url_path.split('/')[-1]
            if url_filename and '.' in url_filename:
                filename = url_filename
        
        if 'filename' in data and data['filename']:
            filename = data['filename']
        
        # Lire le contenu
        content = response.content
        file_ext = get_file_extension(filename)
        is_image = file_ext in IMAGE_FORMATS
        max_size = MAX_IMAGE_SIZE if is_image else MAX_FILE_SIZE
        
        if len(content) > max_size:
            return jsonify({
                "error": "Fichier trop volumineux",
                "file_size_mb": round(len(content) / (1024 * 1024), 2),
                "max_size_mb": round(max_size / (1024 * 1024), 2)
            }), 413
        
        content_type = response.headers.get('content-type', 'application/octet-stream')
        
        # Retour binaire direct si demandé
        if return_binary:
            return Response(
                content,
                mimetype=content_type,
                headers={
                    'Content-Disposition': f'attachment; filename="{sanitize_filename(filename)}"',
                    'Content-Length': str(len(content))
                }
            )
        
        # Compression auto si image volumineuse
        was_compressed = False
        compression_info = {}
        original_size = len(content)
        
        if is_image and AUTO_COMPRESS_IMAGES and original_size > 5 * 1024 * 1024:
            content, was_compressed = compress_image(content, filename, max_dimension=MAX_IMAGE_DIMENSION)
            if was_compressed:
                compression_info = {
                    "compressed": True,
                    "original_size_mb": round(original_size / (1024 * 1024), 2),
                    "compressed_size_mb": round(len(content) / (1024 * 1024), 2),
                    "compression_ratio": round((1 - len(content) / original_size) * 100, 1)
                }
        
        # Stocker
        metadata = {'was_compressed': was_compressed}
        if compression_info:
            metadata['compression_info'] = compression_info
        
        download_url = store_file(content, filename, content_type, metadata)
        
        result = {
            "success": True,
            "source_url": file_url,
            "filename": sanitize_filename(filename),
            "download_url": download_url,
            "file_id": download_url.split('/')[-1],
            "format": file_ext or "unknown",
            "size_bytes": len(content),
            "size_mb": round(len(content) / (1024 * 1024), 2),
            "content_type": content_type,
            "uploaded_at": datetime.now().isoformat(),
            "expires_at": (datetime.now() + timedelta(hours=FILE_EXPIRY_HOURS)).isoformat()
        }
        
        if was_compressed:
            result["compression"] = compression_info
        
        return jsonify(result)
        
    except Exception as e:
        print(f"[ERROR] upload-from-url: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@app.route('/download/<file_id>')
def download(file_id):
    """Télécharge un fichier stocké"""
    cleanup_old_files()
    
    if file_id not in TEMP_STORAGE:
        return jsonify({"error": "Fichier non trouvé ou expiré"}), 404
    
    file_data = TEMP_STORAGE[file_id]
    
    if datetime.now() > file_data['expiry']:
        del TEMP_STORAGE[file_id]
        return jsonify({"error": "Fichier expiré"}), 404
    
    content = base64.b64decode(file_data['content'])
    
    response = Response(
        content,
        mimetype=file_data['content_type'],
        headers={
            'Content-Disposition': f'attachment; filename="{file_data["filename"]}"',
            'Content-Length': str(len(content)),
            'Cache-Control': 'public, max-age=3600'
        }
    )
    
    return response

@app.route('/info/<file_id>')
def file_info(file_id):
    """Retourne les infos sur un fichier"""
    if file_id not in TEMP_STORAGE:
        return jsonify({"error": "Fichier non trouvé"}), 404
    
    file_data = TEMP_STORAGE[file_id]
    time_left = file_data['expiry'] - datetime.now()
    
    info = {
        "filename": file_data['filename'],
        "original_filename": file_data.get('original_filename', file_data['filename']),
        "content_type": file_data['content_type'],
        "size_bytes": file_data['size'],
        "size_mb": round(file_data['size'] / (1024 * 1024), 2),
        "created": file_data['created'].isoformat(),
        "expires_at": file_data['expiry'].isoformat(),
        "expires_in_hours": max(0, time_left.total_seconds() / 3600),
        "download_url": f"{BASE_URL}/download/{file_id}"
    }
    
    if file_data.get('was_compressed'):
        info["was_compressed"] = True
        info["compression_info"] = file_data.get('compression_info', {})
    
    return jsonify(info)

@app.route('/status')
def status():
    """Statut du service"""
    cleanup_old_files()
    
    total_size = sum(data['size'] for data in TEMP_STORAGE.values())
    
    files_list = []
    for file_id, data in list(TEMP_STORAGE.items())[:20]:
        time_left = data['expiry'] - datetime.now()
        files_list.append({
            "id": file_id,
            "filename": data['filename'],
            "size_mb": round(data['size'] / (1024 * 1024), 2),
            "type": data['content_type'],
            "compressed": data.get('was_compressed', False),
            "expires_in_hours": max(0, time_left.total_seconds() / 3600)
        })
    
    return jsonify({
        "status": "operational",
        "version": "2.0",
        "storage": {
            "files_count": len(TEMP_STORAGE),
            "total_size_mb": round(total_size / (1024 * 1024), 2),
            "files": files_list
        },
        "limits": {
            "max_file_size_mb": MAX_FILE_SIZE / (1024 * 1024),
            "max_image_size_mb": MAX_IMAGE_SIZE / (1024 * 1024),
            "max_image_dimension": MAX_IMAGE_DIMENSION,
            "auto_compress": AUTO_COMPRESS_IMAGES
        },
        "timestamp": datetime.now().isoformat()
    })

@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Endpoint non trouvé"}), 404

@app.errorhandler(500)
def server_error(e):
    return jsonify({"error": "Erreur serveur interne"}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    
    print("="*60)
    print("[FILE] STORAGE SERVER v2.0 - GROS FICHIERS + COMPRESSION")
    print("="*60)
    print(f"[OK] Port: {port}")
    print(f"[OK] Taille max fichiers: {MAX_FILE_SIZE/(1024*1024)} MB")
    print(f"[OK] Taille max images: {MAX_IMAGE_SIZE/(1024*1024)} MB")
    print(f"[OK] Dimension max images: {MAX_IMAGE_DIMENSION}px")
    print(f"[OK] Compression auto: {'OUI' if AUTO_COMPRESS_IMAGES else 'NON'}")
    print(f"[OK] Expiration: {FILE_EXPIRY_HOURS} heures")
    print(f"[OK] URL de base: {BASE_URL}")
    print("="*60)
    print("[KEY] CLES API:")
    print(f"   Primary: {PRIMARY_API_KEY[:30]}...{PRIMARY_API_KEY[-3:]}")
    print(f"   Secondary: {SECONDARY_API_KEY[:30]}...{SECONDARY_API_KEY[-3:]}")
    print("="*60)
    
    app.run(host='0.0.0.0', port=port, debug=False)
