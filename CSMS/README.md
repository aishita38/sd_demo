# CSMS — Counselling Slot Management System

Working local prototype based on Team T004's requirements document. This is separate from the existing SAMS admission project.

## Start

Requires Python 3.10 or later; no packages, API keys, or database services are required.

```powershell
cd "C:\Users\aishi\OneDrive\Documents\ChatGPT\sd prototype\CSMS"
python server.py
```

Open http://127.0.0.1:8765 in your browser. Alternatively double-click `start.cmd`.

All seeded accounts use **Demo@123**:

| Role | Email |
|---|---|
| Student | student@csms.demo |
| Administrator | admin@csms.demo |
| Counsellor (Meera) | counsellor@csms.demo |
| Counsellor (Arjun) | arjun@csms.demo |
| Counsellor (Nandini) | nandini@csms.demo |
| Management | management@csms.demo |

The sign-in page has shortcuts to enter each main demo role. New registration always creates a student, regardless of submitted role fields.

## Demonstration

1. Sign in as Student. Find a counsellor, filter by date and time, and book a slot. See the confirmation in My appointments and Notifications.
2. Reschedule the appointment. The previous slot becomes available again. Cancel a booking to release its slot.
3. Sign out and use Admin. Register an offline appointment for an existing active student. It occupies the same slot inventory as online bookings.
4. Under Schedules, assign a counsellor a date range **after the initial 14-day seeded range**. Morning is 09:00–13:00, afternoon 13:00–17:00, evening 17:00–20:00. Slots last 30 minutes. All days, including weekends, are enabled in this prototype. Overlapping date assignments are rejected.
5. Edit counsellor biographies and office locations under Counsellors; disable or enable accounts under Users.
6. Use the Counsellor account to view its schedule and mark its own sessions Completed or No-show. Closed sessions cannot be changed.
7. Use Management for read-only reports; export appointment CSV. Admin Reports also contains the audit trail.

## Implementation and requirement coverage

- Authentication and authorization: salted PBKDF2 passwords, server-side sessions with 12-hour expiry, HttpOnly SameSite cookies; backend role checks on mutations (FR-001–004).
- Users and profiles: student registration, admin account activation/deactivation, counsellor profile editing (FR-005–006). Adding staff accounts and changing roles currently require a code/database migration.
- Schedules: predefined shifts, date-range assignments, overlap validation, automatic slot generation (FR-007–009).
- Discovery: counsellor profiles, date/time-range filtering, available future slots (FR-010–012).
- Booking: online and offline registration, shared SQLite data, database uniqueness constraint, student overlap validation, immediate confirmation (FR-013–018).
- Appointment lifecycle: scoped appointment lists, atomic rescheduling to the same counsellor, cancellation, completion and no-show statuses (FR-019–025). Bookings confirm immediately; Pending is supported as a stored status but not created by the UI.
- In-app notifications for students and counsellors; marking as read (FR-026).
- Dashboards, status counts, slot utilization, CSV export, management read-only view (FR-027–029).
- Audit records for profile, user, schedule and appointment mutations.

`server.py` implements the HTTP application, authorization, domain operations, and SQLite persistence. The static frontend is plain HTML/CSS/JavaScript. Data lives in `csms.sqlite3`, created and seeded on first start. Slot availability is derived from appointment records, preventing contradictory availability flags. SQL `BEGIN IMMEDIATE` transactions serialize competing writes; a unique index prevents multiple non-cancelled appointments per slot. Rescheduling failure rolls back the transaction and preserves the old slot. Completed and no-show appointments retain their slots for historical accuracy.

## Validation

```powershell
python -m unittest test_system.py -v
```

Tests use a temporary database and real HTTP requests. They exercise booking, cancellation, rescheduling rollback, simultaneous online/offline booking, schedule overlap rejection, role access, student-only registration, session logout and notifications.

## Prototype limits

This runs on localhost for demonstrations. Email delivery is not connected; notifications are in-app. Updates appear after actions or Refresh rather than server push. The UI loads fonts from Google Fonts when online, with system font fallbacks. There is no password reset, login throttling, account invitation, configurable working-day calendar, or production HTTPS deployment. The code is a compact prototype rather than the document's fully separated service/repository architecture. Do not use real student records for this demo.

To choose a different port set `PORT` before starting. To use a different database set `CSMS_DB`. Stop the server before moving or replacing the database. Keep the database to preserve changes between runs.
