from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
from pymongo import MongoClient
from datetime import datetime, timedelta
import requests
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
CORS(app)

# MongoDB Configuration
MONGO_URI = os.getenv("MONGO_CONNECTION_STRING")
client = MongoClient(MONGO_URI)
db = client["doctor_consultation"]
appointments_collection = db["patients_appointments"]

# Calendly Configuration
CALENDLY_API_KEY = os.getenv("CALENDLY_API_KEY")
CALENDLY_EVENT_TYPE_URI = os.getenv("CALENDLY_EVENT_TYPE_URI")

# Email Configuration
EMAIL_HOST = os.getenv("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", 587))
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
DOCTOR_EMAIL = os.getenv("DOCTOR_EMAIL")


def calculate_priority(issues):
    """Calculate priority based on patient issues"""
    urgent_keywords = [
        "emergency",
        "severe",
        "acute",
        "urgent",
        "critical",
        "bleeding",
        "chest pain",
    ]
    high_keywords = ["pain", "fever", "infection", "injury"]

    issues_lower = issues.lower()

    if any(keyword in issues_lower for keyword in urgent_keywords):
        return "High"
    elif any(keyword in issues_lower for keyword in high_keywords):
        return "Medium"
    else:
        return "Low"


def send_email(to_email, subject, body):
    """Send email notification"""
    try:
        msg = MIMEMultipart()
        msg["From"] = EMAIL_USER
        msg["To"] = to_email
        msg["Subject"] = subject

        msg.attach(MIMEText(body, "html"))

        server = smtplib.SMTP(EMAIL_HOST, EMAIL_PORT)
        server.starttls()
        server.login(EMAIL_USER, EMAIL_PASSWORD)
        text = msg.as_string()
        server.sendmail(EMAIL_USER, to_email, text)
        server.quit()
        return True
    except Exception as e:
        print(f"Email error: {str(e)}")
        return False


def create_calendly_booking(name, email, start_time):
    """Create booking in Calendly"""
    try:
        headers = {
            "Authorization": f"Bearer {CALENDLY_API_KEY}",
            "Content-Type": "application/json",
        }

        # Get available times first
        url = "https://api.calendly.com/scheduled_events"

        # Create invitee data
        invitee_data = {
            "event": CALENDLY_EVENT_TYPE_URI,
            "name": name,
            "email": email,
            "start_time": start_time,
        }

        # Note: Calendly scheduling requires specific API endpoints
        # This is a simplified version - you may need to use event_type scheduling

        return {"success": True, "event_id": "calendly_event_id"}
    except Exception as e:
        print(f"Calendly error: {str(e)}")
        return {"success": False, "error": str(e)}


@app.route("/")
def index():
    """Serve the patient booking form"""
    return render_template("index.html")


@app.route("/doctor-dashboard")
def doctor_dashboard():
    """Serve the doctor dashboard"""
    return render_template("dashboard.html")


@app.route("/api/book-appointment", methods=["POST"])
def book_appointment():
    """Handle appointment booking"""
    try:
        data = request.json

        patient_name = data.get("patient_name")
        patient_email = data.get("patient_email")
        issues = data.get("issues")
        preferred_time = data.get("preferred_time")

        # Validate required fields
        if not all([patient_name, patient_email, issues, preferred_time]):
            return (
                jsonify({"success": False, "message": "All fields are required"}),
                400,
            )

        # Calculate priority
        priority = calculate_priority(issues)

        # Create appointment document
        appointment = {
            "patient_name": patient_name,
            "patient_email": patient_email,
            "issues": issues,
            "preferred_time": preferred_time,
            "priority": priority,
            "status": "pending",
            "created_at": datetime.utcnow().isoformat(),
            "doctor_approved": False,
            "google_meet_link": None,
        }

        # Store in MongoDB
        result = appointments_collection.insert_one(appointment)
        appointment["_id"] = str(result.inserted_id)

        # Create Calendly booking (simplified)
        calendly_result = create_calendly_booking(
            patient_name, patient_email, preferred_time
        )

        # Send confirmation email to patient
        patient_email_body = f"""
        <html>
            <body>
                <h2>Booking Confirmation</h2>
                <p>Dear {patient_name},</p>
                <p>Your appointment request has been received successfully.</p>
                <p><strong>Details:</strong></p>
                <ul>
                    <li>Preferred Time: {preferred_time}</li>
                    <li>Issues: {issues}</li>
                    <li>Priority: {priority}</li>
                </ul>
                <p>Your appointment is pending doctor confirmation. You will receive another email once the doctor approves.</p>
                <p>Best regards,<br>Medical Consultation Team</p>
            </body>
        </html>
        """
        send_email(patient_email, "Appointment Booking Received", patient_email_body)

        # Notify doctor
        doctor_email_body = f"""
        <html>
            <body>
                <h2>New Appointment Request</h2>
                <p><strong>Patient:</strong> {patient_name}</p>
                <p><strong>Email:</strong> {patient_email}</p>
                <p><strong>Issues:</strong> {issues}</p>
                <p><strong>Preferred Time:</strong> {preferred_time}</p>
                <p><strong>Priority:</strong> {priority}</p>
                <p>Please log in to your dashboard to approve or reject this appointment.</p>
            </body>
        </html>
        """
        send_email(
            DOCTOR_EMAIL, f"New Appointment - Priority: {priority}", doctor_email_body
        )

        return jsonify(
            {
                "success": True,
                "message": "Form submitted successfully! Email will be sent shortly",
                "appointment_id": appointment["_id"],
            }
        )

    except Exception as e:
        print(f"Error: {str(e)}")
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/appointments", methods=["GET"])
def get_appointments():
    """Get all appointments for doctor dashboard"""
    try:
        appointments = list(appointments_collection.find().sort("created_at", -1))

        # Convert ObjectId to string
        for apt in appointments:
            apt["_id"] = str(apt["_id"])

        # Sort by priority
        priority_order = {"High": 0, "Medium": 1, "Low": 2}
        appointments.sort(key=lambda x: priority_order.get(x["priority"], 3))

        return jsonify({"success": True, "appointments": appointments})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/appointments/<appointment_id>/approve", methods=["POST"])
def approve_appointment(appointment_id):
    """Approve an appointment"""
    try:
        from bson.objectid import ObjectId

        # Create Google Meet link (simplified - you'd integrate with Google Meet API)
        meet_link = f"https://meet.google.com/{appointment_id[:10]}"

        # Update appointment
        result = appointments_collection.update_one(
            {"_id": ObjectId(appointment_id)},
            {
                "$set": {
                    "status": "approved",
                    "doctor_approved": True,
                    "google_meet_link": meet_link,
                    "approved_at": datetime.utcnow().isoformat(),
                }
            },
        )

        # Get appointment details
        appointment = appointments_collection.find_one(
            {"_id": ObjectId(appointment_id)}
        )

        # Send confirmation email to patient
        email_body = f"""
        <html>
            <body>
                <h2>Appointment Confirmed!</h2>
                <p>Dear {appointment['patient_name']},</p>
                <p>Your appointment has been approved by the doctor.</p>
                <p><strong>Details:</strong></p>
                <ul>
                    <li>Time: {appointment['preferred_time']}</li>
                    <li>Google Meet Link: <a href="{meet_link}">{meet_link}</a></li>
                </ul>
                <p>You will receive a reminder 10 minutes before your consultation.</p>
                <p>Best regards,<br>Medical Consultation Team</p>
            </body>
        </html>
        """
        send_email(appointment["patient_email"], "Appointment Confirmed", email_body)

        return jsonify({"success": True, "message": "Appointment approved"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/appointments/<appointment_id>/reject", methods=["POST"])
def reject_appointment(appointment_id):
    """Reject an appointment"""
    try:
        from bson.objectid import ObjectId

        # Update appointment
        appointments_collection.update_one(
            {"_id": ObjectId(appointment_id)},
            {
                "$set": {
                    "status": "rejected",
                    "doctor_approved": False,
                    "rejected_at": datetime.utcnow().isoformat(),
                }
            },
        )

        # Get appointment details
        appointment = appointments_collection.find_one(
            {"_id": ObjectId(appointment_id)}
        )

        # Send rejection email with reschedule link
        reschedule_link = "https://online-dr-consultation.onrender.com/api/appointments"  # Your booking page
        email_body = f"""
        <html>
            <body>
                <h2>Appointment Update</h2>
                <p>Dear {appointment['patient_name']},</p>
                <p>Unfortunately, the doctor is not available at your requested time.</p>
                <p>Please reschedule your appointment: <a href="{reschedule_link}">Reschedule Now</a></p>
                <p>We apologize for the inconvenience.</p>
                <p>Best regards,<br>Medical Consultation Team</p>
            </body>
        </html>
        """
        send_email(
            appointment["patient_email"],
            "Appointment Rescheduling Required",
            email_body,
        )

        return jsonify({"success": True, "message": "Appointment rejected"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5000)
