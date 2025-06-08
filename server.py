from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

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
    
    return jsonify({
        "success": True,
        "filename": file.filename,
        "message": "SUCCESS!"
    })

if __name__ == "__main__":
    import os
    port = int(os.environ.get('PORT', 8001))
    app.run(host='0.0.0.0', port=port, debug=False)
