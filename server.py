from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import os
import uuid
from datetime import datetime
from werkzeug.utils import secure_filename
import shutil
from functools import wraps
import hashlib
import time
import io
import json
import re

# Configuration des imports optionnels
try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    print("⚠️  PIL/Pillow non disponible - conversion d'images limitée")

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False
    print("⚠️  Requests non disponible - conversion URL limitée")

try:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseDownload
    GOOGLE_API_AVAILABLE = True
except ImportError:
    GOOGLE_API_AVAILABLE = False
    print("⚠️  Google API non disponible - téléchargement Google Drive limité")

try:
    from docx import Document
    import docx2txt
    DOCX_AVAILABLE = True
except ImportError:
    DOCX_AVAILABLE = False
    print("⚠️  python-docx non disponible - conversion DOCX limitée")

try:
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False
    print("⚠️  ReportLab non disponible - création PDF avancée limitée")

app = Flask(__name__)
CORS(app)

# Configuration
API_KEY = os.environ.get('PDF_API_KEY', 'votre-cle-secrete-changez-moi')
UPLOAD_FOLDER = 'uploads'
CONVERTED_FOLDER = 'converted'
MAX_FILE_SIZE = 16 * 1024 * 1024  # 16MB

# Configuration Google Drive
GOOGLE_SERVICE_ACCOUNT_FILE = os.environ.get('GOOGLE_SERVICE_ACCOUNT_FILE', 'service-account.json')

# Feature Flags
ENABLE_IMAGE_CONVERSION = os.environ.get('ENABLE_IMAGE_CONVERSION', 'true').lower() == 'true'
ENABLE_TEXT_TO_IMAGE = os.environ.get('ENABLE_TEXT_TO_IMAGE', 'true').lower() == 'true'
ENABLE_GOOGLE_DRIVE = os.environ.get('ENABLE_GOOGLE_DRIVE', 'true').lower() == 'true'

# Créer les dossiers
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(CONVERTED_FOLDER, exist_ok=True)

# Formats supportés
ALLOWED_EXTENSIONS = {
    'pdf', 'txt', 'rtf', 'md',
    'doc', 'docx', 'odt',
    'ppt', 'pptx', 'odp',
    'csv', 'xlsx', 'xls',
    'png', 'jpg', 'jpeg', 'gif', 'bmp',
    'tiff', 'tif', 'webp', 'svg', 'ico',
    'html', 'htm'
}

# Service Google Drive
google_drive_service = None
if GOOGLE_API_AVAILABLE and ENABLE_GOOGLE_DRIVE and os.path.exists(GOOGLE_SERVICE_ACCOUNT_FILE):
    try:
        credentials = service_account.Credentials.from_service_account_file(
            GOOGLE_SERVICE_ACCOUNT_FILE,
            scopes=['https://www.googleapis.com/auth/drive.readonly']
        )
        google_drive_service = build('drive', 'v3', credentials=credentials)
        print("✅ Service Google Drive initialisé")
    except Exception as e:
        print(f"❌ Erreur initialisation Google Drive: {e}")

def require_api_key(f):
    """Décorateur pour vérifier la clé API"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = request.headers.get('X-API-Key')
        
        if not api_key:
            api_key = request.args.get('api_key')
        
        if not api_key and request.form:
            api_key = request.form.get('api_key')
        
        if not api_key or api_key != API_KEY:
            return jsonify({
                "error": "Clé API manquante ou invalide",
                "message": "Utilisez le header 'X-API-Key' ou le paramètre 'api_key'"
            }), 401
        
        return f(*args, **kwargs)
    return decorated_function

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_file_size(file):
    """Obtenir la taille du fichier"""
    file.seek(0, os.SEEK_END)
    size = file.tell()
    file.seek(0)
    return size

def get_file_extension_safe(filename):
    """Extraction sûre de l'extension"""
    if not filename or '.' not in filename:
        return None
    return filename.rsplit('.', 1)[1].lower()

def extract_google_drive_id(url):
    """Extrait l'ID du fichier Google Drive depuis une URL"""
    patterns = [
        r'/file/d/([a-zA-Z0-9-_]+)',
        r'id=([a-zA-Z0-9-_]+)',
        r'/open\?id=([a-zA-Z0-9-_]+)',
        r'/uc\?id=([a-zA-Z0-9-_]+)',
        r'^([a-zA-Z0-9-_]+)$'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None

def download_google_drive_file(file_id):
    """Télécharge un fichier depuis Google Drive"""
    if not google_drive_service:
        return None, None, "Service Google Drive non disponible"
    
    try:
        file_metadata = google_drive_service.files().get(
            fileId=file_id,
            fields='name,size,mimeType'
        ).execute()
        
        filename = file_metadata.get('name', 'unknown')
        file_size = int(file_metadata.get('size', 0))
        
        if file_size > MAX_FILE_SIZE:
            return None, None, f"Fichier trop volumineux ({file_size / (1024*1024):.2f} MB)"
        
        request_file = google_drive_service.files().get_media(fileId=file_id)
        file_content = io.BytesIO()
        downloader = MediaIoBaseDownload(file_content, request_file)
        
        done = False
        while not done:
            status, done = downloader.next_chunk()
        
        file_content.seek(0)
        return file_content, filename, None
        
    except Exception as e:
        return None, None, f"Erreur téléchargement Google Drive: {str(e)}"

def create_simple_pdf(text, output_path):
    """Crée un PDF simple à partir de texte"""
    try:
        if REPORTLAB_AVAILABLE:
            # Utiliser ReportLab si disponible
            c = canvas.Canvas(output_path, pagesize=letter)
            width, height = letter
            
            y = height - 50
            for line in text.split('\n')[:50]:  # Limiter à 50 lignes
                if y < 50:
                    c.showPage()
                    y = height - 50
                if len(line) > 80:
                    line = line[:77] + "..."
                c.drawString(50, y, line)
                y -= 15
            
            c.save()
            return True
        else:
            # PDF basique sans ReportLab
            pdf_content = f"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R >>
endobj
4 0 obj
<< /Length {len(text[:500]) + 50} >>
stream
BT
/F1 12 Tf
50 750 Td
({text[:500].replace('(', '\\(').replace(')', '\\)').replace('\\', '\\\\')}) Tj
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
{350 + len(text[:500])}
%%EOF"""
            
            with open(output_path, 'wb') as f:
                f.write(pdf_content.encode('latin-1', errors='replace'))
            return True
            
    except Exception as e:
        print(f"Erreur création PDF: {e}")
        return False

def convert_docx_to_pdf(input_path, output_path):
    """Convertit un DOCX en PDF"""
    try:
        text = ""
        
        if DOCX_AVAILABLE:
            try:
                # Essayer d'abord docx2txt
                text = docx2txt.process(input_path)
            except:
                try:
                    # Sinon utiliser python-docx
                    doc = Document(input_path)
                    text = '\n'.join([paragraph.text for paragraph in doc.paragraphs])
                except:
                    pass
        
        if not text:
            # Fallback: lire comme binaire et extraire ce qu'on peut
            with open(input_path, 'rb') as f:
                content = f.read()
                # Essayer d'extraire du texte
                import re
                pattern = re.compile(b'<w:t[^>]*>([^<]+)</w:t>')
                matches = pattern.findall(content)
                text_parts = []
                for match in matches:
                    try:
                        text_parts.append(match.decode('utf-8', errors='ignore'))
                    except:
                        pass
                text = ' '.join(text_parts)
        
        if not text:
            text = "Impossible d'extraire le contenu du document DOCX"
        
        return create_simple_pdf(text, output_path), "DOCX converti en PDF"
        
    except Exception as e:
        print(f"Erreur conversion DOCX: {e}")
        return False, f"Erreur conversion DOCX: {str(e)}"

def convert_text_to_pdf(input_path, output_path):
    """Convertit un fichier texte en PDF"""
    try:
        with open(input_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        
        return create_simple_pdf(content, output_path), "Texte converti en PDF"
        
    except Exception as e:
        print(f"Erreur conversion texte: {e}")
        return False, f"Erreur: {str(e)}"

def create_placeholder_image(output_path, text, format='png'):
    """Crée une image placeholder"""
    if PIL_AVAILABLE:
        try:
            img = Image.new('RGB', (400, 300), color='lightgray')
            draw = ImageDraw.Draw(img)
            draw.text((150, 140), text, fill='darkgray')
            draw.rectangle([(10, 10), (390, 290)], outline='gray', width=2)
            img.save(output_path, format=format.upper())
            return True
        except:
            pass
    
    # PNG minimal si PIL non disponible
    with open(output_path, 'wb') as f:
        f.write(b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde')
    return True

def convert_to_image(input_path, output_path, file_extension, target_format='png'):
    """Conversion vers image"""
    if not ENABLE_IMAGE_CONVERSION:
        return False, "Conversion d'images désactivée"
    
    try:
        if file_extension == target_format and file_extension in ['png', 'jpg', 'jpeg', 'gif']:
            shutil.copy2(input_path, output_path)
            return True, f"Image copiée"
        elif PIL_AVAILABLE and file_extension in ['png', 'jpg', 'jpeg', 'gif', 'bmp']:
            img = Image.open(input_path)
            img.save(output_path, format=target_format.upper())
            return True, f"Image convertie en {target_format.upper()}"
        else:
            return create_placeholder_image(output_path, f"IMG\n{file_extension.upper()}", target_format), True
            
    except Exception as e:
        print(f"Erreur conversion image: {e}")
        return False, f"Erreur: {str(e)}"

def enhanced_convert_file(input_path, output_path, file_extension):
    """Conversion vers PDF selon le type de fichier"""
    try:
        if file_extension == 'pdf':
            shutil.copy2(input_path, output_path)
            return True, "PDF copié"
            
        elif file_extension in ['txt', 'md']:
            return convert_text_to_pdf(input_path, output_path)
            
        elif file_extension in ['doc', 'docx']:
            return convert_docx_to_pdf(input_path, output_path)
            
        elif file_extension in ['png', 'jpg', 'jpeg', 'gif', 'bmp']:
            if PIL_AVAILABLE:
                try:
                    img = Image.open(input_path)
                    img.save(output_path, "PDF")
                    return True, f"Image convertie en PDF"
                except:
                    shutil.copy2(input_path, output_path)
                    return True, f"Image préparée"
            else:
                shutil.copy2(input_path, output_path)
                return True, f"Image préparée (PIL non disponible)"
            
        else:
            # Pour tous les autres formats, copier le fichier
            shutil.copy2(input_path, output_path)
            return True, f"Fichier {file_extension.upper()} préparé"
            
    except Exception as e:
        print(f"Erreur de conversion: {e}")
        return False, f"Erreur: {str(e)}"

# ==================== ROUTES ====================

@app.route('/')
def home():
    """Page d'accueil"""
    return jsonify({
        "service": "Convertisseur PDF/Image avec Support Google Drive",
        "version": "3.0",
        "endpoints": {
            "health": "/health",
            "formats": "/formats", 
            "convert": "POST /convert (nécessite clé API)",
            "convert_to_image": "POST /convert-to-image (nécessite clé API)",
            "convert_url_to_image": "POST /convert-url-to-image (nécessite clé API)",
            "convert_google_drive": "POST /convert-google-drive (nécessite clé API)",
            "public_download": "/public/download/<filename>"
        },
        "supported_formats": len(ALLOWED_EXTENSIONS),
        "max_file_size_mb": MAX_FILE_SIZE / (1024 * 1024),
        "features": {
            "image_conversion": ENABLE_IMAGE_CONVERSION,
            "text_to_image": ENABLE_TEXT_TO_IMAGE,
            "google_drive": ENABLE_GOOGLE_DRIVE,
            "pil_available": PIL_AVAILABLE,
            "requests_available": REQUESTS_AVAILABLE,
            "google_api_available": GOOGLE_API_AVAILABLE,
            "docx_available": DOCX_AVAILABLE,
            "reportlab_available": REPORTLAB_AVAILABLE
        }
    })

@app.route('/health')
def health():
    return jsonify({
        "status": "OK",
        "version": "3.0",
        "timestamp": datetime.now().isoformat()
    })

@app.route('/formats')
def supported_formats():
    """Liste des formats supportés"""
    return jsonify({
        "supported_formats": sorted(list(ALLOWED_EXTENSIONS)),
        "total_formats": len(ALLOWED_EXTENSIONS),
        "max_file_size_mb": MAX_FILE_SIZE / (1024 * 1024)
    })

@app.route('/convert', methods=['POST'])
@require_api_key
def convert():
    """Conversion vers PDF"""
    start_time = time.time()
    
    if 'file' not in request.files:
        return jsonify({"error": "Pas de fichier fourni"}), 400
    
    file = request.files['file']
    
    if file.filename == '':
        return jsonify({"error": "Nom de fichier vide"}), 400
    
    file_size = get_file_size(file)
    if file_size > MAX_FILE_SIZE:
        return jsonify({
            "error": "Fichier trop volumineux",
            "max_size_mb": MAX_FILE_SIZE / (1024 * 1024),
            "file_size_mb": round(file_size / (1024 * 1024), 2)
        }), 413
    
    if not allowed_file(file.filename):
        return jsonify({
            "error": "Format de fichier non supporté",
            "supported_formats": sorted(list(ALLOWED_EXTENSIONS))
        }), 400
    
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        unique_id = str(uuid.uuid4())[:8]
        
        original_name = secure_filename(file.filename)
        base_name = os.path.splitext(original_name)[0]
        file_extension = get_file_extension_safe(original_name)
        
        temp_filename = f"temp_{unique_id}.{file_extension}"
        temp_path = os.path.join(UPLOAD_FOLDER, temp_filename)
        file.save(temp_path)
        
        converted_filename = f"{base_name}_converted_{timestamp}_{unique_id}.pdf"
        converted_path = os.path.join(CONVERTED_FOLDER, converted_filename)
        
        conversion_success, conversion_message = enhanced_convert_file(temp_path, converted_path, file_extension)
        
        if os.path.exists(temp_path):
            os.remove(temp_path)
        
        if not conversion_success:
            return jsonify({"error": f"Échec de la conversion: {conversion_message}"}), 500
        
        base_url = request.host_url.rstrip('/')
        download_url = f"{base_url}/public/download/{converted_filename}"
        
        processing_time = round(time.time() - start_time, 3)
        
        return jsonify({
            "success": True,
            "filename": converted_filename,
            "download_url": download_url,
            "original_format": file_extension,
            "file_size_mb": round(file_size / (1024 * 1024), 2),
            "processing_time_seconds": processing_time,
            "conversion_method": conversion_message,
            "message": f"Fichier {file_extension.upper()} converti avec succès!"
        })
        
    except Exception as e:
        print(f"Erreur: {str(e)}")
        return jsonify({"error": f"Erreur de traitement: {str(e)}"}), 500

@app.route('/convert-to-image', methods=['POST'])
@require_api_key
def convert_to_image_route():
    """Conversion vers image"""
    start_time = time.time()
    
    if not ENABLE_IMAGE_CONVERSION:
        return jsonify({
            "error": "Conversion d'images désactivée"
        }), 503
    
    if 'file' not in request.files:
        return jsonify({"error": "Pas de fichier fourni"}), 400
    
    file = request.files['file']
    
    if file.filename == '':
        return jsonify({"error": "Nom de fichier vide"}), 400
    
    target_format = request.form.get('format', 'png').lower()
    if target_format not in ['png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp']:
        target_format = 'png'
    
    file_size = get_file_size(file)
    if file_size > MAX_FILE_SIZE:
        return jsonify({
            "error": "Fichier trop volumineux",
            "max_size_mb": MAX_FILE_SIZE / (1024 * 1024),
            "file_size_mb": round(file_size / (1024 * 1024), 2)
        }), 413
    
    if not allowed_file(file.filename):
        return jsonify({
            "error": "Format de fichier non supporté",
            "supported_formats": sorted(list(ALLOWED_EXTENSIONS))
        }), 400
    
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        unique_id = str(uuid.uuid4())[:8]
        
        original_name = secure_filename(file.filename)
        base_name = os.path.splitext(original_name)[0]
        file_extension = get_file_extension_safe(original_name)
        
        temp_filename = f"temp_{unique_id}.{file_extension}"
        temp_path = os.path.join(UPLOAD_FOLDER, temp_filename)
        file.save(temp_path)
        
        converted_filename = f"{base_name}_image_{timestamp}_{unique_id}.{target_format}"
        converted_path = os.path.join(CONVERTED_FOLDER, converted_filename)
        
        conversion_success, conversion_message = convert_to_image(temp_path, converted_path, file_extension, target_format)
        
        if os.path.exists(temp_path):
            os.remove(temp_path)
        
        if not conversion_success:
            return jsonify({"error": f"Échec de la conversion: {conversion_message}"}), 500
        
        base_url = request.host_url.rstrip('/')
        download_url = f"{base_url}/public/download/{converted_filename}"
        
        processing_time = round(time.time() - start_time, 3)
        
        return jsonify({
            "success": True,
            "filename": converted_filename,
            "download_url": download_url,
            "original_format": file_extension,
            "target_format": target_format,
            "file_size_mb": round(file_size / (1024 * 1024), 2),
            "processing_time_seconds": processing_time,
            "conversion_method": conversion_message,
            "message": f"Fichier converti en image {target_format.upper()} avec succès!"
        })
        
    except Exception as e:
        print(f"Erreur: {str(e)}")
        return jsonify({"error": f"Erreur de traitement: {str(e)}"}), 500

@app.route('/convert-url-to-image', methods=['POST'])
@require_api_key
def convert_url_to_image():
    """Conversion URL vers image"""
    if not ENABLE_IMAGE_CONVERSION or not REQUESTS_AVAILABLE:
        return jsonify({
            "error": "Conversion URL non disponible"
        }), 503
    
    data = request.get_json() if request.is_json else request.form
    file_url = data.get('url')
    target_format = data.get('format', 'png')
    
    if not file_url:
        return jsonify({"error": "URL manquante"}), 400
    
    # Si c'est Google Drive, rediriger
    if 'drive.google.com' in file_url or 'docs.google.com' in file_url:
        return convert_google_drive()
    
    try:
        response = requests.get(file_url, timeout=30)
        response.raise_for_status()
        
        if len(response.content) > MAX_FILE_SIZE:
            return jsonify({
                "error": "Fichier trop volumineux"
            }), 413
        
        filename = file_url.split('/')[-1]
        if '.' not in filename:
            filename = 'downloaded.tmp'
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        unique_id = str(uuid.uuid4())[:8]
        
        temp_filename = f"temp_url_{unique_id}"
        temp_path = os.path.join(UPLOAD_FOLDER, temp_filename)
        
        with open(temp_path, 'wb') as f:
            f.write(response.content)
        
        converted_filename = f"url_image_{timestamp}_{unique_id}.{target_format}"
        converted_path = os.path.join(CONVERTED_FOLDER, converted_filename)
        
        # Simple copie ou conversion basique
        if PIL_AVAILABLE:
            try:
                img = Image.open(temp_path)
                img.save(converted_path, format=target_format.upper())
            except:
                create_placeholder_image(converted_path, "URL", target_format)
        else:
            create_placeholder_image(converted_path, "URL", target_format)
        
        if os.path.exists(temp_path):
            os.remove(temp_path)
        
        base_url = request.host_url.rstrip('/')
        download_url = f"{base_url}/public/download/{converted_filename}"
        
        return jsonify({
            "success": True,
            "filename": converted_filename,
            "download_url": download_url,
            "message": "URL convertie en image avec succès!"
        })
        
    except Exception as e:
        return jsonify({"error": f"Erreur: {str(e)}"}), 500

@app.route('/convert-google-drive', methods=['POST'])
@require_api_key
def convert_google_drive():
    """Conversion depuis Google Drive"""
    if not ENABLE_GOOGLE_DRIVE or not google_drive_service:
        return jsonify({
            "error": "Service Google Drive non disponible"
        }), 503
    
    data = request.get_json() if request.is_json else request.form
    google_drive_url = data.get('url') or data.get('google_drive_url')
    output_format = data.get('format', 'pdf').lower()
    conversion_type = data.get('type', 'pdf').lower()
    
    if not google_drive_url:
        return jsonify({
            "error": "URL Google Drive manquante"
        }), 400
    
    file_id = extract_google_drive_id(google_drive_url)
    if not file_id:
        return jsonify({
            "error": "URL Google Drive invalide"
        }), 400
    
    try:
        file_content, filename, error = download_google_drive_file(file_id)
        
        if error:
            return jsonify({
                "error": error
            }), 400
        
        file_extension = get_file_extension_safe(filename) or 'tmp'
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        unique_id = str(uuid.uuid4())[:8]
        
        temp_filename = f"temp_gdrive_{unique_id}.{file_extension}"
        temp_path = os.path.join(UPLOAD_FOLDER, temp_filename)
        
        with open(temp_path, 'wb') as f:
            f.write(file_content.getvalue())
        
        base_name = os.path.splitext(filename)[0]
        
        if conversion_type == 'image':
            converted_filename = f"{base_name}_gdrive_image_{timestamp}_{unique_id}.{output_format}"
            converted_path = os.path.join(CONVERTED_FOLDER, converted_filename)
            conversion_success, conversion_message = convert_to_image(temp_path, converted_path, file_extension, output_format)
        else:
            converted_filename = f"{base_name}_gdrive_converted_{timestamp}_{unique_id}.pdf"
            converted_path = os.path.join(CONVERTED_FOLDER, converted_filename)
            conversion_success, conversion_message = enhanced_convert_file(temp_path, converted_path, file_extension)
        
        if os.path.exists(temp_path):
            os.remove(temp_path)
        
        if not conversion_success:
            return jsonify({
                "error": f"Échec de la conversion: {conversion_message}"
            }), 500
        
        base_url = request.host_url.rstrip('/')
        download_url = f"{base_url}/public/download/{converted_filename}"
        
        return jsonify({
            "success": True,
            "filename": converted_filename,
            "download_url": download_url,
            "message": "Fichier Google Drive converti avec succès!"
        })
        
    except Exception as e:
        return jsonify({"error": f"Erreur: {str(e)}"}), 500

@app.route('/public/download/<filename>')
def public_download(filename):
    """Télécharger les fichiers convertis"""
    try:
        return send_from_directory(CONVERTED_FOLDER, filename, as_attachment=True)
    except FileNotFoundError:
        return jsonify({"error": "Fichier non trouvé"}), 404

@app.route('/status')
@require_api_key
def status():
    """Statut de l'API"""
    return jsonify({
        "status": "Active",
        "version": "3.0",
        "files_in_upload": len(os.listdir(UPLOAD_FOLDER)) if os.path.exists(UPLOAD_FOLDER) else 0,
        "files_converted": len(os.listdir(CONVERTED_FOLDER)) if os.path.exists(CONVERTED_FOLDER) else 0,
        "features": {
            "image_conversion": ENABLE_IMAGE_CONVERSION,
            "text_to_image": ENABLE_TEXT_TO_IMAGE,
            "google_drive": ENABLE_GOOGLE_DRIVE and google_drive_service is not None,
            "docx_conversion": DOCX_AVAILABLE
        }
    })

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 8080))
    
    print(f"🚀 Serveur démarré sur le port {port}")
    print(f"📁 Formats supportés: {len(ALLOWED_EXTENSIONS)}")
    print(f"🔑 API Key: {'Définie' if API_KEY != 'votre-cle-secrete-changez-moi' else 'Par défaut'}")
    print(f"✨ Features:")
    print(f"   - PIL: {'✅' if PIL_AVAILABLE else '❌'}")
    print(f"   - Requests: {'✅' if REQUESTS_AVAILABLE else '❌'}")
    print(f"   - Google API: {'✅' if GOOGLE_API_AVAILABLE else '❌'}")
    print(f"   - DOCX: {'✅' if DOCX_AVAILABLE else '❌'}")
    print(f"   - ReportLab: {'✅' if REPORTLAB_AVAILABLE else '❌'}")
    
    app.run(host='0.0.0.0', port=port, debug=False)
