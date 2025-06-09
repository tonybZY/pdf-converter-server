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

app = Flask(__name__)
CORS(app)

# Configuration sécurisée
API_KEY = os.environ.get('PDF_API_KEY', 'votre-cle-secrete-changez-moi')
UPLOAD_FOLDER = 'uploads'
CONVERTED_FOLDER = 'converted'
MAX_FILE_SIZE = 16 * 1024 * 1024  # 16MB max

# Créer les dossiers
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(CONVERTED_FOLDER, exist_ok=True)

# Formats supportés - ÉTENDU
ALLOWED_EXTENSIONS = {
    # Documents PDF et texte
    'pdf', 'txt', 'rtf',
    # Documents bureautiques
    'doc', 'docx', 'gdoc', 'odt', 'pages',
    # Présentations
    'ppt', 'pptx', 'odp', 'key',
    # Tableurs
    'csv', 'xlsx', 'xls', 'ods', 'numbers',
    # Images standards
    'png', 'jpg', 'jpeg', 'gif', 'bmp',
    # Images avancées
    'tiff', 'tif', 'webp', 'svg', 'ico',
    # Web et autres
    'html', 'htm', 'epub', 'md'
}

def require_api_key(f):
    """Décorateur pour vérifier la clé API"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Vérifier dans les headers
        api_key = request.headers.get('X-API-Key')
        
        # Ou dans les paramètres de requête
        if not api_key:
            api_key = request.args.get('api_key')
        
        # Ou dans le form data pour les uploads
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

def convert_text_to_pdf(input_path, output_path):
    """Convertit un fichier texte en PDF simple"""
    try:
        with open(input_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        
        # Simulation de conversion PDF
        pdf_content = f"""
%PDF-1.4
1 0 obj
<<
/Type /Catalog
/Pages 2 0 R
>>
endobj

2 0 obj
<<
/Type /Pages
/Kids [3 0 R]
/Count 1
>>
endobj

3 0 obj
<<
/Type /Page
/Parent 2 0 R
/MediaBox [0 0 612 792]
/Contents 4 0 R
>>
endobj

4 0 obj
<<
/Length {len(content) + 50}
>>
stream
BT
/F1 12 Tf
50 750 Td
({content[:500]}) Tj
ET
endstream
endobj

xref
0 5
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
0000000115 00000 n 
0000000199 00000 n 
trailer
<<
/Size 5
/Root 1 0 R
>>
startxref
{300 + len(content)}
%%EOF
"""
        
        with open(output_path, 'w') as f:
            f.write(pdf_content)
        
        return True
    except Exception as e:
        print(f"Erreur conversion texte: {e}")
        return False

def enhanced_convert_to_image(input_path, output_path, file_extension, target_format='png'):
    """Conversion vers image selon le type de fichier"""
    try:
        if file_extension in ['png', 'jpg', 'jpeg', 'gif', 'bmp', 'tiff', 'tif', 'webp', 'svg', 'ico']:
            # Si c'est déjà une image, on la copie (ou on peut la convertir au format cible)
            if file_extension == target_format:
                shutil.copy2(input_path, output_path)
                return True, f"Image {file_extension.upper()} copiée"
            else:
                # Conversion d'un format image à un autre (simulation)
                shutil.copy2(input_path, output_path)
                return True, f"Image {file_extension.upper()} convertie en {target_format.upper()} (simulation)"
            
        elif file_extension == 'pdf':
            # PDF vers image (simulation - nécessiterait pdf2image en réalité)
            shutil.copy2(input_path, output_path)
            return True, f"PDF converti en {target_format.upper()} (simulation - première page)"
            
        elif file_extension in ['txt', 'md']:
            # Texte vers image (simulation - créer une image avec le texte)
            shutil.copy2(input_path, output_path)
            return True, f"Texte {file_extension.upper()} converti en image (simulation)"
            
        elif file_extension in ['doc', 'docx', 'gdoc', 'odt', 'pages', 'rtf']:
            # Documents vers image (simulation)
            shutil.copy2(input_path, output_path)
            return True, f"Document {file_extension.upper()} converti en image (simulation - première page)"
            
        elif file_extension in ['ppt', 'pptx', 'odp', 'key']:
            # Présentations vers image (simulation)
            shutil.copy2(input_path, output_path)
            return True, f"Présentation {file_extension.upper()} convertie en image (simulation - première slide)"
            
        elif file_extension in ['csv', 'xlsx', 'xls', 'ods', 'numbers']:
            # Tableurs vers image (simulation)
            shutil.copy2(input_path, output_path)
            return True, f"Tableur {file_extension.upper()} converti en image (simulation)"
            
        elif file_extension in ['html', 'htm']:
            # Web vers image (simulation - screenshot)
            shutil.copy2(input_path, output_path)
            return True, f"Page Web convertie en image (simulation - screenshot)"
            
        else:
            return False, "Format non supporté pour conversion image"
            
    except Exception as e:
        print(f"Erreur de conversion image: {e}")
        return False, f"Erreur: {str(e)}"
    """Conversion améliorée selon le type de fichier"""
    try:
        if file_extension == 'pdf':
            shutil.copy2(input_path, output_path)
            return True, "PDF copié"
            
        elif file_extension in ['txt', 'md']:
            success = convert_text_to_pdf(input_path, output_path)
            return success, f"Texte {file_extension.upper()} converti en PDF" if success else "Échec conversion texte"
            
        elif file_extension in ['png', 'jpg', 'jpeg', 'gif', 'bmp']:
            shutil.copy2(input_path, output_path)
            return True, f"Image {file_extension.upper()} préparée (conversion PDF en développement)"
            
        elif file_extension in ['tiff', 'tif', 'webp', 'svg', 'ico']:
            shutil.copy2(input_path, output_path)
            return True, f"Image {file_extension.upper()} préparée (conversion PDF en développement)"
            
        elif file_extension in ['csv', 'xlsx', 'xls']:
            shutil.copy2(input_path, output_path)
            return True, f"Tableur {file_extension.upper()} préparé (conversion PDF en développement)"
            
        elif file_extension in ['ods', 'numbers']:
            shutil.copy2(input_path, output_path)
            return True, f"Tableur {file_extension.upper()} préparé (conversion PDF en développement)"
            
        elif file_extension in ['doc', 'docx']:
            shutil.copy2(input_path, output_path)
            return True, f"Document Word {file_extension.upper()} préparé (conversion PDF en développement)"
            
        elif file_extension in ['gdoc', 'odt']:
            shutil.copy2(input_path, output_path)
            return True, f"Document {file_extension.upper()} préparé (conversion PDF en développement)"
            
        elif file_extension in ['pages']:
            shutil.copy2(input_path, output_path)
            return True, "Document Apple Pages préparé (conversion PDF en développement)"
            
        elif file_extension in ['rtf']:
            shutil.copy2(input_path, output_path)
            return True, "Document RTF préparé (conversion PDF en développement)"
            
        elif file_extension in ['ppt', 'pptx']:
            shutil.copy2(input_path, output_path)
            return True, f"Présentation PowerPoint {file_extension.upper()} préparée (conversion PDF en développement)"
            
        elif file_extension in ['odp']:
            shutil.copy2(input_path, output_path)
            return True, "Présentation LibreOffice préparée (conversion PDF en développement)"
            
        elif file_extension in ['key']:
            shutil.copy2(input_path, output_path)
            return True, "Présentation Apple Keynote préparée (conversion PDF en développement)"
            
        elif file_extension in ['html', 'htm']:
            shutil.copy2(input_path, output_path)
            return True, f"Page Web {file_extension.upper()} préparée (conversion PDF en développement)"
            
        elif file_extension in ['epub']:
            shutil.copy2(input_path, output_path)
            return True, "eBook EPUB préparé (conversion PDF en développement)"
            
        else:
            return False, "Format non supporté"
            
    except Exception as e:
        print(f"Erreur de conversion: {e}")
        return False, f"Erreur: {str(e)}"

@app.route('/')
def home():
    """Page d'accueil avec informations sur l'API"""
    return jsonify({
        "service": "Convertisseur PDF Sécurisé",
        "version": "2.3-stable",
        "description": "API de conversion de fichiers vers PDF avec authentification",
        "endpoints": {
            "health": "/health",
            "formats": "/formats", 
            "convert": "POST /convert (nécessite clé API) - Conversion vers PDF",
            "convert_to_image": "POST /convert-to-image (nécessite clé API) - Conversion vers Image",
            "public_download": "/public/download/<filename> (AUCUNE authentification requise)",
            "status": "/status (nécessite clé API)"
        },
        "authentication": "Clé API requise via header 'X-API-Key' pour les uploads uniquement",
        "supported_formats": len(ALLOWED_EXTENSIONS),
        "max_file_size_mb": MAX_FILE_SIZE / (1024 * 1024),
        "documentation": "Voir /formats pour la liste complète des formats"
    })

@app.route('/health')
def health():
    return jsonify({
        "status": "OK",
        "version": "2.4-dual-conversion",
        "features": ["API Key Security", "Public Downloads", "PDF Conversion", "Image Conversion"],
        "max_file_size_mb": MAX_FILE_SIZE / (1024 * 1024),
        "total_supported_formats": len(ALLOWED_EXTENSIONS)
    })

@app.route('/convert', methods=['POST'])
@require_api_key
def convert():
    start_time = time.time()
    
    print("=== REQUÊTE SÉCURISÉE REÇUE ===")
    print("Method:", request.method)
    print("Content-Type:", request.content_type)
    print("Files:", list(request.files.keys()))
    print("API Key présente:", bool(request.headers.get('X-API-Key') or request.args.get('api_key') or request.form.get('api_key')))
    
    if 'file' not in request.files:
        return jsonify({"error": "Pas de fichier fourni"}), 400
    
    file = request.files['file']
    
    if file.filename == '':
        return jsonify({"error": "Nom de fichier vide"}), 400
    
    # Vérifier la taille du fichier
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
            "supported_formats": sorted(list(ALLOWED_EXTENSIONS)),
            "hint": "Formats acceptés: Documents (doc, docx, gdoc, pdf, txt), Images (png, jpg, gif), Tableurs (xlsx, csv), Présentations (ppt, pptx), et plus..."
        }), 400
    
    try:
        # Générer des identifiants uniques
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        unique_id = str(uuid.uuid4())[:8]
        request_hash = hashlib.md5(f"{file.filename}{timestamp}".encode()).hexdigest()[:8]
        
        original_name = secure_filename(file.filename)
        base_name = os.path.splitext(original_name)[0]
        file_extension = original_name.rsplit('.', 1)[1].lower()
        
        # Sauvegarder le fichier temporairement
        temp_filename = f"temp_{request_hash}_{unique_id}.{file_extension}"
        temp_path = os.path.join(UPLOAD_FOLDER, temp_filename)
        file.save(temp_path)
        
        # Nom du fichier converti
        converted_filename = f"{base_name}_converted_{timestamp}_{unique_id}.pdf"
        converted_path = os.path.join(CONVERTED_FOLDER, converted_filename)
        
        # Conversion avec la nouvelle fonction améliorée
        conversion_success, conversion_message = enhanced_convert_file(temp_path, converted_path, file_extension)
        
        # Nettoyer le fichier temporaire
        if os.path.exists(temp_path):
            os.remove(temp_path)
        
        if not conversion_success:
            return jsonify({"error": f"Échec de la conversion: {conversion_message}"}), 500
        
        # Construire l'URL de téléchargement PUBLIC (sans authentification)
        base_url = request.host_url.rstrip('/')
        download_url = f"{base_url}/public/download/{converted_filename}"
        
        processing_time = round(time.time() - start_time, 3)
        
        print(f"✅ Conversion réussie: {converted_path}")
        print(f"🔗 URL publique: {download_url}")
        print(f"⏱️ Temps de traitement: {processing_time}s")
        
        return jsonify({
            "success": True,
            "filename": converted_filename,
            "download_url": download_url,
            "original_format": file_extension,
            "file_size_mb": round(file_size / (1024 * 1024), 2),
            "processing_time_seconds": processing_time,
            "conversion_method": conversion_message,
            "message": f"Fichier {file_extension.upper()} traité avec succès!",
            "format_category": get_format_category(file_extension),
            "security_note": "URL publique permanente - aucune authentification requise pour le téléchargement"
        })
        
    except Exception as e:
        print(f"❌ Erreur: {str(e)}")
        return jsonify({"error": f"Erreur de traitement: {str(e)}"}), 500

def get_format_category(extension):
    """Retourne la catégorie du format de fichier"""
    categories = {
        'documents': ['pdf', 'doc', 'docx', 'gdoc', 'odt', 'pages', 'txt', 'rtf', 'md'],
        'images': ['png', 'jpg', 'jpeg', 'gif', 'bmp', 'tiff', 'tif', 'webp', 'svg', 'ico'],
        'spreadsheets': ['csv', 'xlsx', 'xls', 'ods', 'numbers'],
        'presentations': ['ppt', 'pptx', 'odp', 'key'],
        'web': ['html', 'htm'],
        'ebooks': ['epub']
    }
    
    for category, extensions in categories.items():
        if extension in extensions:
            return category
    return 'unknown'

@app.route('/public/download/<filename>')
def public_download(filename):
    """Route publique pour télécharger les fichiers convertis - AUCUNE AUTHENTIFICATION"""
    try:
        return send_from_directory(CONVERTED_FOLDER, filename, as_attachment=True)
    except FileNotFoundError:
        return jsonify({"error": "Fichier non trouvé"}), 404

@app.route('/formats')
def supported_formats():
    """Liste détaillée des formats supportés"""
    formats_by_category = {
        "documents": ["pdf", "doc", "docx", "gdoc", "odt", "pages", "txt", "rtf", "md"],
        "images": ["png", "jpg", "jpeg", "gif", "bmp", "tiff", "tif", "webp", "svg", "ico"],
        "spreadsheets": ["csv", "xlsx", "xls", "ods", "numbers"],
        "presentations": ["ppt", "pptx", "odp", "key"],
        "web": ["html", "htm"],
        "ebooks": ["epub"]
    }
    
    return jsonify({
        "supported_formats": sorted(list(ALLOWED_EXTENSIONS)),
        "formats_by_category": formats_by_category,
        "total_formats": len(ALLOWED_EXTENSIONS),
        "max_file_size_mb": MAX_FILE_SIZE / (1024 * 1024),
        "description": "Convertisseur de fichiers sécurisé vers PDF - Support étendu",
        "security": "Clé API requise pour upload, téléchargements publics",
        "version": "2.3-stable"
    })

@app.route('/status')
@require_api_key
def status():
    """Statut détaillé pour les utilisateurs authentifiés"""
    try:
        uploaded_files = len(os.listdir(UPLOAD_FOLDER)) if os.path.exists(UPLOAD_FOLDER) else 0
        converted_files = len(os.listdir(CONVERTED_FOLDER)) if os.path.exists(CONVERTED_FOLDER) else 0
        
        return jsonify({
            "status": "Active",
            "version": "2.3-stable",
            "files_in_upload": uploaded_files,
            "files_converted": converted_files,
            "supported_formats_count": len(ALLOWED_EXTENSIONS),
            "uptime": "Depuis le dernier déploiement",
            "security": "Upload protégé par clé API - Téléchargements publics"
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    import os
    port = int(os.environ.get('PORT', 8080))
    
    # Avertissement si la clé par défaut est utilisée
    if API_KEY == 'votre-cle-secrete-changez-moi':
        print("⚠️  ATTENTION: Utilisez une vraie clé API en production!")
        print("   Définissez la variable d'environnement PDF_API_KEY")
    
    print(f"🚀 Serveur PDF stable v2.3 démarré sur le port {port}")
    print(f"🔑 Clé API requise pour uploads: {'***' + API_KEY[-4:] if len(API_KEY) > 4 else '****'}")
    print(f"📁 Formats supportés: {len(ALLOWED_EXTENSIONS)} types de fichiers")
    print(f"🌍 Téléchargements publics: /public/download/<filename>")
    
    app.run(host='0.0.0.0', port=port, debug=False)
