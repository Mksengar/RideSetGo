# DriveNow — Backend + Frontend Setup

## Folder structure
```
drivenow/
├── app.py              ← Flask backend (this file)
├── requirements.txt
├── README.md
└── frontend.html       ← Drop your frontend file here
```

## Quick start (3 steps)

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Run the backend
```bash
python app.py
# Server starts on http://localhost:5000
```

### 3. Open the frontend
Open `frontend.html` directly in your browser (double-click, or `open frontend.html`).
The frontend already points to `http://localhost:5000/api` — no changes needed.

---

## API endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/health` | — | Server health check |
| POST | `/api/rides/estimate` | — | Fare estimate for passenger tab |
| POST | `/api/auth/driver/register` | — | Driver registration form |
| POST | `/api/auth/driver/login` | — | Driver login → JWT token |
| GET | `/api/driver/earnings` | Bearer token | Dashboard data |
| GET | `/api/driver/rides` | Bearer token | Ride history |
| GET | `/api/driver/profile` | Bearer token | Driver profile |
| PATCH | `/api/driver/status` | Bearer token | Go online/offline |
| POST | `/api/driver/subscribe` | Bearer token | Choose a plan |
| POST | `/api/admin/seed` | — | Seed demo driver (dev only) |

## Demo login
First, hit the seed endpoint once to create demo data:
```
POST http://localhost:5000/api/admin/seed
```
Then log in with:
- **Email:** demo@drivenow.in
- **Password:** demo1234

## How the frontend connects

The frontend HTML uses `API_BASE_URL = 'http://localhost:5000/api'` and calls:

1. **Fare estimate** — when you click "For Passengers" tab → `POST /api/rides/estimate`
2. **Register** — on Submit Application → `POST /api/auth/driver/register`
3. **Login** — on Login to Dashboard → `POST /api/auth/driver/login`
4. **Dashboard data** — after login (or on page load if token exists) → `GET /api/driver/earnings`

JWT token is saved in `localStorage` as `driver_token` and sent as `Authorization: Bearer <token>`.

## Production notes
- Replace the in-memory `drivers_db` / `rides_db` dicts with a real database (PostgreSQL recommended).
- Set `SECRET_KEY` via environment variable: `export SECRET_KEY=your-strong-secret`
- Run with gunicorn: `gunicorn app:app -w 4 -b 0.0.0.0:5000`
- Enable HTTPS and restrict CORS to your frontend domain.
