from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from werkzeug.middleware.proxy_fix import ProxyFix

app = Flask(__name__)

app.wsgi_app = ProxyFix(
    app.wsgi_app,
    x_for=1,
    x_proto=1,
    x_host=1
)

app.secret_key = os.environ.get(
    "SECRET_KEY",
    "change-this-secret-key-before-production"
)

app.config["SESSION_COOKIE_SECURE"] = True
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"


# =========================================================
# DATABASE
# =========================================================

def get_database_url():
    database_url = os.environ.get("DATABASE_URL")

    if not database_url:
        raise RuntimeError(
            "DATABASE_URL environment variable is not configured."
        )

    # Some providers may still return postgres://
    if database_url.startswith("postgres://"):
        database_url = database_url.replace(
            "postgres://",
            "postgresql://",
            1
        )

    return database_url


def get_connection():
    return psycopg2.connect(get_database_url())


def init_database():
    connection = get_connection()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    first_name VARCHAR(100) NOT NULL,
                    last_name VARCHAR(100) NOT NULL,
                    email VARCHAR(255) NOT NULL UNIQUE,
                    phone VARCHAR(30) NOT NULL,
                    latitude DOUBLE PRECISION NOT NULL,
                    longitude DOUBLE PRECISION NOT NULL,
                    address TEXT,
                    created_at TIMESTAMP NOT NULL
                )
                """
            )

        connection.commit()

    finally:
        connection.close()


# =========================================================
# VALIDATION
# =========================================================

def valid_email(email):
    pattern = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
    return re.match(pattern, email) is not None


def valid_phone(phone):
    cleaned = re.sub(r"[\s\-()+]", "", phone)
    return cleaned.isdigit() and 7 <= len(cleaned) <= 15


def valid_coordinates(latitude, longitude):
    try:
        latitude = float(latitude)
        longitude = float(longitude)

        return (
            -90 <= latitude <= 90
            and -180 <= longitude <= 180
        )

    except (TypeError, ValueError):
        return False


# =========================================================
# REVERSE GEOCODING
# =========================================================

def get_address(latitude, longitude):
    try:
        response = requests.get(
            "https://nominatim.openstreetmap.org/reverse",
            params={
                "lat": latitude,
                "lon": longitude,
                "format": "json",
                "zoom": 18,
                "addressdetails": 1
            },
            headers={
                "User-Agent": "LotusHeartFlaskWebsite/1.0"
            },
            timeout=10
        )

        response.raise_for_status()

        data = response.json()

        return data.get(
            "display_name",
            "Address unavailable"
        )

    except Exception as error:
        print("Reverse geocoding error:", error)
        return "Address unavailable"


# =========================================================
# REGISTER
# =========================================================

@app.route("/", methods=["GET", "POST"])
def register():

    if "user_id" in session:
        return redirect(url_for("home"))

    if request.method == "POST":

        first_name = request.form.get(
            "first_name",
            ""
        ).strip()

        last_name = request.form.get(
            "last_name",
            ""
        ).strip()

        email = request.form.get(
            "email",
            ""
        ).strip().lower()

        phone = request.form.get(
            "phone",
            ""
        ).strip()

        latitude = request.form.get(
            "latitude",
            ""
        ).strip()

        longitude = request.form.get(
            "longitude",
            ""
        ).strip()

        # -------------------------
        # Required fields
        # -------------------------

        if not first_name:
            return render_template(
                "register.html",
                error="Please enter your first name."
            )

        if not last_name:
            return render_template(
                "register.html",
                error="Please enter your last name."
            )

        if not email:
            return render_template(
                "register.html",
                error="Please enter your email."
            )

        if not phone:
            return render_template(
                "register.html",
                error="Please enter your phone number."
            )

        if not latitude or not longitude:
            return render_template(
                "register.html",
                error="Please allow your location first."
            )

        # -------------------------
        # Validation
        # -------------------------

        if not valid_email(email):
            return render_template(
                "register.html",
                error="Please enter a valid email address."
            )

        if not valid_phone(phone):
            return render_template(
                "register.html",
                error="Please enter a valid phone number."
            )

        if not valid_coordinates(latitude, longitude):
            return render_template(
                "register.html",
                error="Invalid location coordinates."
            )

        latitude = float(latitude)
        longitude = float(longitude)

        connection = get_connection()

        try:

            with connection.cursor(
                cursor_factory=RealDictCursor
            ) as cursor:

                # -------------------------
                # Check existing email
                # -------------------------

                cursor.execute(
                    """
                    SELECT id
                    FROM users
                    WHERE email = %s
                    """,
                    (email,)
                )

                existing_user = cursor.fetchone()

                if existing_user:

                    return render_template(
                        "register.html",
                        error="This email is already registered."
                    )

                # -------------------------
                # Get address
                # -------------------------

                address = get_address(
                    latitude,
                    longitude
                )

                # -------------------------
                # Save user
                # -------------------------

                cursor.execute(
                    """
                    INSERT INTO users (
                        first_name,
                        last_name,
                        email,
                        phone,
                        latitude,
                        longitude,
                        address,
                        created_at
                    )
                    VALUES (
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s
                    )
                    RETURNING id
                    """,
                    (
                        first_name,
                        last_name,
                        email,
                        phone,
                        latitude,
                        longitude,
                        address,
                        datetime.now(timezone.utc)
                    )
                )

                user = cursor.fetchone()

            connection.commit()

        except Exception as error:

            connection.rollback()

            print(
                "Registration error:",
                error
            )

            return render_template(
                "register.html",
                error="Something went wrong. Please try again."
            )

        finally:
            connection.close()

        # -------------------------
        # Login session
        # -------------------------

        session["user_id"] = user["id"]

        session["user_name"] = (
            f"{first_name} {last_name}"
        )

        return redirect(
            url_for("home")
        )

    return render_template(
        "register.html"
    )


# =========================================================
# HOME
# =========================================================

@app.route("/home")
def home():

    if "user_id" not in session:
        return redirect(
            url_for("register")
        )

    return render_template(
        "home.html",
        user_name=session.get(
            "user_name",
            "Friend"
        )
    )


# =========================================================
# LOGOUT
# =========================================================

@app.route("/logout")
def logout():

    session.clear()

    return redirect(
        url_for("register")
    )


# =========================================================
# ADMIN
# =========================================================

@app.route("/admin/users")
def admin_users():

    admin_key = os.environ.get(
        "ADMIN_KEY"
    )

    provided_key = request.args.get(
        "key"
    )

    if not admin_key:
        return "ADMIN_KEY is not configured.", 500

    if not provided_key or provided_key != admin_key:
        return "Unauthorized", 401

    connection = get_connection()

    try:

        with connection.cursor(
            cursor_factory=RealDictCursor
        ) as cursor:

            cursor.execute(
                """
                SELECT
                    id,
                    first_name,
                    last_name,
                    email,
                    phone,
                    latitude,
                    longitude,
                    address,
                    created_at
                FROM users
                ORDER BY created_at DESC
                """
            )

            users = cursor.fetchall()

    finally:
        connection.close()

    return render_template(
        "admin.html",
        users=users
    )


# =========================================================
# HEALTH CHECK
# =========================================================

@app.route("/health")
def health():

    return jsonify({
        "status": "ok"
    })


# =========================================================
# STARTUP
# =========================================================

def startup_database():

    try:

        init_database()

        print(
            "Database initialized successfully."
        )

    except Exception as error:

        print(
            "Database initialization error:",
            error
        )


# =========================================================
# LOCAL RUN
# =========================================================

if __name__ == "__main__":

    startup_database()

    port = int(
        os.environ.get(
            "PORT",
            5000
        )
    )

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False
    )