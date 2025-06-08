from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import os
import uuid
from datetime import datetime
from werkzeug.utils import secure_filename

app = Flask(__name__)
CORS(app)

# Créer le dossier pour stocker les PDFs convertis
UPLOAD_FOLDER = 'uploads'
CONVERTED_FOLDER = 'converted'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(CONVERTED_FOLDER, exist_ok=True)

@app.route('/health')
def health():
    return jsonify({"status": "OK"})

@app.route('/convert', methods=['POST'])
def convert():
    print("=== REQUÊTE REÇUE ===")
    print("Method:", request.method)
    print("Content-Type:", request.content_type)
    print("Files:", list(request.files.keys()))
    print("Form data:", list(request.form.keys()))
    
    if 'file' not in request.files:
        print("❌ ERREUR: Pas de fichier 'file'")
        return jsonify({"error": "Pas de fichier"}), 400
    
    file = request.files['file']
    print("✅ Fichier trouvé:", file.filename)
    
    if file.filename == '':
        return jsonify({"error": "Nom de fichier vide"}), 400
    
    if not file.filename.lower().endswith('.pdf'):
        return jsonify({"error": "Le fichier doit être un PDF"}), 400
    
    try:
        # Générer un nom unique pour le fichier
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        unique_id = str(uuid.uuid4())[:8]
        original_name = secure_filename(file.filename)
        base_name = os.path.splitext(original_name)[0]
        
        # Nom du fichier converti
        converted_filename = f"{base_name}_converted_{timestamp}_{unique_id}.pdf"
        converted_path = os.path.join(CONVERTED_FOLDER, converted_filename)
        
        # Pour l'instant, on "simule" la conversion en copiant le fichier
        # Plus tard, vous pourrez ajouter ici votre logique de conversion réelle
        file.save(converted_path)
        
        # Construire l'URL de téléchargement
        # Remplacez par votre vraie URL Railway
        base_url = request.host_url.rstrip('/')
        download_url = f"{base_url}/download/{converted_filename}"
        
        print(f"✅ Fichier converti sauvé: {converted_path}")
        print(f"🔗 URL de téléchargement: {download_url}")
        
        return jsonify({
            "success": True,
            "filename": converted_filename,
            "download_url": download_url,
            "message": "Conversion réussie!"
        })
        
    except Exception as e:
        print(f"❌ Erreur lors de la conversion: {str(e)}")
        return jsonify({"error": f"Erreur de conversion: {str(e)}"}), 500

@app.route('/download/<filename>')
def download_file(filename):
    """Route pour télécharger les fichiers convertis"""
    try:
        return send_from_directory(CONVERTED_FOLDER, filename, as_attachment=True)
    except FileNotFoundError:
        return jsonify({"error": "Fichier non trouvé"}), 404

@app.route('/files')
def list_files():
    """Route pour lister les fichiers disponibles (optionnel)"""
    try:
        files = os.listdir(CONVERTED_FOLDER)
        return jsonify({"files": files})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    import os
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False)
