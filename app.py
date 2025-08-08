from flask import Flask, render_template, request, redirect, url_for, jsonify
from pymongo import MongoClient
from bson import ObjectId
import os
from datetime import datetime, date, timedelta
import json

app = Flask(__name__)


def create_mongo_client() -> MongoClient:
    """Create a MongoDB client; fall back to in-memory mongomock if real DB is unavailable."""
    mongodb_uri = os.getenv("MONGODB_URI", "mongodb://localhost:27017/")
    try:
        client = MongoClient(mongodb_uri, serverSelectionTimeoutMS=500)
        # Ensure connection works; will raise if server not reachable
        client.admin.command("ping")
        return client
    except Exception:
        try:
            import mongomock  # type: ignore
        except Exception as exc:
            raise RuntimeError(
                "MongoDB ist nicht verfügbar und 'mongomock' ist nicht installiert. "
                "Installiere mongomock (pip install mongomock) oder setze MONGODB_URI."
            ) from exc
        return mongomock.MongoClient()


client = create_mongo_client()

# Datenbank und Collection für LauneTracker
db = client["launetracker"]
mood_collection = db["moods"]

@app.route('/')
def home():
    return render_template('home.html')


@app.route('/mood-tracker')
def mood_tracker():
    # Hole alle Stimmungseinträge des aktuellen Monats
    current_month = date.today().replace(day=1)
    next_month = (current_month.replace(day=28) + timedelta(days=4)).replace(day=1)
    
    moods = list(mood_collection.find({
        'date': {
            '$gte': current_month.isoformat(),
            '$lt': next_month.isoformat()
        }
    }).sort('date', 1))
    
    return render_template('mood_tracker.html', moods=moods, view_type='monthly', today=date.today().isoformat())

@app.route('/mood-tracker/weekly')
def mood_tracker_weekly():
    # Hole alle Stimmungseinträge der aktuellen Woche
    today = date.today()
    start_of_week = today - timedelta(days=today.weekday())
    end_of_week = start_of_week + timedelta(days=7)
    
    moods = list(mood_collection.find({
        'date': {
            '$gte': start_of_week.isoformat(),
            '$lt': end_of_week.isoformat()
        }
    }).sort('date', 1))
    
    return render_template('mood_tracker.html', moods=moods, view_type='weekly', today=date.today().isoformat())

@app.route('/add_mood', methods=['POST'])
def add_mood():
    if request.method == 'POST':
        motivation = int(request.form['motivation'])
        mood = int(request.form['mood'])
        wellbeing = int(request.form['wellbeing'])
        note = request.form.get('note', '')
        
        # Verwende ausgewähltes Datum oder heute
        selected_date = request.form.get('selected_date', date.today().isoformat())
        
        mood_entry = {
            'date': selected_date,
            'motivation': motivation,
            'mood': mood,
            'wellbeing': wellbeing,
            'note': note,
            'created_at': datetime.now().isoformat()
        }
        mood_collection.insert_one(mood_entry)
    return redirect(url_for('mood_tracker'))

@app.route('/delete_mood/<mood_id>')
def delete_mood(mood_id):
    mood_collection.delete_one({'_id': ObjectId(mood_id)})
    return redirect(url_for('mood_tracker'))

@app.route('/api/mood-data')
def get_mood_data():
    """API endpoint für Chart.js Daten - Monatlich"""
    current_month = date.today().replace(day=1)
    next_month = (current_month.replace(day=28) + timedelta(days=4)).replace(day=1)
    
    moods = list(mood_collection.find({
        'date': {
            '$gte': current_month.isoformat(),
            '$lt': next_month.isoformat()
        }
    }).sort('date', 1))
    
    return _process_mood_data(moods)

@app.route('/api/mood-data/weekly')
def get_mood_data_weekly():
    """API endpoint für Chart.js Daten - Wöchentlich"""
    today = date.today()
    start_of_week = today - timedelta(days=today.weekday())
    end_of_week = start_of_week + timedelta(days=7)
    
    moods = list(mood_collection.find({
        'date': {
            '$gte': start_of_week.isoformat(),
            '$lt': end_of_week.isoformat()
        }
    }).sort('date', 1))
    
    return _process_mood_data(moods)

def _process_mood_data(moods):
    """Verarbeite Stimmungsdaten für Chart.js"""
    # Berechne Durchschnittswerte pro Tag
    daily_data = {}
    for mood in moods:
        day = mood['date']
        if day not in daily_data:
            daily_data[day] = {'motivation': [], 'mood': [], 'wellbeing': []}
        daily_data[day]['motivation'].append(mood['motivation'])
        daily_data[day]['mood'].append(mood['mood'])
        daily_data[day]['wellbeing'].append(mood['wellbeing'])
    
    # Berechne Durchschnitte
    chart_data = {
        'labels': [],
        'motivation': [],
        'mood': [],
        'wellbeing': []
    }
    
    for day in sorted(daily_data.keys()):
        chart_data['labels'].append(day)
        chart_data['motivation'].append(sum(daily_data[day]['motivation']) / len(daily_data[day]['motivation']))
        chart_data['mood'].append(sum(daily_data[day]['mood']) / len(daily_data[day]['mood']))
        chart_data['wellbeing'].append(sum(daily_data[day]['wellbeing']) / len(daily_data[day]['wellbeing']))
    
    return jsonify(chart_data)

if __name__ == '__main__':
    port = int(os.getenv("PORT", "5000"))
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)
