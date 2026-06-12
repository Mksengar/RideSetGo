"""
DriveNow Ride Platform — Flask Backend
Connects to frontend.html via REST API on http://localhost:5000/api
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
from datetime import datetime, timedelta
import jwt
import bcrypt
import uuid
import os

app = Flask(__name__)
CORS(app)  # Allow requests from frontend (any origin)

# ─── Config ───────────────────────────────────────────────────────────────────
SECRET_KEY = os.environ.get("SECRET_KEY", "drivenow-dev-secret-change-in-prod")
JWT_EXPIRY_HOURS = 24

# ─── In-memory "database" (replace with PostgreSQL/MySQL in production) ────────
drivers_db = {}   # email -> driver record
rides_db   = {}   # ride_id -> ride record

# Fare config per vehicle type (₹ per km base fare)
FARE_CONFIG = {
    "car":  {"base": 30, "per_km": 13, "min_fare": 50},
    "auto": {"base": 20, "per_km": 9,  "min_fare": 35},
    "bike": {"base": 15, "per_km": 7,  "min_fare": 25},
}

# ─── Helpers ──────────────────────────────────────────────────────────────────
def generate_token(driver_id: str) -> str:
    payload = {
        "driver_id": driver_id,
        "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRY_HOURS)
    }
    return jwt.encode(payload, SECRET_KEY, algorithm="HS256")


def verify_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def auth_required(f):
    """Decorator: validates Bearer token and injects driver record."""
    from functools import wraps
    @wraps(f)
    def wrapper(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "Missing or invalid token"}), 401
        token = auth_header.split(" ", 1)[1]
        payload = verify_token(token)
        if not payload:
            return jsonify({"error": "Token expired or invalid"}), 401
        driver = next(
            (d for d in drivers_db.values() if d["id"] == payload["driver_id"]),
            None
        )
        if not driver:
            return jsonify({"error": "Driver not found"}), 404
        request.driver = driver
        return f(*args, **kwargs)
    return wrapper


def calculate_fare(distance_km: float, vehicle_type: str) -> dict:
    cfg = FARE_CONFIG.get(vehicle_type, FARE_CONFIG["car"])
    raw = cfg["base"] + (distance_km * cfg["per_km"])
    fare = max(raw, cfg["min_fare"])
    # Surge: random 1.0–1.3× depending on time-of-day simulation
    hour = datetime.now().hour
    surge = 1.3 if 8 <= hour <= 10 or 17 <= hour <= 20 else 1.0
    return {
        "estimated_fare": round(fare * surge),
        "base_fare": round(fare),
        "surge_multiplier": surge,
        "vehicle_type": vehicle_type,
        "distance_km": distance_km,
    }


# ══════════════════════════════════════════════════════════════════════════════
# PUBLIC ROUTES
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "timestamp": datetime.utcnow().isoformat()})


# ── 1. Fare Estimate ──────────────────────────────────────────────────────────
@app.route("/api/rides/estimate", methods=["POST"])
def estimate_fare():
    """
    Called by frontend when passenger tab is opened.
    Body: { distance_km: float, vehicle_type: "car"|"auto"|"bike" }
    """
    body = request.get_json(silent=True) or {}
    distance = float(body.get("distance_km", 0))
    vehicle  = body.get("vehicle_type", "car").lower()

    if distance <= 0:
        return jsonify({"error": "distance_km must be a positive number"}), 400
    if vehicle not in FARE_CONFIG:
        return jsonify({"error": f"vehicle_type must be one of {list(FARE_CONFIG.keys())}"}), 400

    result = calculate_fare(distance, vehicle)
    return jsonify(result), 200


# ── 2. Driver Registration ────────────────────────────────────────────────────
@app.route("/api/auth/driver/register", methods=["POST"])
def register_driver():
    """
    Called by frontend register form.
    Body: { name, email, phone, password, license_number, vehicle_number, vehicle_type }
    """
    body = request.get_json(silent=True) or {}

    required = ["name", "email", "phone", "password",
                "license_number", "vehicle_number", "vehicle_type"]
    missing = [f for f in required if not body.get(f)]
    if missing:
        return jsonify({"error": f"Missing fields: {', '.join(missing)}"}), 400

    email = body["email"].lower().strip()
    if email in drivers_db:
        return jsonify({"error": "An account with this email already exists"}), 409

    hashed_pw = bcrypt.hashpw(body["password"].encode(), bcrypt.gensalt()).decode()

    driver = {
        "id":             str(uuid.uuid4()),
        "name":           body["name"].strip(),
        "email":          email,
        "phone":          body["phone"].strip(),
        "password_hash":  hashed_pw,
        "license_number": body["license_number"].strip(),
        "vehicle_number": body["vehicle_number"].strip().upper(),
        "vehicle_type":   body["vehicle_type"].lower(),
        "status":         "pending",   # pending → verified → active
        "plan":           None,
        "rating":         5.0,
        "total_rides":    0,
        "total_earnings": 0,
        "today_earnings": 0,
        "created_at":     datetime.utcnow().isoformat(),
    }

    drivers_db[email] = driver
    print(f"[REGISTER] New driver: {driver['name']} ({email})")

    return jsonify({
        "message": "Application submitted. You will be verified within 24 hours.",
        "driver_id": driver["id"],
    }), 201


# ── 3. Driver Login ───────────────────────────────────────────────────────────
@app.route("/api/auth/driver/login", methods=["POST"])
def login_driver():
    """
    Called by frontend login form.
    Body: { email, password }
    Returns: { token, driver: { name, status, plan, ... } }
    """
    body  = request.get_json(silent=True) or {}
    email = body.get("email", "").lower().strip()
    password = body.get("password", "")

    driver = drivers_db.get(email)
    if not driver:
        return jsonify({"error": "Invalid credentials"}), 401

    if not bcrypt.checkpw(password.encode(), driver["password_hash"].encode()):
        return jsonify({"error": "Invalid credentials"}), 401

    token = generate_token(driver["id"])
    print(f"[LOGIN] Driver logged in: {driver['name']} ({email})")

    return jsonify({
        "token": token,
        "driver": {
            "id":             driver["id"],
            "name":           driver["name"],
            "email":          driver["email"],
            "phone":          driver["phone"],
            "status":         driver["status"],
            "plan":           driver["plan"],
            "vehicle_type":   driver["vehicle_type"],
            "vehicle_number": driver["vehicle_number"],
            "rating":         driver["rating"],
        }
    }), 200


# ══════════════════════════════════════════════════════════════════════════════
# PROTECTED ROUTES (require Bearer token)
# ══════════════════════════════════════════════════════════════════════════════

# ── 4. Driver Earnings Dashboard ──────────────────────────────────────────────
@app.route("/api/driver/earnings", methods=["GET"])
@auth_required
def driver_earnings():
    """
    Called by frontend updateDriverDashboardView().
    Returns earnings data to populate the driver dashboard mockup.
    """
    driver = request.driver

    # Collect this driver's rides
    driver_rides = [r for r in rides_db.values() if r["driver_id"] == driver["id"]]
    today = datetime.utcnow().date()
    today_rides = [r for r in driver_rides if r["date"] == str(today)]

    today_earnings = sum(r["fare"] for r in today_rides)
    total_earnings = sum(r["fare"] for r in driver_rides)
    total_rides    = len(driver_rides)
    avg_per_ride   = round(total_earnings / total_rides) if total_rides else 0

    return jsonify({
        "driver_name":    driver["name"],
        "plan":           driver["plan"],
        "rating":         driver["rating"],
        "status":         driver["status"],
        "today_earnings": today_earnings or driver["today_earnings"],
        "total_earnings": total_earnings or driver["total_earnings"],
        "today_rides":    len(today_rides),
        "total_rides":    total_rides or driver["total_rides"],
        "avg_per_ride":   avg_per_ride,
        "commission":     0,   # Always 0 — DriveNow promise
    }), 200


# ── 5. List Driver's Ride History ─────────────────────────────────────────────
@app.route("/api/driver/rides", methods=["GET"])
@auth_required
def driver_rides():
    driver = request.driver
    my_rides = [
        {k: v for k, v in r.items() if k != "driver_id"}
        for r in rides_db.values()
        if r["driver_id"] == driver["id"]
    ]
    my_rides.sort(key=lambda r: r["created_at"], reverse=True)
    return jsonify({"rides": my_rides, "count": len(my_rides)}), 200


# ── 6. Driver Profile ─────────────────────────────────────────────────────────
@app.route("/api/driver/profile", methods=["GET"])
@auth_required
def driver_profile():
    d = request.driver
    return jsonify({k: v for k, v in d.items() if k != "password_hash"}), 200


# ── 7. Update Driver Status (online/offline) ──────────────────────────────────
@app.route("/api/driver/status", methods=["PATCH"])
@auth_required
def update_driver_status():
    """Body: { status: "online" | "offline" }"""
    body   = request.get_json(silent=True) or {}
    status = body.get("status", "").lower()
    if status not in ("online", "offline"):
        return jsonify({"error": "status must be 'online' or 'offline'"}), 400
    request.driver["status"] = status
    return jsonify({"status": status}), 200


# ── 8. Subscribe to Plan ──────────────────────────────────────────────────────
@app.route("/api/driver/subscribe", methods=["POST"])
@auth_required
def subscribe():
    """Body: { plan: "basic" | "standard" | "pro", billing: "monthly" | "weekly" }"""
    body    = request.get_json(silent=True) or {}
    plan    = body.get("plan", "").lower()
    billing = body.get("billing", "monthly").lower()

    valid_plans = ("basic", "standard", "pro")
    if plan not in valid_plans:
        return jsonify({"error": f"plan must be one of {valid_plans}"}), 400

    prices = {
        "basic":    {"monthly": 999,  "weekly": 249},
        "standard": {"monthly": 1799, "weekly": 449},
        "pro":      {"monthly": 2499, "weekly": 649},
    }

    request.driver["plan"]    = plan
    request.driver["billing"] = billing
    request.driver["status"]  = "active"

    return jsonify({
        "message": f"Subscribed to {plan.title()} ({billing})",
        "plan":    plan,
        "billing": billing,
        "amount":  prices[plan][billing],
    }), 200


# ══════════════════════════════════════════════════════════════════════════════
# INTERNAL / ADMIN HELPERS (not called by current frontend but useful)
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/api/admin/seed", methods=["POST"])
def seed_demo_data():
    """Seeds a demo driver with ride history so the dashboard shows live data."""
    email = "demo@drivenow.in"
    if email not in drivers_db:
        hashed = bcrypt.hashpw(b"demo1234", bcrypt.gensalt()).decode()
        driver = {
            "id":             "demo-driver-001",
            "name":           "Ramesh Kumar",
            "email":          email,
            "phone":          "+919898989898",
            "password_hash":  hashed,
            "license_number": "GJ05-2019-001234",
            "vehicle_number": "GJ06AB1234",
            "vehicle_type":   "car",
            "status":         "active",
            "plan":           "pro",
            "billing":        "monthly",
            "rating":         4.9,
            "total_rides":    64,
            "total_earnings": 18450,
            "today_earnings": 3173,
            "created_at":     datetime.utcnow().isoformat(),
        }
        drivers_db[email] = driver

        # Seed some ride records
        today = str(datetime.utcnow().date())
        for i in range(12):
            ride_id = f"ride-demo-{i+1}"
            rides_db[ride_id] = {
                "id":          ride_id,
                "driver_id":   "demo-driver-001",
                "date":        today,
                "fare":        [200, 340, 180, 410, 290, 260, 315, 220, 180, 270, 380, 175][i],
                "distance_km": round(10 + i * 1.5, 1),
                "vehicle":     "car",
                "status":      "completed",
                "created_at":  datetime.utcnow().isoformat(),
            }

    return jsonify({"message": "Demo data seeded", "email": email, "password": "demo1234"}), 200


# ─── Run ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("\n🚗 DriveNow Backend starting on http://localhost:5000")
    print("   Frontend API base: http://localhost:5000/api\n")
    app.run(debug=True, port=5000)