# Skillora

Skillora is a Django skill-learning platform for Sri Ramakrishna College of Arts and Science for Women, Coimbatore. It provides department-based courses and batches, teacher-reviewed applications, attendance tracking, and certificate requests that require authorized approval.

## Run locally

1. Create and activate a Python virtual environment.
2. Install dependencies:

   ```powershell
   python -m pip install -r requirements.txt
   ```

3. Set a unique `DJANGO_SECRET_KEY` and `DJANGO_DEBUG=true` in your environment. For local use, Django defaults to SQLite; see `.env.example` for the environment variables available for PostgreSQL.
4. Apply migrations and optionally load the demonstration content:

   ```powershell
   python manage.py migrate
   python manage.py seed_data
   python manage.py createsuperuser
   python manage.py runserver
   ```

The sample student profiles on the home page are illustrative records with initials-based avatars, not real student photos or live enrollments. The seed command creates demo course accounts with documented demo credentials; change them before using any deployment.

## AI assistant

Skillora Guide uses the OpenAI Chat Completions API from the Django backend. Set `OPENAI_API_KEY` in the server environment before starting Django; optionally set `OPENAI_MODEL`, `OPENAI_BASE_URL`, and `OPENAI_TIMEOUT`. For example, in PowerShell:

```powershell
$env:OPENAI_API_KEY = "your-key"
python manage.py runserver
```

Never put the key in a template, JavaScript, or a committed settings file. Without a configured key, the chat reports that it is unavailable rather than returning a pretend AI answer. Conversation turns are kept in the user's Django session and can be cleared with **New chat**. Skillora course schedules, availability, and a signed-in student's own application, attendance, and certificate records are supplied from the database. For college-information questions, the assistant retrieves pages from [the official college website](https://srcw.ac.in/) and includes source links; if that service is unavailable, it reports the problem instead of guessing.

## PostgreSQL

Install the compatible driver from `requirements.txt`, create a PostgreSQL database, then set `DB_ENGINE=django.db.backends.postgresql`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, and `DB_PORT`. Run migrations after configuring the variables. Never commit real passwords or a production secret key.

## Applications and email

Applications are saved as **Pending** and do not create an enrollment until an assigned teacher or college administrator approves them. A batch can accept at most 10 students. If a teacher tries to accept an application after the batch has filled, Skillora keeps the application pending and offers the next batch (creating one when no later batch exists).

Email uses Django's console backend by default, which writes test messages to the development server output and does not deliver email. For actual delivery, configure `EMAIL_BACKEND`, `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_USE_TLS` or `EMAIL_USE_SSL`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, and `DEFAULT_FROM_EMAIL` using an authorized email account. The application reports console-backend messages as not delivered; use real SMTP only after obtaining the required college authorization.

## Attendance and certificates

Teachers can record attendance for a class date and verify completion. A student must have at least 75% attendance and teacher-verified completion before a certificate request is created. The student dashboard shows a locked, clearly marked sample certificate preview while they are learning; instructor-verified completion unlocks a personalized preview, while the official certificate remains unavailable until authorized faculty or administrators approve issuance. Approved students can view a printable certificate page or download an A4 landscape PDF; its QR code opens the live verification page for that issued certificate ID. The certificate uses a Skillora mark and watermark, not the college logo, campus image, or an imitated signature. It displays the college name as learning context and clearly states that it is not a college-issued credential or endorsement. Use college branding or a college signatory only after authorization and receipt of genuine approved assets and details.

## Demonstration accounts

The optional `seed_data` command creates the following local-only accounts:

| Username | Role |
| --- | --- |
| `skillora-demo-teacher` | Approved teacher (display name: Raja Sharma) |
| `faculty` | College administrator (Django superuser; may already exist) |
| `student01` | Student (may already exist) |

New accounts created by the command use the password `Skillora@123`; rerunning the command never resets an existing account's password or changes its role. Do not use demo credentials outside a local development environment. For a new administrator, create a Django superuser with `python manage.py createsuperuser`.

## Checks

```powershell
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test core
```
