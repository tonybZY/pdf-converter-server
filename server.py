from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import os
import uuid
from datetime import datetime
from werkzeug.utils import secure_filename
import shutil

app = Flask(__name__)
CORS(app)

# Créer les dossiers
UPLOAD_FOLDER = 'uploads'
CONVERTED_FOLDER = 'converted'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(CONVERTED_FOLDER, exist_ok=True)

# Formats supportés (on commence simple)
ALLOWED_EXTENSIONS = {'pdf', 'txt', 'png', 'jpg', 'jpeg', 'gif', 'csv'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def simple_convert_to_pdf(input_path, output_path, file_extension):
    """Conversion simple - pour l'instant on copie juste le fichier"""
    try:
        if file_extension == 'pdf':
            # Si c'est déjà un PDF, on le copie
            shutil.copy2(input_path, output_path)
            return True
        elif file_extension == 'txt':
            # Pour les fichiers texte, on crée un pseudo-PDF (copie pour l'instant)
            shutil.copy2(input_path, output_path)
            return True
        elif file_extension in ['png', 'jpg', 'jpeg', 'gif']:
            # Pour les images, on copie pour l'instant (on ajoutera la vraie conversion plus tard)
            shutil.copy2(input_path, output_path)
            return True
        elif file_extension == 'csv':
            # Pour CSV, on copie pour l'instant
            shutil.copy2(input_path, output_path)
            return True
        else:
            return False
    except Exception as e:
        print(f"Erreur de conversion: {e}")
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
        
        # Conversion simple
        conversion_success = simple_convert_to_pdf(temp_path, converted_path, file_extension)
        
        # Nettoyer le fichier temporaire
        if os.path.exists(temp_path):
            os.remove(temp_path)
        
        if not conversion_success:
            return jsonify({"error": "Échec de la conversion"}), 500
        
        # Construire l'URL de téléchargement
        base_url = request.host_url.rstrip('/')
        download_url = f"{base_url}/download/{converted_filename}"
        
        print(f"✅ Fichier traité: {converted_path}")
        print(f"🔗 URL: {download_url}")
        
        return jsonify({
            "success": True,
            "filename": converted_filename,
            "download_url": download_url,
            "original_format": file_extension,
            "message": f"Fichier {file_extension.upper()} traité avec succès!"
        })
        
    except Exception as e:
        print(f"❌ Erreur: {str(e)}")
        return jsonify({"error": f"Erreur de traitement: {str(e)}"}), 500

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
        "description": "Convertisseur de fichiers (en développement)"
    })

if __name__ == "__main__":
    import os
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False)
