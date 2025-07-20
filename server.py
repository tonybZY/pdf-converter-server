from flask import Flask, request, jsonify, Response
from flask_cors import CORS
import os
import uuid
from datetime import datetime, timedelta
import io
import base64
from functools import wraps
import json

app = Flask(__name__)
CORS(app)

# Configuration
PRIMARY_API_KEY = os.environ.get('PRIMARY_API_KEY', 'pk_live_mega_converter_primary_key_2024_super_secure_token_xyz789')
SECONDARY_API_KEY = os.environ.get('SECONDARY_API_KEY', 'sk_live_mega_converter_secondary_key_2024_ultra_secure_token_abc456')
MAX_FILE_SIZE = int(os.environ.get('MAX_FILE_SIZE', 50 * 1024 * 1024))
FILE_EXPIRY_HOURS = int(os.environ.get('FILE_EXPIRY_HOURS', 24))
BASE_URL = os.environ.get('BASE_URL', 'https://pdf-converter-server-production.up.railway.app')

# Stockage temporaire
TEMP_STORAGE = {}

# Formats supportés
ALLOWED_EXTENSIONS = {
    'pdf', 'txt', 'rtf', 'md', 'csv', 'json', 'xml',
    'png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp',
    'html', 'htm', 'doc', 'docx', 'xls', 'xlsx'
}

def cleanup_old_files():
    """Nettoie les fichiers expirés"""
    current_time = datetime.now()
    expired_keys = []
    
    for key, data in TEMP_STORAGE.items():
        if current_time > data['expiry']:
            expired_keys.append(key)
    
    for key in expired_keys:
        del TEMP_STORAGE[key]

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

def create_pdf_from_text(text, title="Document"):
    """Crée un PDF à partir de texte"""
    # Nettoyer le texte
    text = text.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
    title = title.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
    
    # Découper le texte en lignes
    lines = []
    words = text.split()
    current_line = ""
    
    for word in words:
        if len(current_line + word) < 70:
            current_line += word + " "
        else:
            if current_line:
                lines.append(current_line.strip())
            current_line = word + " "
    if current_line:
        lines.append(current_line.strip())
    
    # Construire le contenu du stream
    stream_content = f"""BT
/F1 16 Tf
50 750 Td
({title}) Tj
0 -30 Td
/F1 12 Tf"""
    
    y_position = 0
    for line in lines[:40]:  # Limiter à 40 lignes pour une page
        stream_content += f"""
0 -20 Td
({line}) Tj"""
        y_position += 20
    
    stream_content += """
ET"""
    
    stream_length = len(stream_content)
    
    # Créer le PDF
    pdf = f"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>
endobj
4 0 obj
<< /Length {stream_length} >>
stream
{stream_content}
endstream
endobj
5 0 obj
<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>
endobj
xref
0 6
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
0000000115 00000 n 
0000000229 00000 n 
0000{229 + stream_length + 50:010} 00000 n 
trailer
<< /Size 6 /Root 1 0 R >>
startxref
{229 + stream_length + 128}
%%EOF"""
    
    return pdf.encode('latin-1', errors='ignore')

def create_pdf_from_image_placeholder(filename):
    """Crée un PDF placeholder pour les images"""
    return create_pdf_from_text(
        f"Image: {filename}\n\nLa conversion d'images nécessite des librairies supplémentaires.\nVotre image a été reçue mais ne peut pas être convertie en PDF sur ce serveur.",
        "Placeholder Image PDF"
    )

def store_file_content(content, filename, content_type='application/octet-stream'):
    """Stocke le fichier et retourne une URL"""
    cleanup_old_files()
    
    file_id = str(uuid.uuid4())
    expiry = datetime.now() + timedelta(hours=FILE_EXPIRY_HOURS)
    
    TEMP_STORAGE[file_id] = {
        'content': base64.b64encode(content).decode('utf-8') if isinstance(content, bytes) else content,
        'filename': filename,
        'content_type': content_type,
        'expiry': expiry,
        'created': datetime.now()
    }
    
    return f"{BASE_URL}/download/{file_id}"

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_file_extension(filename):
    if not filename or '.' not in filename:
        return None
    return filename.rsplit('.', 1)[1].lower()

# ===== ROUTES =====

@app.route('/')
def home():
    """Page d'accueil"""
    return jsonify({
        "service": "🚀 PDF Converter API - Production Ready",
        "version": "1.0",
        "status": "✅ Opérationnel",
        "features": {
            "pdf_conversion": "✅ Conversion vers PDF",
            "text_formats": "✅ TXT, CSV, JSON, XML, HTML",
            "image_formats": "⚠️ Images → PDF placeholder",
            "temporary_storage": "✅ URLs temporaires 24h",
            "dual_api_keys": "✅ Primary & Secondary keys",
            "auto_cleanup": "✅ Nettoyage automatique"
        },
        "endpoints": {
            "POST /convert": "Convertir un fichier en PDF",
            "GET /download/{id}": "Télécharger un fichier",
            "GET /health": "Vérification santé",
            "GET /status": "Statut du service"
        },
        "authentication": "Header 'X-API-Key' ou paramètre 'api_key'"
    })

@app.route('/health')
def health():
    """Vérification santé"""
    cleanup_old_files()
    
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "storage_count": len(TEMP_STORAGE)
    })

@app.route('/convert', methods=['POST'])
@require_api_key
def convert():
    """Conversion universelle vers PDF"""
    try:
        if 'file' not in request.files:
            return jsonify({"error": "Aucun fichier fourni"}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({"error": "Nom de fichier vide"}), 400
        
        if not allowed_file(file.filename):
            return jsonify({
                "error": "Format non supporté",
                "supported": sorted(list(ALLOWED_EXTENSIONS))
            }), 400
        
        # Lire le fichier
        file_content = file.read()
        if len(file_content) > MAX_FILE_SIZE:
            return jsonify({
                "error": "Fichier trop volumineux",
                "max_size_mb": MAX_FILE_SIZE / (1024 * 1024)
            }), 413
        
        filename = file.filename
        file_ext = get_file_extension(filename)
        
        # Conversion selon le type
        if file_ext == 'pdf':
            # Si c'est déjà un PDF, le retourner tel quel
            output_content = file_content
        elif file_ext in ['png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp']:
            # Pour les images, créer un PDF placeholder
            output_content = create_pdf_from_image_placeholder(filename)
        else:
            # Pour tous les autres formats, convertir en texte puis PDF
            try:
                text = file_content.decode('utf-8', errors='ignore')
                if file_ext == 'json':
                    # Formatter le JSON
                    try:
                        json_data = json.loads(text)
                        text = json.dumps(json_data, indent=2, ensure_ascii=False)
                    except:
                        pass
                elif file_ext == 'csv':
                    # Formatter le CSV
                    lines = text.split('\n')
                    formatted_lines = []
                    for line in lines[:50]:  # Limiter aux 50 premières lignes
                        if line.strip():
                            formatted_lines.append(line.strip())
                    text = '\n'.join(formatted_lines)
                
                output_content = create_pdf_from_text(text, f"Conversion de {filename}")
            except:
                output_content = create_pdf_from_text(
                    f"Erreur lors de la lecture du fichier {filename}\nFormat: {file_ext}\nTaille: {len(file_content)} bytes",
                    "Erreur de conversion"
                )
        
        # Stocker le fichier
        output_filename = f"{os.path.splitext(filename)[0]}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        download_url = store_file_content(output_content, output_filename, 'application/pdf')
        
        return jsonify({
            "success": True,
            "filename": output_filename,
            "download_url": download_url,
            "original_format": file_ext,
            "file_size_mb": round(len(output_content) / (1024 * 1024), 2),
            "api_key_used": request.api_key_type,
            "expires_at": (datetime.now() + timedelta(hours=FILE_EXPIRY_HOURS)).isoformat(),
            "expiry_hours": FILE_EXPIRY_HOURS,
            "message": f"✅ Conversion réussie! Le fichier expire dans {FILE_EXPIRY_HOURS}h"
        })
        
    except Exception as e:
        print(f"Erreur conversion: {e}")
        return jsonify({"error": f"Erreur de conversion: {str(e)}"}), 500

@app.route('/download/<file_id>')
def download(file_id):
    """Télécharge un fichier stocké"""
    cleanup_old_files()
    
    if file_id not in TEMP_STORAGE:
        return jsonify({"error": "Fichier non trouvé"}), 404
    
    file_data = TEMP_STORAGE[file_id]
    
    # Vérifier l'expiration
    if datetime.now() > file_data['expiry']:
        del TEMP_STORAGE[file_id]
        return jsonify({"error": "Fichier expiré"}), 404
    
    # Décoder le contenu
    content = base64.b64decode(file_data['content'])
    
    # Créer la réponse
    response = Response(
        content,
        mimetype=file_data['content_type'],
        headers={
            'Content-Disposition': f'attachment; filename="{file_data["filename"]}"',
            'Content-Length': str(len(content))
        }
    )
    
    return response

@app.route('/status')
def status():
    """Statut du service"""
    cleanup_old_files()
    
    files_info = []
    for file_id, data in TEMP_STORAGE.items():
        time_left = data['expiry'] - datetime.now()
        files_info.append({
            "filename": data['filename'],
            "created": data['created'].isoformat(),
            "expires_in_hours": max(0, time_left.total_seconds() / 3600)
        })
    
    return jsonify({
        "status": "operational",
        "version": "1.0",
        "storage": {
            "type": "memory",
            "files_count": len(TEMP_STORAGE),
            "files": files_info[:10]
        },
        "limits": {
            "max_file_size_mb": MAX_FILE_SIZE / (1024 * 1024),
            "file_expiry_hours": FILE_EXPIRY_HOURS
        },
        "timestamp": datetime.now().isoformat()
    })

# Gestion des erreurs
@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Endpoint non trouvé"}), 404

@app.errorhandler(500)
def server_error(e):
    return jsonify({"error": "Erreur serveur interne"}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    
    print("="*60)
    print("🚀 PDF CONVERTER API - PRODUCTION READY")
    print("="*60)
    print(f"✅ Port: {port}")
    print(f"✅ Taille max: {MAX_FILE_SIZE / (1024*1024)} MB")
    print(f"✅ Expiration: {FILE_EXPIRY_HOURS} heures")
    print(f"✅ Formats: {len(ALLOWED_EXTENSIONS)}")
    print(f"✅ URL de base: {BASE_URL}")
    print("="*60)
    print("🔑 CLÉS API:")
    print(f"   Primary: {PRIMARY_API_KEY[:30]}...{PRIMARY_API_KEY[-3:]}")
    print(f"   Secondary: {SECONDARY_API_KEY[:30]}...{SECONDARY_API_KEY[-3:]}")
    print("="*60)
    print("📡 Endpoints disponibles:")
    print("   GET  / - Page d'accueil")
    print("   GET  /health - Vérification santé")
    print("   POST /convert - Conversion vers PDF")
    print("   GET  /download/{id} - Téléchargement")
    print("   GET  /status - Statut du service")
    print("="*60)
    
    app.run(host='0.0.0.0', port=port, debug=False)
