from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import os
import uuid
from datetime import datetime
from werkzeug.utils import secure_filename
from PIL import Image
import pandas as pd
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib.utils import ImageReader
import io
import tempfile

app = Flask(__name__)
CORS(app)

# Créer les dossiers
UPLOAD_FOLDER = 'uploads'
CONVERTED_FOLDER = 'converted'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(CONVERTED_FOLDER, exist_ok=True)

# Formats supportés
ALLOWED_EXTENSIONS = {'pdf', 'doc', 'docx', 'txt', 'xlsx', 'csv', 'png', 'jpg', 'jpeg', 'gif'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def convert_image_to_pdf(image_path, output_path):
    """Convertit une image en PDF"""
    try:
        with Image.open(image_path) as img:
            # Convertir en RGB si nécessaire
            if img.mode != 'RGB':
                img = img.convert('RGB')
            
            # Créer un PDF avec ReportLab
            c = canvas.Canvas(output_path, pagesize=A4)
            width, height = A4
            
            # Calculer les dimensions pour ajuster l'image
            img_width, img_height = img.size
            aspect = img_height / float(img_width)
            
            # Ajuster la taille pour tenir dans la page
            if img_width > img_height:
                new_width = width - 40  # marge
                new_height = new_width * aspect
            else:
                new_height = height - 40  # marge
                new_width = new_height / aspect
            
            # Centrer l'image
            x = (width - new_width) / 2
            y = (height - new_height) / 2
            
            # Créer un objet ImageReader pour ReportLab
            img_buffer = io.BytesIO()
            img.save(img_buffer, format='JPEG')
            img_buffer.seek(0)
            img_reader = ImageReader(img_buffer)
            
            c.drawImage(img_reader, x, y, new_width, new_height)
            c.save()
            return True
    except Exception as e:
        print(f"Erreur conversion image: {e}")
        return False

def convert_text_to_pdf(text_path, output_path):
    """Convertit un fichier texte en PDF"""
    try:
        with open(text_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        c = canvas.Canvas(output_path, pagesize=A4)
        width, height = A4
        
        # Configuration du texte
        y_position = height - 50
        line_height = 14
        max_lines_per_page = int((height - 100) / line_height)
        
        lines = content.split('\n')
        line_count = 0
        
        for line in lines:
            if line_count >= max_lines_per_page:
                c.showPage()
                y_position = height - 50
                line_count = 0
            
            c.drawString(50, y_position, line[:80])  # Limiter la largeur
            y_position -= line_height
            line_count += 1
        
        c.save()
        return True
    except Exception as e:
        print(f"Erreur conversion texte: {e}")
        return False

def convert_excel_to_pdf(excel_path, output_path):
    """Convertit un fichier Excel/CSV en PDF"""
    try:
        # Lire le fichier
        if excel_path.endswith('.csv'):
            df = pd.read_csv(excel_path)
        else:
            df = pd.read_excel(excel_path)
        
        c = canvas.Canvas(output_path, pagesize=A4)
        width, height = A4
        
        # Configuration
        y_position = height - 50
        row_height = 20
        col_width = width / len(df.columns) if len(df.columns) > 0 else 100
        
        # En-têtes
        x_position = 50
        for col in df.columns:
            c.drawString(x_position, y_position, str(col)[:15])
            x_position += col_width
        
        y_position -= row_height
        
        # Données (limiter aux premières lignes)
        for idx, row in df.head(30).iterrows():
            if y_position < 50:
                c.showPage()
                y_position = height - 50
            
            x_position = 50
            for value in row:
                c.drawString(x_position, y_position, str(value)[:15])
                x_position += col_width
            
            y_position -= row_height
        
        c.save()
        return True
    except Exception as e:
        print(f"Erreur conversion Excel/CSV: {e}")
        return False

@app.route('/health')
def health():
    return jsonify({"status": "OK"})

@app.route('/convert', methods=['POST'])
def convert():
    print("=== REQUÊTE REÇUE ===")
    print("Method:", request.method)
    print("Content-Type:", request.content_type)
    print("Files:", list(request.files.keys()))
    
    if 'file' not in request.files:
        print("❌ ERREUR: Pas de fichier 'file'")
        return jsonify({"error": "Pas de fichier"}), 400
    
    file = request.files['file']
    print("✅ Fichier trouvé:", file.filename)
    
    if file.filename == '':
        return jsonify({"error": "Nom de fichier vide"}), 400
    
    if not allowed_file(file.filename):
        return jsonify({"error": f"Format non supporté. Formats acceptés: {', '.join(ALLOWED_EXTENSIONS)}"}), 400
    
    try:
        # Générer des noms uniques
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        unique_id = str(uuid.uuid4())[:8]
        original_name = secure_filename(file.filename)
        base_name = os.path.splitext(original_name)[0]
        file_extension = original_name.rsplit('.', 1)[1].lower()
        
        # Sauvegarder le fichier original temporairement
        temp_path = os.path.join(UPLOAD_FOLDER, f"temp_{timestamp}_{unique_id}.{file_extension}")
        file.save(temp_path)
        
        # Nom du fichier converti
        converted_filename = f"{base_name}_converted_{timestamp}_{unique_id}.pdf"
        converted_path = os.path.join(CONVERTED_FOLDER, converted_filename)
        
        # Conversion selon le type de fichier
        conversion_success = False
        
        if file_extension == 'pdf':
            # Si c'est déjà un PDF, on le copie
            import shutil
            shutil.copy2(temp_path, converted_path)
            conversion_success = True
            
        elif file_extension in ['png', 'jpg', 'jpeg', 'gif']:
            # Conversion image vers PDF
            conversion_success = convert_image_to_pdf(temp_path, converted_path)
            
        elif file_extension == 'txt':
            # Conversion texte vers PDF
            conversion_success = convert_text_to_pdf(temp_path, converted_path)
            
        elif file_extension in ['xlsx', 'csv']:
            # Conversion Excel/CSV vers PDF
            conversion_success = convert_excel_to_pdf(temp_path, converted_path)
            
        elif file_extension in ['doc', 'docx']:
            # Pour les documents Word, on retourne une erreur pour l'instant
            # (nécessite python-docx + plus de logique)
            return jsonify({"error": "Les fichiers Word ne sont pas encore supportés"}), 400
        
        # Nettoyer le fichier temporaire
        if os.path.exists(temp_path):
            os.remove(temp_path)
        
        if not conversion_success:
            return jsonify({"error": "Échec de la conversion"}), 500
        
        # Construire l'URL de téléchargement
        base_url = request.host_url.rstrip('/')
        download_url = f"{base_url}/download/{converted_filename}"
        
        print(f"✅ Fichier converti: {converted_path}")
        print(f"🔗 URL: {download_url}")
        
        return jsonify({
            "success": True,
            "filename": converted_filename,
            "download_url": download_url,
            "original_format": file_extension,
            "message": f"Conversion {file_extension.upper()} vers PDF réussie!"
        })
        
    except Exception as e:
        print(f"❌ Erreur: {str(e)}")
        return jsonify({"error": f"Erreur de conversion: {str(e)}"}), 500

@app.route('/download/<filename>')
def download_file(filename):
    """Route pour télécharger les fichiers convertis"""
    try:
        return send_from_directory(CONVERTED_FOLDER, filename, as_attachment=True)
    except FileNotFoundError:
        return jsonify({"error": "Fichier non trouvé"}), 404

@app.route('/formats')
def supported_formats():
    """Liste des formats supportés"""
    return jsonify({
        "supported_formats": list(ALLOWED_EXTENSIONS),
        "description": "Tous les formats sont convertis en PDF"
    })

if __name__ == "__main__":
    import os
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False)
