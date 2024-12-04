import datetime
from threading import Thread
import threading
from flask import Flask, request, send_from_directory, jsonify
from flask_pymongo import PyMongo
from bson import ObjectId
from flask_cors import CORS
import random
import click
import urllib
import os
from dotenv import load_dotenv
from pymongo import MongoClient
import requests
from models import User
from apscheduler.schedulers.background import BackgroundScheduler
from pymongo.errors import ConnectionFailure
import time


def sensor():
    """ Function for test purposes. """
    print("Scheduler is alive!")


app = Flask(__name__)
CORS(app)
load_dotenv()

# MongoDB configuration
username = urllib.parse.quote_plus(os.environ['MONGO_USERNAME'])
password = urllib.parse.quote_plus(os.environ['MONGO_PASSWORD'])
url = "mongodb+srv://{}:{}@resume.hp2fd.mongodb.net/?retryWrites=true&w=majority&appName=resume".format(
    username, password)
client = MongoClient(url)
db = client["Spring"]
users_collection = db['Users']
winners_collection = db['Winners']

UPLOAD_FOLDER = 'qr_codes'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER


# get users api
@app.route("/users", methods=["GET"])
def get_users():
    sort_by = request.args.get("sort_by", "points")
    # -1 for descending, 1 for ascending
    order = int(request.args.get("order", "-1"))
    search = request.args.get("search", "")

    query = {}
    if search:
        query["name"] = {"$regex": search, "$options": "i"}

    users = list(users_collection.find(query).sort(sort_by, order))

    # Convert ObjectId to string for JSON serialization
    for user in users:
        user["_id"] = str(user["_id"])

    return jsonify(users)


# get user by id
@app.route("/users/<user_id>", methods=["GET"])
def get_user(user_id):
    user = users_collection.find_one({"_id": ObjectId(user_id)})
    if user:
        user["_id"] = str(user["_id"])
        return jsonify(user)
    return jsonify({"error": "User not found"}), 404


# add user to the database

@app.route("/users", methods=["POST"])
def add_user():
    data = request.json
    user = User(
        name=data["name"],
        age=data["age"],
        points=0,  # All users start with 0 points
        address=data["address"]
    )
    item = user.to_dict()
    result = users_collection.insert_one(item)
    print(result)
    item['_id'] = str(result.inserted_id)
    return jsonify(item), 200

# Delete User


@app.route("/users/<user_id>", methods=["DELETE"])
def delete_user(user_id):
    result = users_collection.delete_one({"_id": ObjectId(user_id)})
    if result.deleted_count:
        return jsonify({"message": "User deleted"}), 200
    return jsonify({"error": "User not found"}), 404

# Update points


@app.route("/users/<user_id>/points", methods=["PATCH"])
def update_points(user_id):
    points_change = request.json.get("points_change", 0)
    result = users_collection.update_one(
        {"_id": ObjectId(user_id)},
        {"$inc": {"points": points_change}}
    )
    print(result)
    if result.modified_count:
        return jsonify({"message": "Points updated", }), 200
    return jsonify({"error": "User not found"}), 404


@app.route("/users/grouped", methods=["GET"])
def get_users_grouped():
    pipeline = [
        {
            "$group": {
                "_id": "$points",
                "names": {"$push": "$name"},
                "average_age": {"$avg": "$age"}
            }
        },
        {
            "$project": {
                "_id": 0,
                "points": "$_id",
                "names": 1,
                "average_age": {"$round": ["$average_age", 2]}
            }
        },
        {"$sort": {"points": -1}}
    ]

    result = list(users_collection.aggregate(pipeline))

    grouped_users = {str(item["points"]): {
        "names": item["names"], "average_age": item["average_age"]} for item in result}

    return jsonify(grouped_users)

# QR Code Generation


def generate_qr_code(user_id, address):
    url = f"https://api.qrserver.com/v1/create-qr-code/?size=150x150&data={address}"
    response = requests.get(url)
    if response.status_code == 200:
        os.makedirs("qr_codes", exist_ok=True)
        with open(f"qr_codes/{user_id}.png", "wb") as f:
            f.write(response.content)


# Route to retrieve the uploaded image
@app.route('/uploads/<filename>', methods=['GET'])
def get_image(filename):
    try:
        return send_from_directory(app.config['UPLOAD_FOLDER'], filename)
    except FileNotFoundError:
        return jsonify({"error": "File not found"}), 404

# CLI Commands

# reset scores cli command


@app.cli.command("reset-scores")
def reset_scores():
    """Reset all user scores to 0"""
    users_collection.update_many({}, {"$set": {"points": 0}})
    click.echo("All scores have been reset to 0")

# add random users cli command


@app.cli.command("seed-db")
@click.option("--count", default=5, help="Number of users to create")
def seed_db(count):
    """Seed the database with random users"""
    names = ["Emma", "Noah", "James", "William", "Olivia",
             "Liam", "Ava", "Isabella", "Sophia", "Mason"]
    addresses = ["123 Main St", "456 Oak Ave",
                 "789 Pine Rd", "321 Elm St", "654 Maple Dr"]

    for _ in range(count):
        user = User(
            name=random.choice(names),
            age=random.randint(18, 70),
            points=0,
            address=random.choice(addresses)
        )
        users_collection.insert_one(user.to_dict())

    click.echo(f"Created {count} random users")


def listen_for_changes():
    """Function to listen to MongoDB change streams in a background thread"""
    try:
        with users_collection.watch() as stream:
            for change in stream:
                if change['operationType'] == 'insert':
                    print(f"Change detected: {change}")
                    item = change['fullDocument']
                    generate_qr_code(str(item['_id']), item['address'])
                # You can handle the change event here (e.g., send it to a front-end via WebSocket)
    except Exception as e:
        print(f"Error listening to change stream: {e}")

# Winner Selection Job


def select_winner():
    print("test")
    top_users = list(users_collection.find().sort("points", -1).limit(2))

    if len(top_users) > 1 and top_users[0]["points"] > top_users[1]["points"]:
        winner = top_users[0]
        winner_id = winner["_id"]
        points = winner["points"]
        timestamp = time

        winners_collection.insert_one({
            "user_id": winner_id,
            "points": points,
            "timestamp": time.time()
        })

        print(
            f"Winner selected: {winner['name']} with {points} points at {timestamp}")
    else:
        print("No winner selected due to a tie or insufficient users")


def start_change_stream_thread():
    change_stream_thread = threading.Thread(target=listen_for_changes)
    change_stream_thread.daemon = True
    change_stream_thread.start()

def add_sched():
    sched = BackgroundScheduler(daemon=True)
    # sched.add_job(select_winner, 'interval', seconds=10)
    sched.start()

if __name__ == "__main__":
    start_change_stream_thread()
    add_sched()
    app.run(debug=True)

