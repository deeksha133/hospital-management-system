import os
import sqlite3
from datetime import date
from functools import wraps

from flask import Flask, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.getenv("SECRET_KEY", "dev-change-this-key"),
    DATABASE=os.path.join(app.instance_path, "hospital.db"),
)
os.makedirs(app.instance_path, exist_ok=True)


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    with app.open_resource("schema.sql") as schema:
        db.executescript(schema.read().decode("utf8"))
    admin = db.execute("SELECT id FROM users WHERE username = ?", ("admin",)).fetchone()
    if not admin:
        db.execute(
            "INSERT INTO users (username, password) VALUES (?, ?)",
            ("admin", generate_password_hash("admin123")),
        )
    db.commit()


# Initialize SQLite when Gunicorn imports the application on Render.
with app.app_context():
    init_db()


def login_required(view):
    @wraps(view)
    def wrapped(**kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login"))
        return view(**kwargs)
    return wrapped


@app.route("/login", methods=("GET", "POST"))
def login():
    if request.method == "POST":
        user = get_db().execute(
            "SELECT * FROM users WHERE username = ?", (request.form["username"].strip(),)
        ).fetchone()
        if user and check_password_hash(user["password"], request.form["password"]):
            session.clear()
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            return redirect(url_for("dashboard"))
        flash("Invalid username or password.", "danger")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def dashboard():
    db = get_db()
    stats = {
        "patients": db.execute("SELECT COUNT(*) FROM patients").fetchone()[0],
        "doctors": db.execute("SELECT COUNT(*) FROM doctors").fetchone()[0],
        "appointments": db.execute("SELECT COUNT(*) FROM appointments WHERE appointment_date >= ?", (date.today().isoformat(),)).fetchone()[0],
        "revenue": db.execute("SELECT COALESCE(SUM(amount), 0) FROM bills WHERE status='Paid'").fetchone()[0],
    }
    recent = db.execute("""
        SELECT a.*, p.name patient_name, d.name doctor_name FROM appointments a
        JOIN patients p ON p.id=a.patient_id JOIN doctors d ON d.id=a.doctor_id
        ORDER BY a.appointment_date DESC, a.appointment_time DESC LIMIT 6
    """).fetchall()
    return render_template("dashboard.html", stats=stats, recent=recent)


@app.route("/patients", methods=("GET", "POST"))
@login_required
def patients():
    db = get_db()
    if request.method == "POST":
        db.execute("INSERT INTO patients(name, age, gender, phone, blood_group, address) VALUES(?,?,?,?,?,?)",
                   tuple(request.form[k].strip() for k in ("name", "age", "gender", "phone", "blood_group", "address")))
        db.commit(); flash("Patient registered successfully.", "success")
        return redirect(url_for("patients"))
    q = request.args.get("q", "").strip()
    rows = db.execute("SELECT * FROM patients WHERE name LIKE ? OR phone LIKE ? ORDER BY id DESC", (f"%{q}%", f"%{q}%")).fetchall()
    return render_template("patients.html", rows=rows, q=q)


@app.post("/patients/<int:item_id>/delete")
@login_required
def delete_patient(item_id):
    try:
        get_db().execute("DELETE FROM patients WHERE id=?", (item_id,)); get_db().commit()
        flash("Patient deleted.", "success")
    except sqlite3.IntegrityError:
        flash("This patient has appointments or bills and cannot be deleted.", "danger")
    return redirect(url_for("patients"))


@app.route("/doctors", methods=("GET", "POST"))
@login_required
def doctors():
    db = get_db()
    if request.method == "POST":
        db.execute("INSERT INTO doctors(name, specialization, phone, email, availability) VALUES(?,?,?,?,?)",
                   tuple(request.form[k].strip() for k in ("name", "specialization", "phone", "email", "availability")))
        db.commit(); flash("Doctor added successfully.", "success")
        return redirect(url_for("doctors"))
    rows = db.execute("SELECT * FROM doctors ORDER BY id DESC").fetchall()
    return render_template("doctors.html", rows=rows)


@app.post("/doctors/<int:item_id>/delete")
@login_required
def delete_doctor(item_id):
    try:
        get_db().execute("DELETE FROM doctors WHERE id=?", (item_id,)); get_db().commit()
        flash("Doctor deleted.", "success")
    except sqlite3.IntegrityError:
        flash("This doctor has appointments and cannot be deleted.", "danger")
    return redirect(url_for("doctors"))


@app.route("/appointments", methods=("GET", "POST"))
@login_required
def appointments():
    db = get_db()
    if request.method == "POST":
        db.execute("INSERT INTO appointments(patient_id,doctor_id,appointment_date,appointment_time,reason,status) VALUES(?,?,?,?,?,?)",
                   tuple(request.form[k] for k in ("patient_id", "doctor_id", "appointment_date", "appointment_time", "reason", "status")))
        db.commit(); flash("Appointment booked successfully.", "success")
        return redirect(url_for("appointments"))
    rows = db.execute("SELECT a.*,p.name patient_name,d.name doctor_name FROM appointments a JOIN patients p ON p.id=a.patient_id JOIN doctors d ON d.id=a.doctor_id ORDER BY appointment_date DESC").fetchall()
    return render_template("appointments.html", rows=rows,
                           patients=db.execute("SELECT id,name FROM patients ORDER BY name").fetchall(),
                           doctors=db.execute("SELECT id,name,specialization FROM doctors ORDER BY name").fetchall())


@app.post("/appointments/<int:item_id>/status")
@login_required
def appointment_status(item_id):
    get_db().execute("UPDATE appointments SET status=? WHERE id=?", (request.form["status"], item_id)); get_db().commit()
    flash("Appointment status updated.", "success")
    return redirect(url_for("appointments"))


@app.route("/billing", methods=("GET", "POST"))
@login_required
def billing():
    db = get_db()
    if request.method == "POST":
        db.execute("INSERT INTO bills(patient_id,description,amount,bill_date,status) VALUES(?,?,?,?,?)",
                   tuple(request.form[k] for k in ("patient_id", "description", "amount", "bill_date", "status")))
        db.commit(); flash("Bill created successfully.", "success")
        return redirect(url_for("billing"))
    rows = db.execute("SELECT b.*,p.name patient_name FROM bills b JOIN patients p ON p.id=b.patient_id ORDER BY b.id DESC").fetchall()
    return render_template("billing.html", rows=rows, patients=db.execute("SELECT id,name FROM patients ORDER BY name").fetchall(), today=date.today().isoformat())


@app.post("/billing/<int:item_id>/status")
@login_required
def bill_status(item_id):
    get_db().execute("UPDATE bills SET status=? WHERE id=?", (request.form["status"], item_id)); get_db().commit()
    flash("Payment status updated.", "success")
    return redirect(url_for("billing"))


@app.cli.command("init-db")
def init_db_command():
    init_db(); print("Database initialized.")


if __name__ == "__main__":
    with app.app_context(): init_db()
    app.run(debug=True)
