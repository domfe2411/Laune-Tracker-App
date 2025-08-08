from flask import Flask, render_template, request, redirect, url_for
from pymongo import MongoClient
from bson import ObjectId
import os

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

# Datenbank und Collection
# (Wird automatisch angelegt, falls nicht vorhanden)
db = client["inventory"]
collection = db["items"]

@app.route('/')
def index():
    items = collection.find()
    return render_template('index.html', items=list(items))

@app.route('/add_item', methods=['POST'])
def add_item():
    if request.method == 'POST':
        item_name = request.form['item_name']
        quantity = int(request.form['quantity'])
        price = float(request.form['price'])
        item = {
            'item_name': item_name,
            'quantity': quantity,
            'price': price
        }
        collection.insert_one(item)
    return redirect(url_for('index'))

@app.route('/update_item/<item_id>', methods=['GET', 'POST'])
def update_item(item_id):
    item = collection.find_one({'_id': ObjectId(item_id)})
    if request.method == 'POST':
        new_quantity = int(request.form['new_quantity'])
        new_price = float(request.form['new_price'])
        collection.update_one(
            {'_id': ObjectId(item_id)},
            {'$set': {'quantity': new_quantity, 'price': new_price}}
        )
        return redirect(url_for('index'))
    return render_template('update_item.html', item=item)

@app.route('/delete_item/<item_id>')
def delete_item(item_id):
    collection.delete_one({'_id': ObjectId(item_id)})
    return redirect(url_for('index'))

if __name__ == '__main__':
    port = int(os.getenv("PORT", "5000"))
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)
