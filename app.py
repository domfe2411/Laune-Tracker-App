from flask import Flask, render_template, request, redirect, url_for, jsonify, session, flash
from pymongo import MongoClient
from bson import ObjectId
import os
from datetime import datetime, date, timedelta
import json
import secrets
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from functools import wraps

app = Flask(__name__)
app.secret_key = secrets.token_hex(16)

# E-Mail-Konfiguration (anpassen)
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_USER = os.getenv("SMTP_USER", "your-email@gmail.com")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "your-app-password")
SENDER_EMAIL = os.getenv("SENDER_EMAIL", "your-email@gmail.com")

def create_mongo_client() -> MongoClient:
    """Create a MongoDB client; fall back to in-memory mongomock if real DB is unavailable."""
    mongodb_uri = os.getenv("MONGODB_URI", "mongodb://localhost:27017/")
    try:
        client = MongoClient(mongodb_uri, serverSelectionTimeoutMS=500)
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

db = client["launetracker"]
mood_collection = db["moods"]
user_collection = db["users"]


def create_admin_if_not_exists():
    admin = user_collection.find_one({"email": "admin@launetracker.com"})
    if not admin:
        user_collection.insert_one({
            "email": "admin@launetracker.com",
            "password": "admin123",
            "role": "admin",
            "created_at": datetime.now().isoformat(),
            "active": True
        })


def remove_user_if_exists(email: str) -> None:
    try:
        user_collection.delete_one({"email": email})
    except Exception:
        pass


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        user = user_collection.find_one({"_id": ObjectId(session['user_id'])})
        if not user or user.get('role') != 'admin':
            flash('Admin-Berechtigung erforderlich', 'error')
            return redirect(url_for('mood_tracker'))
        return f(*args, **kwargs)
    return decorated_function


def send_email(to_email, subject, body):
    try:
        msg = MIMEMultipart()
        msg['From'] = SENDER_EMAIL
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SMTP_USER, SMTP_PASSWORD)
        text = msg.as_string()
        server.sendmail(SENDER_EMAIL, to_email, text)
        server.quit()
        return True
    except Exception as e:
        print(f"E-Mail-Fehler: {e}")
        return False


@app.route('/')
def home():
    if 'user_id' in session:
        return redirect(url_for('mood_tracker'))
    return render_template('home.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        user = user_collection.find_one({"email": email, "password": password, "active": True})
        if user:
            session['user_id'] = str(user['_id'])
            session['user_email'] = user['email']
            session['user_role'] = user['role']
            flash('Erfolgreich angemeldet!', 'success')
            return redirect(url_for('mood_tracker'))
        flash('Ungültige E-Mail oder Passwort', 'error')
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    flash('Erfolgreich abgemeldet!', 'success')
    return redirect(url_for('home'))


@app.route('/admin')
@admin_required
def admin_dashboard():
    users = list(user_collection.find().sort("created_at", -1))
    return render_template('admin_dashboard.html', users=users)


@app.route('/admin/create-user', methods=['GET', 'POST'])
@admin_required
def create_user():
    if request.method == 'POST':
        email = request.form['email']
        role = request.form['role']
        existing_user = user_collection.find_one({"email": email})
        if existing_user:
            flash('E-Mail-Adresse bereits registriert', 'error')
            return render_template('create_user.html')
        generated_password = secrets.token_urlsafe(8)
        user_data = {
            "email": email,
            "password": generated_password,
            "role": role,
            "created_at": datetime.now().isoformat(),
            "active": True
        }
        user_collection.insert_one(user_data)
        if SMTP_USER != "your-email@gmail.com":
            subject = "Zugang zum LauneTracker"
            body = f"""
Willkommen beim LauneTracker!

Zugangsdaten:
E-Mail: {email}
Passwort: {generated_password}

Login: {request.host_url}login
Bitte ändere dein Passwort nach der ersten Anmeldung unter "Passwort ändern".
"""
            if send_email(email, subject, body):
                flash(f'Benutzer {email} erstellt und E-Mail gesendet', 'success')
            else:
                flash(f'Benutzer {email} erstellt, aber E-Mail-Versand fehlgeschlagen. Passwort: {generated_password}', 'warning')
        else:
            flash(f'Benutzer {email} erstellt mit Passwort: {generated_password}', 'success')
        return redirect(url_for('admin_dashboard'))
    return render_template('create_user.html')


@app.route('/admin/delete-user/<user_id>')
@admin_required
def delete_user(user_id):
    user_collection.delete_one({"_id": ObjectId(user_id)})
    flash('Benutzer gelöscht', 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/update-role/<user_id>', methods=['POST'])
@admin_required
def update_user_role(user_id):
    new_role = request.form.get('role')
    if new_role not in ['admin', 'teilnehmer']:
        flash('Ungültige Rolle', 'error')
        return redirect(url_for('admin_dashboard'))
    # Verhindere, dass sich der aktuelle Admin selbst degradiert
    if str(user_id) == session.get('user_id') and new_role != 'admin':
        flash('Du kannst deine eigene Admin-Rolle nicht entfernen', 'error')
        return redirect(url_for('admin_dashboard'))
    user_collection.update_one({"_id": ObjectId(user_id)}, {"$set": {"role": new_role}})
    flash('Rolle aktualisiert', 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/reset-password/<user_id>', methods=['GET', 'POST'])
@admin_required
def reset_user_password(user_id):
    user = user_collection.find_one({"_id": ObjectId(user_id)})
    if not user:
        flash('Benutzer nicht gefunden', 'error')
        return redirect(url_for('admin_dashboard'))
    if request.method == 'POST':
        new_password = request.form['new_password']
        if len(new_password) < 6:
            flash('Passwort muss mindestens 6 Zeichen lang sein', 'error')
            return render_template('reset_password.html', user=user)
        user_collection.update_one({"_id": ObjectId(user_id)}, {"$set": {"password": new_password}})
        flash(f'Passwort für {user["email"]} wurde geändert', 'success')
        return redirect(url_for('admin_dashboard'))
    return render_template('reset_password.html', user=user)


@app.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    if request.method == 'POST':
        current_password = request.form['current_password']
        new_password = request.form['new_password']
        confirm_password = request.form['confirm_password']
        user = user_collection.find_one({"_id": ObjectId(session['user_id'])})
        if not user or user.get('password') != current_password:
            flash('Aktuelles Passwort ist falsch', 'error')
            return render_template('change_password.html')
        if new_password != confirm_password:
            flash('Neues Passwort und Bestätigung stimmen nicht überein', 'error')
            return render_template('change_password.html')
        if len(new_password) < 6:
            flash('Neues Passwort muss mindestens 6 Zeichen lang sein', 'error')
            return render_template('change_password.html')
        user_collection.update_one({"_id": ObjectId(session['user_id'])}, {"$set": {"password": new_password}})
        flash('Passwort erfolgreich geändert', 'success')
        return redirect(url_for('mood_tracker'))
    return render_template('change_password.html')


@app.route('/mood-tracker')
@login_required
def mood_tracker():
    current_month = date.today().replace(day=1)
    next_month = (current_month.replace(day=28) + timedelta(days=4)).replace(day=1)
    moods = list(mood_collection.find({
        'user_id': session['user_id'],
        'date': {'$gte': current_month.isoformat(), '$lt': next_month.isoformat()}
    }).sort('date', 1))
    return render_template('mood_tracker.html', moods=moods, view_type='monthly', today=date.today().isoformat())


@app.route('/mood-tracker/weekly')
@login_required
def mood_tracker_weekly():
    today = date.today()
    start_of_week = today - timedelta(days=today.weekday())
    end_of_week = start_of_week + timedelta(days=7)
    moods = list(mood_collection.find({
        'user_id': session['user_id'],
        'date': {'$gte': start_of_week.isoformat(), '$lt': end_of_week.isoformat()}
    }).sort('date', 1))
    return render_template('mood_tracker.html', moods=moods, view_type='weekly', today=date.today().isoformat())


@app.route('/add_mood', methods=['POST'])
@login_required
def add_mood():
    if request.method == 'POST':
        motivation = int(request.form['motivation'])
        mood = int(request.form['mood'])
        wellbeing = int(request.form['wellbeing'])
        note = request.form.get('note', '')
        selected_date = request.form.get('selected_date', date.today().isoformat())
        mood_entry = {
            'user_id': session['user_id'],
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
@login_required
def delete_mood(mood_id):
    mood = mood_collection.find_one({"_id": ObjectId(mood_id), "user_id": session['user_id']})
    if mood:
        mood_collection.delete_one({"_id": ObjectId(mood_id)})
        flash('Eintrag gelöscht', 'success')
    else:
        flash('Eintrag nicht gefunden oder keine Berechtigung', 'error')
    return redirect(url_for('mood_tracker'))


@app.route('/api/mood-data')
@login_required
def get_mood_data():
    current_month = date.today().replace(day=1)
    next_month = (current_month.replace(day=28) + timedelta(days=4)).replace(day=1)
    moods = list(mood_collection.find({
        'user_id': session['user_id'],
        'date': {'$gte': current_month.isoformat(), '$lt': next_month.isoformat()}
    }).sort('date', 1))
    return _process_mood_data(moods)


@app.route('/api/mood-data/weekly')
@login_required
def get_mood_data_weekly():
    today = date.today()
    start_of_week = today - timedelta(days=today.weekday())
    end_of_week = start_of_week + timedelta(days=7)
    moods = list(mood_collection.find({
        'user_id': session['user_id'],
        'date': {'$gte': start_of_week.isoformat(), '$lt': end_of_week.isoformat()}
    }).sort('date', 1))
    return _process_mood_data(moods)


def _process_mood_data(moods):
    daily_data = {}
    for mood in moods:
        day = mood['date']
        if day not in daily_data:
            daily_data[day] = {'motivation': [], 'mood': [], 'wellbeing': []}
        daily_data[day]['motivation'].append(mood['motivation'])
        daily_data[day]['mood'].append(mood['mood'])
        daily_data[day]['wellbeing'].append(mood['wellbeing'])
    chart_data = {'labels': [], 'motivation': [], 'mood': [], 'wellbeing': []}
    for day in sorted(daily_data.keys()):
        chart_data['labels'].append(day)
        chart_data['motivation'].append(sum(daily_data[day]['motivation']) / len(daily_data[day]['motivation']))
        chart_data['mood'].append(sum(daily_data[day]['mood']) / len(daily_data[day]['mood']))
        chart_data['wellbeing'].append(sum(daily_data[day]['wellbeing']) / len(daily_data[day]['wellbeing']))
    return jsonify(chart_data)


def bootstrap_on_start():
    create_admin_if_not_exists()
    remove_user_if_exists("d.feix.teiln@btz-koeln.net")


bootstrap_on_start()


if __name__ == '__main__':
    port = int(os.getenv("PORT", "5000"))
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)
