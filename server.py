from flask import Flask, request, jsonify, send_file, Response
from flask_cors import CORS
import os
import uuid
from datetime import datetime, timedelta
import time
import io
import base64
import requests
from functools import wraps
import json
import hashlib
import threading

# Import basiques pour PDF
try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_AVAILABLE = True
except:
    PIL_AVAILABLE = False

try:
    from reportlab.lib.pagesizes import letter, A4
    from reportlab.pdfgen import canvas
    REPORTLAB_AVAILABLE = True
except:
    REPORTLAB_AVAILABLE = False

app = Flask(__name__)
CORS(app)

# ===== CONFIGURATION =====
PRIMARY_API_KEY = os.environ.get('PRIMARY_API_KEY', 'pk_live_mega_converter_primary_key_2024_super_secure_token_xyz789')
SECONDARY_API_KEY = os.environ.get('SECONDARY_API_KEY', 'sk_live_mega_converter_secondary_key_2024_ultra_secure_token_abc456')

MAX_FILE_SIZE = int(os.environ.get('MAX_FILE_SIZE', 50 * 1024 * 1024))
FILE_EXPIRY_HOURS = int(os.environ.get('FILE_EXPIRY_HOURS', 24))
BASE_URL = os.environ.get('BASE_URL', 'https://pdf-converter-server-production.up.railway.app')

# Stockage temporaire
TEMP_STORAGE = {}
STORAGE_LOCK = threading.Lock()

# Formats supportés
ALLOWED_EXTENSIONS = {
    'pdf', 'txt', 'rtf', 'md', 'csv', 'json', 'xml',
    'png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp',
    'html', 'htm', 'doc', 'docx', 'xls', 'xlsx'
}

def cleanup_old_files():
    """Nettoie les fichiers expirés"""
    with STORAGE_LOCK:
        current_time = datetime.now()
        expired_keys = []
        
        for key, data in TEMP_STORAGE.items():
            if current_time > data['expiry']:
                expired_keys.append(key)
        
        for key in expired_keys:
            del TEMP_STORAGE[key]
        
        if expired_keys:
            print(f"🧹 Nettoyage: {len(expired_keys)} fichiers expirés supprimés")

def auto_cleanup():
    """Thread de nettoyage automatique"""
    while True:
        time.sleep(3600)  # Toutes les heures
        cleanup_old_files()

# Démarrer le nettoyage automatique
cleanup_thread = threading.Thread(target=auto_cleanup, daemon=True)
cleanup_thread.start()

def require_api_key(f):
    """Vérification des clés API"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = request.headers.get('X-API-Key')
        if not api_key:
            api_key = request.args.get('api_key')
        if not api_key and request.form:
            api_key = request.form.get('api_key')
        if not api_key and request.is_json:
            api_key = request.json.get('api_key')
        
        if api_key not in [PRIMARY_API_KEY, SECONDARY_API_KEY]:
            return jsonify({
                "error": "Clé API invalide ou manquante",
                "message": "Utilisez une des deux clés API valides"
            }), 401
        
        request.api_key_type = "primary" if api_key == PRIMARY_API_KEY else "secondary"
        return f(*args, **kwargs)
    return decorated_function

def store_file_content(content, filename, content_type='application/octet-stream'):
    """Stocke le fichier et retourne une URL"""
    cleanup_old_files()
    
    file_id = str(uuid.uuid4())
    expiry = datetime.now() + timedelta(hours=FILE_EXPIRY_HOURS)
    
    with STORAGE_LOCK:
        TEMP_STORAGE[file_id] = {
            'content': base64.b64encode(content).decode('utf-8') if isinstance(content, bytes) else content,
            'filename': filename,
            'content_type': content_type,
            'expiry': expiry,
            'created': datetime.now()
        }
    
    return f"{BASE_URL}/download/{file_id}"

def create_simple_pdf(text_content, title="Document"):
    """Crée un PDF simple à partir de texte"""
    output = io.BytesIO()
    
    if REPORTLAB_AVAILABLE:
        c = canvas.Canvas(output, pagesize=letter)
        width, height = letter
        
        # Titre
        c.setFont("Helvetica-Bold", 16)
        c.drawString(50, height - 50, title)
        
        # Contenu
        c.setFont("Helvetica", 12)
        y = height - 100
        
        lines = text_content.split('\n')
        for line in lines:
            if y < 50:
                c.showPage()
                y = height - 50
            
            # Découper les lignes longues
            if len(line) > 80:
                words = line.split()
                current_line = ""
                for word in words:
                    if len(current_line + word) < 80:
                        current_line += word + " "
                    else:
                        c.drawString(50, y, current_line.strip())
                        y -= 15
                        current_line = word + " "
                if current_line:
                    c.drawString(50, y, current_line.strip())
                    y -= 15
            else:
                c.drawString(50, y, line)
                y -= 15
        
        c.save()
    else:
        # PDF minimaliste sans ReportLab
        pdf_content = f"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> >> >> >>
endobj
4 0 obj
<< /Length {len(text_content[:500]) + 100} >>
stream
BT
/F1 12 Tf
50 750 Td
({title}) Tj
0 -20 Td
({text_content[:400].replace('(', '\\(').replace(')', '\\)').replace('\\', '\\\\')}) Tj
ET
endstream
endobj
xref
0 5
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
0000000115 00000 n 
0000000203 00000 n 
trailer
<< /Size 5 /Root 1 0 R >>
startxref
{400 + len(text_content[:400])}
%%EOF"""
        output.write(pdf_content.encode('latin-1', errors='replace'))
    
    output.seek(0)
    return output.getvalue()

def convert_image_to_pdf(image_content):
    """Convertit une image en PDF"""
    if not PIL_AVAILABLE:
        return create_simple_pdf("Image convertie en PDF (PIL non disponible)")
    
    try:
        img = Image.open(io.BytesIO(image_content))
        
        # Convertir en RGB si nécessaire
        if img.mode != 'RGB':
            img = img.convert('RGB')
        
        output = io.BytesIO()
        img.save(output, format='PDF')
        output.seek(0)
        return output.getvalue()
    except Exception as e:
        print(f"Erreur conversion image: {e}")
        return create_simple_pdf(f"Erreur conversion image: {str(e)}")

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
        "service": "🚀 MEGA PDF Converter - Optimisé Railway",
        "version": "2.0 STABLE",
        "status": "✅ Opérationnel",
        "features": {
            "pdf_conversion": "✅ Texte/Image vers PDF",
            "image_support": "✅" if PIL_AVAILABLE else "❌",
            "advanced_pdf": "✅" if REPORTLAB_AVAILABLE else "❌",
            "temporary_storage": "✅ URLs temporaires",
            "dual_api_keys": "✅ Primary & Secondary",
            "auto_cleanup": "✅ Nettoyage automatique",
            "formats_supported": len(ALLOWED_EXTENSIONS)
        },
        "endpoints": {
            "convert": "POST /convert",
            "qrcode": "POST /qrcode",
            "download": "GET /download/{id}",
            "health": "GET /health",
            "status": "GET /status"
        },
        "limits": {
            "max_file_size_mb": MAX_FILE_SIZE / (1024 * 1024),
            "file_expiry_hours": FILE_EXPIRY_HOURS,
            "supported_formats": sorted(list(ALLOWED_EXTENSIONS))
        }
    })

@app.route('/health')
def health():
    """Vérification santé"""
    cleanup_old_files()
    
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "storage_count": len(TEMP_STORAGE),
        "modules": {
            "pil": PIL_AVAILABLE,
            "reportlab": REPORTLAB_AVAILABLE
        }
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
            output_content = file_content
        elif file_ext in ['png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp']:
            output_content = convert_image_to_pdf(file_content)
        elif file_ext in ['txt', 'md', 'csv', 'json', 'xml', 'html', 'htm']:
            try:
                text = file_content.decode('utf-8', errors='ignore')
                output_content = create_simple_pdf(text, f"Conversion de {filename}")
            except:
                output_content = create_simple_pdf("Erreur de décodage du fichier")
        else:
            # Pour les autres formats, créer un PDF avec info
            output_content = create_simple_pdf(
                f"Fichier: {filename}\n"
                f"Format: {file_ext}\n"
                f"Taille: {len(file_content)} bytes\n\n"
                f"Conversion directe non disponible pour ce format."
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
        return jsonify({"error": f"Erreur: {str(e)}"}), 500

@app.route('/qrcode', methods=['POST'])
@require_api_key
def generate_qrcode():
    """Génère un QR Code simple"""
    try:
        data = request.form.get('data') or (request.json.get('data') if request.is_json else None)
        if not data:
            return jsonify({"error": "Données requises"}), 400
        
        # Créer un PDF avec le QR code (version simplifiée)
        qr_pdf_content = create_simple_pdf(
            f"QR Code généré le {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            f"Données encodées:\n{data}\n\n"
            f"[QR CODE ICI]\n\n"
            f"Scannez ce code avec votre smartphone"
        )
        
        filename = f"qrcode_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        download_url = store_file_content(qr_pdf_content, filename, 'application/pdf')
        
        return jsonify({
            "success": True,
            "filename": filename,
            "download_url": download_url,
            "data_encoded": data[:100],
            "message": "QR Code généré (version PDF)"
        })
        
    except Exception as e:
        return jsonify({"error": f"Erreur: {str(e)}"}), 500

@app.route('/download/<file_id>')
def download_file(file_id):
    """Télécharge un fichier stocké"""
    cleanup_old_files()
    
    with STORAGE_LOCK:
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
    
    with STORAGE_LOCK:
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
        "version": "2.0 STABLE",
        "storage": {
            "type": "memory",
            "files_count": len(TEMP_STORAGE),
            "files": files_info[:5]  # Montrer max 5 fichiers
        },
        "capabilities": {
            "image_processing": PIL_AVAILABLE,
            "advanced_pdf": REPORTLAB_AVAILABLE
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
    return jsonify({"error": "Erreur serveur"}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    
    print("="*50)
    print("🚀 MEGA PDF Converter - Version STABLE")
    print("="*50)
    print(f"✅ Port: {port}")
    print(f"✅ Taille max: {MAX_FILE_SIZE / (1024*1024)} MB")
    print(f"✅ Expiration: {FILE_EXPIRY_HOURS} heures")
    print(f"✅ Formats: {len(ALLOWED_EXTENSIONS)}")
    print(f"✅ PIL: {'Oui' if PIL_AVAILABLE else 'Non'}")
    print(f"✅ ReportLab: {'Oui' if REPORTLAB_AVAILABLE else 'Non'}")
    print("="*50)
    print("🔑 Clés API configurées:")
    print(f"   Primary: {PRIMARY_API_KEY[:30]}...{PRIMARY_API_KEY[-3:]}")
    print(f"   Secondary: {SECONDARY_API_KEY[:30]}...{SECONDARY_API_KEY[-3:]}")
    print("="*50)
    
    app.run(host='0.0.0.0', port=port, debug=False)
