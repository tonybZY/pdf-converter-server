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
from urllib.parse import urlparse, parse_qs

# Imports pour conversion d'images
try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    print("⚠️  PIL/Pillow non disponible - conversion d'images limitée")

try:
    import fitz  # PyMuPDF pour PDF vers image
    PYMUPDF_AVAILABLE = True
except ImportError:
    PYMUPDF_AVAILABLE = False
    print("⚠️  PyMuPDF non disponible - conversion PDF vers image limitée")

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False
    print("⚠️  Requests non disponible - conversion URL limitée")

# Imports pour Google Drive
try:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseDownload
    GOOGLE_API_AVAILABLE = True
except ImportError:
    GOOGLE_API_AVAILABLE = False
    print("⚠️  Google API non disponible - téléchargement Google Drive limité")

app = Flask(__name__)
CORS(app)

# Configuration sécurisée avec feature flags
API_KEY = os.environ.get('PDF_API_KEY', 'votre-cle-secrete-changez-moi')
UPLOAD_FOLDER = 'uploads'
CONVERTED_FOLDER = 'converted'
MAX_FILE_SIZE = 16 * 1024 * 1024  # 16MB max

# Configuration Google Drive
GOOGLE_SERVICE_ACCOUNT_FILE = os.environ.get('GOOGLE_SERVICE_ACCOUNT_FILE', 'service-account.json')
GOOGLE_DRIVE_FOLDER_ID = os.environ.get('GOOGLE_DRIVE_FOLDER_ID', '')

# Feature Flags pour déploiement progressif
ENABLE_IMAGE_CONVERSION = os.environ.get('ENABLE_IMAGE_CONVERSION', 'true').lower() == 'true'
ENABLE_ADVANCED_PDF_CONVERSION = os.environ.get('ENABLE_ADVANCED_PDF_CONVERSION', 'true').lower() == 'true'
ENABLE_TEXT_TO_IMAGE = os.environ.get('ENABLE_TEXT_TO_IMAGE', 'true').lower() == 'true'
ENABLE_GOOGLE_DRIVE = os.environ.get('ENABLE_GOOGLE_DRIVE', 'true').lower() == 'true'

# Créer les dossiers
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(CONVERTED_FOLDER, exist_ok=True)

# Formats supportés - ÉTENDU
ALLOWED_EXTENSIONS = {
    'pdf', 'txt', 'rtf',
    'doc', 'docx', 'gdoc', 'odt', 'pages',
    'ppt', 'pptx', 'odp', 'key',
    'csv', 'xlsx', 'xls', 'ods', 'numbers',
    'png', 'jpg', 'jpeg', 'gif', 'bmp',
    'tiff', 'tif', 'webp', 'svg', 'ico',
    'html', 'htm', 'epub', 'md'
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

def extract_google_drive_id(url):
    """Extrait l'ID du fichier Google Drive depuis une URL"""
    patterns = [
        r'/file/d/([a-zA-Z0-9-_]+)',
        r'id=([a-zA-Z0-9-_]+)',
        r'/open\?id=([a-zA-Z0-9-_]+)',
        r'/uc\?id=([a-zA-Z0-9-_]+)',
        r'^([a-zA-Z0-9-_]+)$'  # ID direct
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
        # Obtenir les métadonnées du fichier
        file_metadata = google_drive_service.files().get(
            fileId=file_id,
            fields='name,size,mimeType'
        ).execute()
        
        filename = file_metadata.get('name', 'unknown')
        file_size = int(file_metadata.get('size', 0))
        mime_type = file_metadata.get('mimeType', '')
        
        # Vérifier la taille
        if file_size > MAX_FILE_SIZE:
            return None, None, f"Fichier trop volumineux ({file_size / (1024*1024):.2f} MB)"
        
        # Déterminer l'extension
        if '.' not in filename:
            mime_to_ext = {
                'application/pdf': '.pdf',
                'image/png': '.png',
                'image/jpeg': '.jpg',
                'text/plain': '.txt',
                'application/vnd.google-apps.document': '.gdoc',
                'application/vnd.google-apps.spreadsheet': '.gsheet',
                'application/vnd.google-apps.presentation': '.gslides'
            }
            ext = mime_to_ext.get(mime_type, '')
            if ext:
                filename += ext
        
        # Télécharger le fichier
        request_file = google_drive_service.files().get_media(fileId=file_id)
        file_content = io.BytesIO()
        downloader = MediaIoBaseDownload(file_content, request_file)
        
        done = False
        while not done:
            status, done = downloader.next_chunk()
            if status:
                print(f"Téléchargement: {int(status.progress() * 100)}%")
        
        file_content.seek(0)
        return file_content, filename, None
        
    except Exception as e:
        return None, None, f"Erreur téléchargement Google Drive: {str(e)}"

def convert_text_to_pdf(input_path, output_path):
    """Convertit un fichier texte en PDF simple"""
    try:
        with open(input_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        
        # PDF basique - version corrigée
        pdf_content = f"""%PDF-1.4
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
({content[:500].replace('(', '\\(').replace(')', '\\)').replace('\\', '\\\\')}) Tj
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
%%EOF"""
        
        with open(output_path, 'wb') as f:
            f.write(pdf_content.encode('latin-1', errors='ignore'))
        
        return True
    except Exception as e:
        print(f"Erreur conversion texte: {e}")
        return False

def clean_document_content(raw_content):
    """Nettoie le contenu du document pour un meilleur affichage"""
    try:
        # Si c'est du JSON, essayer de l'extraire intelligemment
        if raw_content.strip().startswith('{'):
            try:
                data = json.loads(raw_content)
                
                # Extraire les champs texte courants
                text_parts = []
                
                def extract_text_from_dict(obj, depth=0):
                    if depth > 3:  # Éviter récursion infinie
                        return
                    
                    if isinstance(obj, dict):
                        for key, value in obj.items():
                            if isinstance(value, str) and len(value) > 10 and key.lower() in ['text', 'content', 'body', 'description', 'title']:
                                text_parts.append(f"{key.title()}: {value}")
                            elif isinstance(value, (dict, list)):
                                extract_text_from_dict(value, depth + 1)
                    elif isinstance(obj, list):
                        for item in obj:
                            extract_text_from_dict(item, depth + 1)
                
                extract_text_from_dict(data)
                
                if text_parts:
                    return "\n\n".join(text_parts)
                else:
                    # Si pas de texte extrait, formatter le JSON de façon lisible
                    return json.dumps(data, indent=2, ensure_ascii=False)[:2000]
                    
            except json.JSONDecodeError:
                pass
        
        # Nettoyage général du texte
        content = raw_content
        
        # Remplacer les caractères de contrôle
        content = content.replace('\r\n', '\n').replace('\r', '\n')
        
        # Enlever les espaces excessifs
        lines = []
        for line in content.split('\n'):
            cleaned_line = ' '.join(line.split())  # Normaliser les espaces
            lines.append(cleaned_line)
        
        # Reconstruire avec espacement intelligent
        result = []
        for i, line in enumerate(lines):
            if line.strip():  # Ligne non vide
                result.append(line)
            elif i > 0 and lines[i-1].strip():  # Ligne vide après du contenu
                result.append("")  # Garder une seule ligne vide
        
        return '\n'.join(result)
        
    except Exception as e:
        print(f"Erreur nettoyage contenu: {e}")
        return raw_content[:2000]  # Fallback

def create_placeholder_image(output_path, text, format='png'):
    """Crée une image placeholder simple"""
    if PIL_AVAILABLE:
        try:
            img = Image.new('RGB', (400, 300), color='lightgray')
            draw = ImageDraw.Draw(img)
            
            try:
                font = ImageFont.truetype("arial.ttf", 24)
            except:
                font = ImageFont.load_default()
            
            bbox = draw.textbbox((0, 0), text, font=font)
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]
            
            x = (400 - text_width) // 2
            y = (300 - text_height) // 2
            
            draw.text((x, y), text, fill='darkgray', font=font)
            draw.rectangle([(10, 10), (390, 290)], outline='gray', width=2)
            
            img.save(output_path, format=format.upper())
            return True
        except Exception as e:
            print(f"Erreur création placeholder PIL: {e}")
    
    # Fallback: PNG basique
    try:
        png_data = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\tpHYs\x00\x00\x0b\x13\x00\x00\x0b\x13\x01\x00\x9a\x9c\x18\x00\x00\x00\nIDATx\x9cc\xf8\x0f\x00\x00\x01\x00\x01\x00\x18\xdd\x8d\xb4\x00\x00\x00\x00IEND\xaeB`\x82'
        
        with open(output_path, 'wb') as f:
            f.write(png_data)
        return True
    except Exception as e:
        print(f"Erreur création placeholder: {e}")
        return False

def create_document_image_advanced(text_content, output_path, doc_type, target_format='png'):
    """Création d'image avancée pour documents - VERSION AMÉLIORÉE"""
    if not PIL_AVAILABLE:
        return create_placeholder_image(output_path, f"{doc_type}\nPIL non disponible", target_format), "PIL non disponible"
    
    try:
        # Image plus grande pour meilleure lisibilité
        width, height = 1400, 1800
        img = Image.new('RGB', (width, height), color='white')
        draw = ImageDraw.Draw(img)
        
        # Couleurs améliorées
        header_color = '#4285f4'  # Bleu Google
        text_color = '#2c3e50'    # Gris foncé pour meilleure lisibilité
        border_color = '#bdc3c7'  # Gris clair
        highlight_color = '#fff3cd'  # Jaune pour surlignage
        
        # Polices plus grandes
        try:
            title_font = ImageFont.truetype("arial.ttf", 32)      # Plus grand
            subtitle_font = ImageFont.truetype("arial.ttf", 18)   # Plus grand
            content_font = ImageFont.truetype("arial.ttf", 16)    # Plus grand
            small_font = ImageFont.truetype("arial.ttf", 14)      # Pour les détails
        except:
            title_font = ImageFont.load_default()
            subtitle_font = ImageFont.load_default()
            content_font = ImageFont.load_default()
            small_font = ImageFont.load_default()
        
        # Header avec icône et titre
        draw.rectangle([(0, 0), (width, 90)], fill=header_color)
        draw.text((50, 30), f"📄 {doc_type}", fill='white', font=title_font)
        
        # Sous-header avec infos
        date_str = datetime.now().strftime("%d/%m/%Y à %H:%M")
        draw.rectangle([(0, 90), (width, 130)], fill='#f8f9fa')
        draw.text((50, 100), f"Converti le {date_str} | Convertisseur PDF/Image", fill='#6c757d', font=small_font)
        
        # Bordure principale
        draw.rectangle([(40, 150), (width-40, height-40)], outline=border_color, width=3)
        
        # Nettoyage et préparation du contenu
        y_position = 180
        line_height = 22  # Plus d'espace entre lignes
        max_chars_per_line = 85  # Moins de caractères par ligne
        left_margin = 60
        
        # Nettoyer le contenu (enlever le JSON si présent)
        cleaned_content = clean_document_content(text_content)
        
        # Diviser en lignes et traiter
        lines = cleaned_content.replace('\r', '').split('\n')
        processed_lines = []
        
        for line in lines:
            line = line.strip()
            if not line:  # Ligne vide
                processed_lines.append("")
                continue
                
            # Diviser les lignes trop longues intelligemment
            if len(line) > max_chars_per_line:
                words = line.split(' ')
                current_line = ""
                for word in words:
                    test_line = current_line + word + " "
                    if len(test_line) <= max_chars_per_line:
                        current_line = test_line
                    else:
                        if current_line:
                            processed_lines.append(current_line.strip())
                        current_line = word + " "
                if current_line:
                    processed_lines.append(current_line.strip())
            else:
                processed_lines.append(line)
        
        # Affichage des lignes avec mise en forme
        for i, line in enumerate(processed_lines[:65]):  # Limiter à 65 lignes
            if y_position > height - 100:
                # Indication de contenu tronqué
                draw.rectangle([(left_margin, y_position), (width-60, y_position+20)], fill='#e9ecef')
                draw.text((left_margin + 10, y_position), "... (contenu tronqué - document plus long)", fill='#6c757d', font=small_font)
                break
            
            if not line:  # Ligne vide = espace
                y_position += line_height // 2
                continue
            
            # Détecter et surligner les titres/éléments importants
            is_important = False
            if any(keyword in line.lower() for keyword in ['title', 'titre', 'important', 'header', '===', '***']):
                is_important = True
            
            # Détecter les listes (commencent par -, *, •, numéros)
            is_list_item = line.strip().startswith(('-', '*', '•')) or (len(line) > 0 and line[0].isdigit() and '.' in line[:5])
            
            # Surlignage pour éléments importants
            if is_important:
                draw.rectangle([(left_margin-5, y_position-2), (width-60, y_position+18)], fill=highlight_color)
            
            # Indentation pour listes
            x_position = left_margin + (20 if is_list_item else 0)
            
            # Couleur du texte selon le type
            text_color_final = '#1a73e8' if is_important else text_color
            
            # Affichage du texte
            draw.text((x_position, y_position), line, fill=text_color_final, font=content_font)
            y_position += line_height
        
        # Footer avec statistiques
        footer_y = height - 60
        draw.rectangle([(0, footer_y), (width, height)], fill='#f8f9fa')
        
        # Statistiques du document
        total_chars = len(text_content)
        total_lines = len(lines)
        draw.text((50, footer_y + 20), f"Document: {total_lines} lignes | {total_chars} caractères | Format: {target_format.upper()}", 
                 fill='#6c757d', font=small_font)
        
        # Logo/signature à droite
        draw.text((width-300, footer_y + 20), "Généré par Convertisseur PDF/Image", 
                 fill='#6c757d', font=small_font)
        
        # Sauvegarder avec qualité élevée
        img.save(output_path, format=target_format.upper(), quality=95, optimize=True)
        return True, f"Document {doc_type} converti en image {target_format.upper()} avec mise en forme avancée"
        
    except Exception as e:
        print(f"Erreur création image avancée: {e}")
        return create_placeholder_image(output_path, f"{doc_type}\nERREUR", target_format), "Erreur création image"

def convert_gdoc_to_image(input_path, output_path, target_format='png'):
    """Conversion spéciale pour fichiers Google Docs"""
    try:
        with open(input_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        
        print(f"Contenu GDOC: {content[:200]}...")
        
        if PIL_AVAILABLE:
            return create_document_image_advanced(content, output_path, "Google Doc", target_format)
        else:
            return create_placeholder_image(output_path, "GDOC\nPIL non disponible", target_format), "PIL non disponible"
            
    except Exception as e:
        print(f"Erreur conversion GDOC: {e}")
        return create_placeholder_image(output_path, "GDOC\nERREUR", target_format), "Erreur conversion GDOC"

def create_text_to_image_advanced(input_path, output_path, target_format='png', width=800, height=600):
    """Conversion avancée de texte vers image avec PIL"""
    if not PIL_AVAILABLE or not ENABLE_TEXT_TO_IMAGE:
        return create_placeholder_image(output_path, "TEXT", target_format), "PIL non disponible"
    
    try:
        with open(input_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        
        img = Image.new('RGB', (width, height), color='white')
        draw = ImageDraw.Draw(img)
        
        try:
            font = ImageFont.truetype("arial.ttf", 12)
        except:
            font = ImageFont.load_default()
        
        lines = content.split('\n')
        y_position = 20
        line_height = 15
        
        for line in lines[:35]:
            if y_position > height - 20:
                break
            if len(line) > 100:
                line = line[:97] + "..."
            draw.text((20, y_position), line, fill='black', font=font)
            y_position += line_height
        
        if len(lines) > 35 or len(content) > 3500:
            draw.text((20, height - 40), "... (texte tronqué)", fill='gray', font=font)
        
        img.save(output_path, format=target_format.upper())
        return True, f"Texte converti en image {target_format.upper()} avec PIL"
        
    except Exception as e:
        print(f"Erreur conversion texte avancée: {e}")
        return create_placeholder_image(output_path, "TEXT", target_format), f"Erreur: {str(e)}"

def convert_pdf_to_image_advanced(input_path, output_path, target_format='png', page_num=0):
    """Conversion avancée de PDF vers image avec PyMuPDF"""
    if not PYMUPDF_AVAILABLE or not ENABLE_ADVANCED_PDF_CONVERSION:
        return create_placeholder_image(output_path, "PDF", target_format), "PyMuPDF non disponible"
    
    try:
        pdf_document = fitz.open(input_path)
        
        if page_num >= len(pdf_document):
            page_num = 0
        
        page = pdf_document[page_num]
        matrix = fitz.Matrix(2, 2)
        pix = page.get_pixmap(matrix=matrix)
        
        if target_format.lower() == 'png':
            pix.save(output_path)
        else:
            if PIL_AVAILABLE:
                img_data = pix.tobytes("png")
                img = Image.open(io.BytesIO(img_data))
                img.save(output_path, format=target_format.upper())
            else:
                pix.save(output_path)
        
        pdf_document.close()
        return True, f"PDF converti en image {target_format.upper()} avec PyMuPDF"
        
    except Exception as e:
        print(f"Erreur conversion PDF avancée: {e}")
        return create_placeholder_image(output_path, "PDF", target_format), f"Erreur: {str(e)}"

def convert_image_format(input_path, output_path, target_format='png'):
    """Conversion entre formats d'images avec PIL"""
    if not PIL_AVAILABLE:
        shutil.copy2(input_path, output_path)
        return True, f"Image copiée (PIL non disponible)"
    
    try:
        with Image.open(input_path) as img:
            if target_format.lower() in ['jpg', 'jpeg'] and img.mode in ['RGBA', 'LA']:
                background = Image.new('RGB', img.size, (255, 255, 255))
                background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                img = background
            
            img.save(output_path, format=target_format.upper())
            return True, f"Image convertie vers {target_format.upper()} avec PIL"
            
    except Exception as e:
        print(f"Erreur conversion image: {e}")
        shutil.copy2(input_path, output_path)
        return True, f"Image copiée (erreur conversion: {str(e)})"

def enhanced_convert_to_image(input_path, output_path, file_extension, target_format='png'):
    """Conversion vers image selon le type de fichier"""
    
    if not ENABLE_IMAGE_CONVERSION:
        return False, "Conversion d'images désactivée (feature flag)"
    
    try:
        if file_extension in ['png', 'jpg', 'jpeg', 'gif', 'bmp', 'tiff', 'tif', 'webp', 'ico']:
            if file_extension == target_format:
                shutil.copy2(input_path, output_path)
                return True, f"Image {file_extension.upper()} copiée"
            else:
                return convert_image_format(input_path, output_path, target_format)
            
        elif file_extension == 'pdf':
            return convert_pdf_to_image_advanced(input_path, output_path, target_format)
            
        elif file_extension in ['txt', 'md']:
            return create_text_to_image_advanced(input_path, output_path, target_format)
            
        elif file_extension == 'gdoc':
            return convert_gdoc_to_image(input_path, output_path, target_format)
            
        elif file_extension in ['csv', 'rtf']:
            try:
                with open(input_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()[:500]
                return create_document_image_advanced(content, output_path, f"Document {file_extension.upper()}", target_format)
            except:
                return create_placeholder_image(output_path, f"DOC\n{file_extension.upper()}", target_format), "Erreur lecture fichier"
            
        elif file_extension in ['doc', 'docx', 'odt', 'pages']:
            try:
                with open(input_path, 'rb') as f:
                    content = f.read()[:1000].decode('utf-8', errors='ignore')
                return create_document_image_advanced(content, output_path, f"Document {file_extension.upper()}", target_format)
            except:
                return create_placeholder_image(output_path, f"DOC\n{file_extension.upper()}", target_format), "Erreur lecture fichier"
            
        else:
            return create_placeholder_image(output_path, f"FORMAT\n{file_extension.upper()}", target_format), "Format non supporté"
            
    except Exception as e:
        print(f"Erreur de conversion image: {e}")
        return False, f"Erreur: {str(e)}"

def enhanced_convert_file(input_path, output_path, file_extension):
    """Conversion améliorée selon le type de fichier (garde le code existant)"""
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

# ==================== ROUTES ====================

@app.route('/')
def home():
    """Page d'accueil avec informations sur l'API"""
    return jsonify({
        "service": "Convertisseur PDF/Image Sécurisé avec Support Google Drive",
        "version": "2.7-google-drive",
        "description": "API de conversion de fichiers vers PDF ou Image avec authentification et support Google Drive",
        "endpoints": {
            "health": "/health",
            "formats": "/formats", 
            "convert": "POST /convert (nécessite clé API) - Conversion vers PDF",
            "convert_to_image": "POST /convert-to-image (nécessite clé API) - Conversion vers Image",
            "convert_url_to_image": "POST /convert-url-to-image (nécessite clé API) - URL vers Image pour n8n",
            "convert_google_drive": "POST /convert-google-drive (nécessite clé API) - Google Drive vers PDF/Image",
            "public_download": "/public/download/<filename> (AUCUNE authentification requise)",
            "status": "/status (nécessite clé API)",
            "metrics": "/metrics (nécessite clé API)",
            "test_pil": "/test-pil (test PIL)"
        },
        "authentication": "Clé API requise via header 'X-API-Key' pour les uploads uniquement",
        "supported_formats": len(ALLOWED_EXTENSIONS),
        "max_file_size_mb": MAX_FILE_SIZE / (1024 * 1024),
        "features": {
            "image_conversion": ENABLE_IMAGE_CONVERSION,
            "advanced_pdf_conversion": ENABLE_ADVANCED_PDF_CONVERSION,
            "text_to_image": ENABLE_TEXT_TO_IMAGE,
            "google_drive": ENABLE_GOOGLE_DRIVE,
            "pil_available": PIL_AVAILABLE,
            "pymupdf_available": PYMUPDF_AVAILABLE,
            "requests_available": REQUESTS_AVAILABLE,
            "google_api_available": GOOGLE_API_AVAILABLE
        }
    })

@app.route('/health')
def health():
    return jsonify({
        "status": "OK",
        "version": "2.7-google-drive",
        "features": ["API Key Security", "Public Downloads", "PDF Conversion", "Image Conversion", "URL Conversion", "Google Drive"],
        "max_file_size_mb": MAX_FILE_SIZE / (1024 * 1024),
        "total_supported_formats": len(ALLOWED_EXTENSIONS),
        "libraries": {
            "pil_available": PIL_AVAILABLE,
            "pymupdf_available": PYMUPDF_AVAILABLE,
            "requests_available": REQUESTS_AVAILABLE,
            "google_api_available": GOOGLE_API_AVAILABLE
        },
        "feature_flags": {
            "image_conversion": ENABLE_IMAGE_CONVERSION,
            "advanced_pdf_conversion": ENABLE_ADVANCED_PDF_CONVERSION,
            "text_to_image": ENABLE_TEXT_TO_IMAGE,
            "google_drive": ENABLE_GOOGLE_DRIVE
        },
        "google_drive_ready": google_drive_service is not None
    })

@app.route('/test-pil')
def test_pil():
    """Route de test pour vérifier PIL"""
    try:
        if PIL_AVAILABLE:
            img = Image.new('RGB', (100, 100), color='red')
            return jsonify({
                "pil_works": True, 
                "message": "PIL/Pillow fonctionne correctement",
                "image_created": True
            })
        else:
            return jsonify({
                "pil_works": False, 
                "message": "PIL/Pillow non disponible",
                "error": "Module non installé"
            })
    except Exception as e:
        return jsonify({
            "pil_works": False, 
            "message": "Erreur lors du test PIL",
            "error": str(e)
        })

@app.route('/convert-google-drive', methods=['POST'])
@require_api_key
def convert_google_drive():
    """Nouvelle route pour conversion depuis Google Drive"""
    start_time = time.time()
    
    if not ENABLE_GOOGLE_DRIVE or not google_drive_service:
        return jsonify({
            "error": "Service Google Drive non disponible",
            "message": "Google Drive désactivé ou non configuré"
        }), 503
    
    print("=== REQUÊTE GOOGLE DRIVE REÇUE ===")
    
    # Récupérer les paramètres
    data = request.get_json() if request.is_json else request.form
    google_drive_url = data.get('url') or data.get('google_drive_url')
    output_format = data.get('format', 'pdf').lower()
    conversion_type = data.get('type', 'pdf').lower()  # 'pdf' ou 'image'
    
    if not google_drive_url:
        return jsonify({
            "error": "URL Google Drive manquante",
            "parameter": "url ou google_drive_url"
        }), 400
    
    # Extraire l'ID du fichier
    file_id = extract_google_drive_id(google_drive_url)
    if not file_id:
        return jsonify({
            "error": "URL Google Drive invalide",
            "message": "Impossible d'extraire l'ID du fichier",
            "url": google_drive_url
        }), 400
    
    try:
        print(f"📥 Téléchargement depuis Google Drive: {file_id}")
        
        # Télécharger le fichier
        file_content, filename, error = download_google_drive_file(file_id)
        
        if error:
            return jsonify({
                "error": "Échec du téléchargement Google Drive",
                "message": error,
                "file_id": file_id
            }), 400
        
        # Sauvegarder temporairement
        file_extension = filename.rsplit('.', 1)[1].lower() if '.' in filename else 'tmp'
        
        if file_extension not in ALLOWED_EXTENSIONS:
            return jsonify({
                "error": "Format de fichier non supporté",
                "detected_format": file_extension,
                "filename": filename,
                "supported_formats": sorted(list(ALLOWED_EXTENSIONS))
            }), 400
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        unique_id = str(uuid.uuid4())[:8]
        
        temp_filename = f"temp_gdrive_{unique_id}.{file_extension}"
        temp_path = os.path.join(UPLOAD_FOLDER, temp_filename)
        
        with open(temp_path, 'wb') as f:
            f.write(file_content.getvalue())
        
        # Conversion selon le type demandé
        base_name = os.path.splitext(filename)[0]
        
        if conversion_type == 'image':
            # Conversion vers image
            if output_format not in ['png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp']:
                output_format = 'png'
                
            converted_filename = f"{base_name}_gdrive_image_{timestamp}_{unique_id}.{output_format}"
            converted_path = os.path.join(CONVERTED_FOLDER, converted_filename)
            
            conversion_success, conversion_message = enhanced_convert_to_image(
                temp_path, converted_path, file_extension, output_format
            )
        else:
            # Conversion vers PDF
            converted_filename = f"{base_name}_gdrive_converted_{timestamp}_{unique_id}.pdf"
            converted_path = os.path.join(CONVERTED_FOLDER, converted_filename)
            
            conversion_success, conversion_message = enhanced_convert_file(
                temp_path, converted_path, file_extension
            )
        
        # Nettoyer le fichier temporaire
        if os.path.exists(temp_path):
            os.remove(temp_path)
        
        if not conversion_success:
            return jsonify({
                "error": f"Échec de la conversion: {conversion_message}"
            }), 500
        
        # URL de téléchargement
        base_url = request.host_url.rstrip('/')
        download_url = f"{base_url}/public/download/{converted_filename}"
        
        processing_time = round(time.time() - start_time, 3)
        
        print(f"✅ Conversion Google Drive réussie: {converted_path}")
        print(f"🔗 URL publique: {download_url}")
        print(f"⏱️ Temps de traitement: {processing_time}s")
        
        return jsonify({
            "success": True,
            "filename": converted_filename,
            "download_url": download_url,
            "original_filename": filename,
            "google_drive_id": file_id,
            "original_format": file_extension,
            "output_format": output_format if conversion_type == 'image' else 'pdf',
            "conversion_type": conversion_type,
            "processing_time_seconds": processing_time,
            "conversion_method": conversion_message,
            "message": f"Fichier Google Drive converti avec succès!",
            "format_category": get_format_category(file_extension)
        })
        
    except Exception as e:
        print(f"❌ Erreur Google Drive: {str(e)}")
        return jsonify({
            "error": f"Erreur de traitement: {str(e)}"
        }), 500

@app.route('/convert-url-to-image', methods=['POST'])
@require_api_key
def convert_url_to_image():
    """Route existante pour n8n - conversion d'URL de fichier vers image"""
    start_time = time.time()
    
    if not ENABLE_IMAGE_CONVERSION:
        return jsonify({
            "error": "Conversion d'images désactivée", 
            "message": "Feature flag ENABLE_IMAGE_CONVERSION=false"
        }), 503
    
    if not REQUESTS_AVAILABLE:
        return jsonify({
            "error": "Module requests non disponible", 
            "message": "Impossible de télécharger depuis une URL"
        }), 503
    
    print("=== REQUÊTE URL VERS IMAGE REÇUE ===")
    
    file_url = request.json.get('url') if request.is_json else request.form.get('url')
    target_format = request.json.get('format', 'png') if request.is_json else request.form.get('format', 'png')
    
    if not file_url:
        return jsonify({"error": "URL du fichier manquante", "parameter": "url"}), 400
    
    # Vérifier si c'est une URL Google Drive
    if 'drive.google.com' in file_url or 'docs.google.com' in file_url:
        # Rediriger vers la route Google Drive
        return convert_google_drive()
    
    if target_format.lower() not in ['png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp']:
        target_format = 'png'
    
    try:
        print(f"📥 Téléchargement depuis: {file_url}")
        response = requests.get(file_url, timeout=30)
        response.raise_for_status()
        
        if len(response.content) > MAX_FILE_SIZE:
            return jsonify({
                "error": "Fichier trop volumineux",
                "max_size_mb": MAX_FILE_SIZE / (1024 * 1024),
                "file_size_mb": round(len(response.content) / (1024 * 1024), 2)
            }), 413
        
        filename = file_url.split('/')[-1]
        if '.' not in filename:
            filename += '.tmp'
        
        file_extension = filename.rsplit('.', 1)[1].lower() if '.' in filename else 'tmp'
        
        if file_extension not in ALLOWED_EXTENSIONS:
            return jsonify({
                "error": "Format de fichier non supporté",
                "detected_format": file_extension,
                "supported_formats": sorted(list(ALLOWED_EXTENSIONS))
            }), 400
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        unique_id = str(uuid.uuid4())[:8]
        request_hash = hashlib.md5(f"{file_url}{timestamp}".encode()).hexdigest()[:8]
        
        base_name = os.path.splitext(filename)[0]
        
        temp_filename = f"temp_url_{request_hash}_{unique_id}.{file_extension}"
        temp_path = os.path.join(UPLOAD_FOLDER, temp_filename)
        
        with open(temp_path, 'wb') as f:
            f.write(response.content)
        
        converted_filename = f"{base_name}_url_image_{timestamp}_{unique_id}.{target_format}"
        converted_path = os.path.join(CONVERTED_FOLDER, converted_filename)
        
        conversion_success, conversion_message = enhanced_convert_to_image(temp_path, converted_path, file_extension, target_format)
        
        if os.path.exists(temp_path):
            os.remove(temp_path)
        
        if not conversion_success:
            return jsonify({"error": f"Échec de la conversion: {conversion_message}"}), 500
        
        base_url = request.host_url.rstrip('/')
        download_url = f"{base_url}/public/download/{converted_filename}"
        
        processing_time = round(time.time() - start_time, 3)
        
        print(f"✅ Conversion URL vers image réussie: {converted_path}")
        print(f"🔗 URL publique: {download_url}")
        print(f"⏱️ Temps de traitement: {processing_time}s")
        
        return jsonify({
            "success": True,
            "filename": converted_filename,
            "download_url": download_url,
            "original_url": file_url,
            "original_format": file_extension,
            "target_format": target_format,
            "file_size_mb": round(len(response.content) / (1024 * 1024), 2),
            "processing_time_seconds": processing_time,
            "conversion_method": conversion_message,
            "message": f"URL {file_extension.upper()} convertie en image {target_format.upper()} avec succès!",
            "format_category": get_format_category(file_extension),
            "conversion_type": "url_to_image",
            "n8n_ready": True
        })
        
    except requests.exceptions.RequestException as e:
        return jsonify({
            "error": "Erreur lors du téléchargement",
            "message": str(e),
            "url": file_url
        }), 400
    except Exception as e:
        print(f"❌ Erreur URL vers image: {str(e)}")
        return jsonify({"error": f"Erreur de traitement: {str(e)}"}), 500

@app.route('/convert-to-image', methods=['POST'])
@require_api_key
def convert_to_image():
    """Route existante améliorée pour conversion vers image"""
    start_time = time.time()
    
    if not ENABLE_IMAGE_CONVERSION:
        return jsonify({
            "error": "Conversion d'images désactivée", 
            "message": "Feature flag ENABLE_IMAGE_CONVERSION=false"
        }), 503
    
    print("=== REQUÊTE CONVERSION IMAGE REÇUE ===")
    print("Method:", request.method)
    print("Content-Type:", request.content_type)
    print("Files:", list(request.files.keys()))
    
    if 'file' not in request.files:
        return jsonify({"error": "Pas de fichier fourni"}), 400
    
    file = request.files['file']
    
    if file.filename == '':
        return jsonify({"error": "Nom de fichier vide"}), 400
    
    target_format = request.form.get('format', 'png').lower()
    if target_format not in ['png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp']:
        target_format = 'png'
    
    width = int(request.form.get('width', 800))
    height = int(request.form.get('height', 600))
    page_num = int(request.form.get('page', 0))
    
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
        request_hash = hashlib.md5(f"{file.filename}{timestamp}".encode()).hexdigest()[:8]
        
        original_name = secure_filename(file.filename)
        base_name = os.path.splitext(original_name)[0]
        file_extension = original_name.rsplit('.', 1)[1].lower()
        
        temp_filename = f"temp_{request_hash}_{unique_id}.{file_extension}"
        temp_path = os.path.join(UPLOAD_FOLDER, temp_filename)
        file.save(temp_path)
        
        converted_filename = f"{base_name}_image_{timestamp}_{unique_id}.{target_format}"
        converted_path = os.path.join(CONVERTED_FOLDER, converted_filename)
        
        if file_extension == 'pdf' and PYMUPDF_AVAILABLE:
            conversion_success, conversion_message = convert_pdf_to_image_advanced(temp_path, converted_path, target_format, page_num)
        elif file_extension in ['txt', 'md'] and ENABLE_TEXT_TO_IMAGE:
            conversion_success, conversion_message = create_text_to_image_advanced(temp_path, converted_path, target_format, width, height)
        else:
            conversion_success, conversion_message = enhanced_convert_to_image(temp_path, converted_path, file_extension, target_format)
        
        if os.path.exists(temp_path):
            os.remove(temp_path)
        
        if not conversion_success:
            return jsonify({"error": f"Échec de la conversion: {conversion_message}"}), 500
        
        base_url = request.host_url.rstrip('/')
        download_url = f"{base_url}/public/download/{converted_filename}"
        
        processing_time = round(time.time() - start_time, 3)
        
        print(f"✅ Conversion image réussie: {converted_path}")
        print(f"🔗 URL publique: {download_url}")
        print(f"⏱️ Temps de traitement: {processing_time}s")
        
        return jsonify({
            "success": True,
            "filename": converted_filename,
            "download_url": download_url,
            "original_format": file_extension,
            "target_format": target_format,
            "file_size_mb": round(file_size / (1024 * 1024), 2),
            "processing_time_seconds": processing_time,
            "conversion_method": conversion_message,
            "message": f"Fichier {file_extension.upper()} converti en image {target_format.upper()} avec succès!",
            "format_category": get_format_category(file_extension),
            "conversion_type": "file_to_image",
            "options_used": {
                "width": width if file_extension in ['txt', 'md'] else None,
                "height": height if file_extension in ['txt', 'md'] else None,
                "page": page_num if file_extension == 'pdf' else None
            }
        })
        
    except Exception as e:
        print(f"❌ Erreur: {str(e)}")
        return jsonify({"error": f"Erreur de traitement: {str(e)}"}), 500

@app.route('/convert', methods=['POST'])
@require_api_key
def convert():
    """Route existante pour conversion vers PDF"""
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
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        unique_id = str(uuid.uuid4())[:8]
        request_hash = hashlib.md5(f"{file.filename}{timestamp}".encode()).hexdigest()[:8]
        
        original_name = secure_filename(file.filename)
        base_name = os.path.splitext(original_name)[0]
        file_extension = original_name.rsplit('.', 1)[1].lower()
        
        temp_filename = f"temp_{request_hash}_{unique_id}.{file_extension}"
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

@app.route('/metrics')
@require_api_key
def metrics():
    """Endpoint de métriques pour monitoring"""
    try:
        uploaded_files = len(os.listdir(UPLOAD_FOLDER)) if os.path.exists(UPLOAD_FOLDER) else 0
        converted_files = len(os.listdir(CONVERTED_FOLDER)) if os.path.exists(CONVERTED_FOLDER) else 0
        
        upload_size = sum(os.path.getsize(os.path.join(UPLOAD_FOLDER, f)) 
                         for f in os.listdir(UPLOAD_FOLDER) 
                         if os.path.isfile(os.path.join(UPLOAD_FOLDER, f))) if os.path.exists(UPLOAD_FOLDER) else 0
        
        converted_size = sum(os.path.getsize(os.path.join(CONVERTED_FOLDER, f)) 
                            for f in os.listdir(CONVERTED_FOLDER) 
                            if os.path.isfile(os.path.join(CONVERTED_FOLDER, f))) if os.path.exists(CONVERTED_FOLDER) else 0
        
        return jsonify({
            "status": "active",
            "version": "2.7-google-drive",
            "timestamp": datetime.now().isoformat(),
            "files": {
                "uploaded_count": uploaded_files,
                "converted_count": converted_files,
                "upload_folder_size_mb": round(upload_size / (1024 * 1024), 2),
                "converted_folder_size_mb": round(converted_size / (1024 * 1024), 2),
                "total_size_mb": round((upload_size + converted_size) / (1024 * 1024), 2)
            },
            "features": {
                "image_conversion": ENABLE_IMAGE_CONVERSION,
                "advanced_pdf_conversion": ENABLE_ADVANCED_PDF_CONVERSION,
                "text_to_image": ENABLE_TEXT_TO_IMAGE,
                "google_drive": ENABLE_GOOGLE_DRIVE
            },
            "libraries": {
                "pil_available": PIL_AVAILABLE,
                "pymupdf_available": PYMUPDF_AVAILABLE,
                "requests_available": REQUESTS_AVAILABLE,
                "google_api_available": GOOGLE_API_AVAILABLE
            },
            "google_drive": {
                "service_ready": google_drive_service is not None,
                "service_account_file_exists": os.path.exists(GOOGLE_SERVICE_ACCOUNT_FILE)
            },
            "limits": {
                "max_file_size_mb": MAX_FILE_SIZE / (1024 * 1024),
                "supported_formats_count": len(ALLOWED_EXTENSIONS)
            }
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/public/download/<filename>')
def public_download(filename):
    """Route publique pour télécharger les fichiers convertis"""
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
        "description": "Convertisseur de fichiers sécurisé vers PDF et Image - Support étendu avec Google Drive",
        "security": "Clé API requise pour upload, téléchargements publics",
        "version": "2.7-google-drive",
        "new_features": [
            "🆕 Support Google Drive - téléchargement et conversion directe",
            "🆕 Extraction automatique des IDs Google Drive",
            "🆕 Support des liens de partage Google Drive",
            "Conversion d'URL vers image pour n8n",
            "Support PIL/Pillow pour vraies conversions d'images",
            "PyMuPDF pour conversion PDF vers image",
            "Conversion texte vers image avec rendu",
            "Feature flags pour déploiement progressif",
            "Gestion améliorée des fichiers GDOC avec nettoyage JSON",
            "Mise en forme avancée avec polices plus grandes et espacement",
            "Surlignage intelligent des titres et listes"
        ],
        "google_drive_support": {
            "enabled": ENABLE_GOOGLE_DRIVE,
            "service_ready": google_drive_service is not None,
            "supported_urls": [
                "https://drive.google.com/file/d/FILE_ID/view",
                "https://drive.google.com/open?id=FILE_ID",
                "https://drive.google.com/uc?id=FILE_ID",
                "Direct file ID"
            ]
        }
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
            "version": "2.7-google-drive",
            "files_in_upload": uploaded_files,
            "files_converted": converted_files,
            "supported_formats_count": len(ALLOWED_EXTENSIONS),
            "uptime": "Depuis le dernier déploiement",
            "security": "Upload protégé par clé API - Téléchargements publics",
            "features": {
                "image_conversion": ENABLE_IMAGE_CONVERSION,
                "advanced_pdf_conversion": ENABLE_ADVANCED_PDF_CONVERSION,
                "text_to_image": ENABLE_TEXT_TO_IMAGE,
                "url_conversion": True,
                "google_drive": ENABLE_GOOGLE_DRIVE
            },
            "libraries": {
                "pil_available": PIL_AVAILABLE,
                "pymupdf_available": PYMUPDF_AVAILABLE,
                "requests_available": REQUESTS_AVAILABLE,
                "google_api_available": GOOGLE_API_AVAILABLE
            },
            "google_drive_status": {
                "enabled": ENABLE_GOOGLE_DRIVE,
                "service_ready": google_drive_service is not None,
                "service_account_configured": os.path.exists(GOOGLE_SERVICE_ACCOUNT_FILE),
                "api_available": GOOGLE_API_AVAILABLE
            }
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 8080))
    
    if API_KEY == 'votre-cle-secrete-changez-moi':
        print("⚠️  ATTENTION: Utilisez une vraie clé API en production!")
        print("   Définissez la variable d'environnement PDF_API_KEY")
    
    print(f"🚀 Serveur PDF/Image Enhanced v2.7-google-drive démarré sur le port {port}")
    print(f"🔑 Clé API requise pour uploads: {'***' + API_KEY[-4:] if len(API_KEY) > 4 else '****'}")
    print(f"📁 Formats supportés: {len(ALLOWED_EXTENSIONS)} types de fichiers")
    print(f"🌍 Téléchargements publics: /public/download/<filename>")
    print(f"🎯 Feature Flags:")
    print(f"   - Image Conversion: {ENABLE_IMAGE_CONVERSION}")
    print(f"   - Advanced PDF Conversion: {ENABLE_ADVANCED_PDF_CONVERSION}")
    print(f"   - Text to Image: {ENABLE_TEXT_TO_IMAGE}")
    print(f"   - 🆕 Google Drive: {ENABLE_GOOGLE_DRIVE}")
    print(f"📚 Bibliothèques:")
    print(f"   - PIL/Pillow: {'✅' if PIL_AVAILABLE else '❌'}")
    print(f"   - PyMuPDF: {'✅' if PYMUPDF_AVAILABLE else '❌'}")
    print(f"   - Requests: {'✅' if REQUESTS_AVAILABLE else '❌'}")
    print(f"   - 🆕 Google API: {'✅' if GOOGLE_API_AVAILABLE else '❌'}")
    print(f"🔗 Endpoints principaux:")
    print(f"   - POST /convert (PDF)")
    print(f"   - POST /convert-to-image (Image)")
    print(f"   - POST /convert-url-to-image (URL pour n8n)")
    print(f"   - 🆕 POST /convert-google-drive (Google Drive)")
    print(f"   - GET /test-pil (test PIL)")
    print(f"   - GET /metrics (monitoring)")
    
    if ENABLE_GOOGLE_DRIVE:
        print(f"📋 Configuration Google Drive:")
        print(f"   - Service Account: {'✅ Configuré' if os.path.exists(GOOGLE_SERVICE_ACCOUNT_FILE) else '❌ Manquant'}")
        print(f"   - Service Ready: {'✅' if google_drive_service else '❌'}")
        if not os.path.exists(GOOGLE_SERVICE_ACCOUNT_FILE):
            print(f"   ⚠️  Créez un fichier service-account.json pour activer Google Drive")
            print(f"   ⚠️  Ou définissez GOOGLE_SERVICE_ACCOUNT_FILE")
    
    print(f"🎨 Améliorations v2.7:")
    print(f"   - Support complet Google Drive")
    print(f"   - Téléchargement depuis liens de partage")
    print(f"   - Conversion directe Google Drive vers PDF/Image")
    print(f"   - Détection automatique des URLs Google Drive")
    print(f"   - Toutes les fonctionnalités v2.6 conservées")
    
    app.run(host='0.0.0.0', port=port, debug=False)
