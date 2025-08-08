# Laune-Tracker-App

## Setup

1. Virtuelle Umgebung erstellen und aktivieren:
   ```
   python -m venv venv
   source venv/bin/activate
   ```
2. Abhängigkeiten installieren:
   ```
   pip install -r requirements.txt
   ```
3. MongoDB starten (lokal oder Cloud).
   - Lokal: `sudo systemctl start mongod`
   - Cloud: Passe die MongoDB-URL in app.py an.
4. App starten:
   ```
   python app.py
   ```
5. Im Browser öffnen: `http://<deine-ip>:5000`
