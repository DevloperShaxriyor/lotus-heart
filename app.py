import os
import re
from datetime import datetime

import requests
import psycopg2
from psycopg2.extras import RealDictCursor

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash
)


app = Flask(__name__)

# Render'da Environment Variable orqali beramiz.
# Lokal test uchun esa vaqtinchalik qiymat ishlatamiz.
app.secret_key = os.environ.get(
    "SECRET_KEY",
    "local-development-secret-change-me"
)


# ============================================================
# DATABASE
# ============================================================

def get_database_url():
    database_url = os.environ.get("DATABASE_URL")

    if not database_url:
        return None

    # Ba'zi hostinglarda postgres:// kelishi mumkin.
    # psycopg2 uchun postgresql:// ishlatamiz.
    if database_url.startswith("postgres://"):
        database_url = database_url.replace(
            "postgres://",
            "postgresql://",
            1
        )

    return database_url


def get_connection():
    database_url = get_database_url()

    if not database_url:
        raise RuntimeError(
            "DATABASE_URL environment variable is not configured."
        )

    return psycopg2.connect(database_url)


def init_database():
    connection = get_connection()

    try:
        with connection.cursor() as cursor:

            cursor.execute("""
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
                );
            """)

        connection.commit()

    finally:
        connection.close()


# ============================================================
# VALIDATION
# ============================================================

def valid_email(email):
    pattern = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
    return re.match(pattern, email) is not None


def valid_phone(phone):
    digits = re.sub(r"\D", "", phone)
    return 7 <= len(digits) <= 15


def valid_coordinates(latitude, longitude):

    try:
        latitude = float(latitude)
        longitude = float(longitude)

        if not -90 <= latitude <= 90:
            return False

        if not -180 <= longitude <= 180:
            return False

        return True

    except (TypeError, ValueError):
        return False


# ============================================================
# REVERSE GEOCODING
# ============================================================

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
                "User-Agent":
                    "LotusHeartFlaskWebsite/1.0"
            },
            timeout=10
        )

        if response.ok:

            data = response.json()

            return data.get(
                "display_name",
                "Address unavailable"
            )

    except requests.RequestException:
        pass

    return "Address unavailable"


# ============================================================
# REGISTER
# ============================================================

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


        # ----------------------------------------------------
        # VALIDATION
        # ----------------------------------------------------

        if not first_name:
            flash(
                "Please enter your first name.",
                "error"
            )

            return redirect(
                url_for("register")
            )


        if not last_name:
            flash(
                "Please enter your last name.",
                "error"
            )

            return redirect(
                url_for("register")
            )


        if not valid_email(email):

            flash(
                "Please enter a valid email address.",
                "error"
            )

            return redirect(
                url_for("register")
            )


        if not valid_phone(phone):

            flash(
                "Please enter a valid phone number.",
                "error"
            )

            return redirect(
                url_for("register")
            )


        if not valid_coordinates(
            latitude,
            longitude
        ):

            flash(
                "Please allow location access.",
                "error"
            )

            return redirect(
                url_for("register")
            )


        latitude = float(latitude)
        longitude = float(longitude)


        # ----------------------------------------------------
        # CHECK EXISTING EMAIL
        # ----------------------------------------------------

        connection = get_connection()

        try:

            with connection.cursor(
                cursor_factory=RealDictCursor
            ) as cursor:

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

                    flash(
                        "This email is already registered.",
                        "error"
                    )

                    return redirect(
                        url_for("register")
                    )


                # ------------------------------------------------
                # GET ADDRESS
                # ------------------------------------------------

                address = get_address(
                    latitude,
                    longitude
                )


                # ------------------------------------------------
                # SAVE USER
                # ------------------------------------------------

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
                        datetime.utcnow()
                    )
                )

                user = cursor.fetchone()

                connection.commit()


                # ------------------------------------------------
                # SESSION
                # ------------------------------------------------

                session["user_id"] = user["id"]

                session["user_name"] = first_name

                return redirect(
                    url_for("home")
                )

        except psycopg2.Error:

            connection.rollback()

            flash(
                "Database error. Please try again.",
                "error"
            )

            return redirect(
                url_for("register")
            )

        finally:

            connection.close()


    return render_template(
        "register.html"
    )


# ============================================================
# HOME
# ============================================================

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
            ""
        )
    )


# ============================================================
# LOGOUT
# ============================================================

@app.route("/logout")
def logout():

    session.clear()

    return redirect(
        url_for("register")
    )


# ============================================================
# ADMIN
# ============================================================

@app.route("/admin/users")
def admin_users():

    # Hozircha oddiy admin secret orqali himoyalaymiz.
    admin_key = request.args.get("key")

    correct_key = os.environ.get(
        "ADMIN_KEY"
    )

    if not correct_key:
        return "ADMIN_KEY is not configured.", 500

    if admin_key != correct_key:
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
                ORDER BY id DESC
                """
            )

            users = cursor.fetchall()

    finally:

        connection.close()


    return render_template(
        "admin.html",
        users=users
    )


# ============================================================
# HEALTH CHECK
# ============================================================

@app.route("/health")
def health():

    return {
        "status": "ok"
    }


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    init_database()

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