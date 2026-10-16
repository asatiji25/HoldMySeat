# HoldMySeat — Fair-Queue Seat Ticket Booking Backend

HoldMySeat is a beginner-friendly Python backend prototype for a college concert with 500 seats and a large booking rush. Students join a server-numbered queue, are admitted in order, temporarily reserve seats, and simulate payment. PostgreSQL transactions protect seat claims.

## Features

- 500 seats seeded automatically (configurable with `SEAT_COUNT`)
- Virtual queue with queue number, status, and position lookup
- Explicit queue admission (`POST /queue/admit-next`) so the operator can admit waiting users in order
- Temporary holds that expire after 5 minutes (`HOLD_MINUTES`)
- Seat cancellation and reallocation
- Simulated successful, failed, and delayed payment outcomes
- Idempotency keys for reservation and payment retries
- Booking history, reservation status, and contention metrics
- PostgreSQL + Docker Compose
- Automatic OpenAPI docs at `/docs`

## Important design notes

1. The queue admission endpoint admits one waiting user per call, in ascending queue-number order. An operator or simple script can call it repeatedly to admit a batch.
2. The seat row is selected with `SELECT ... FOR UPDATE`. PostgreSQL serializes competing claims for the same seat. The seat status is then changed inside the same transaction.
3. The database enforces unique seat labels, queue numbers, and idempotency keys.
4. The five-minute expiry cleanup runs periodically and can also be triggered using `/admin/cleanup-expired`.
5. Payment is simulated. This project does not collect real card details or connect to a payment provider.
6. For a production deployment, add authentication/authorization for admin endpoints, migrations, structured logging, rate limits, stronger queue-number allocation, and a robust distributed worker. The current app is a recruitment-task prototype.

## Run with Docker

Prerequisite: install and start Docker Desktop.

From the `HoldMySeat` folder:

```bash
docker compose up --build
```

Wait for the database health check and API startup, then open:

- API root: http://localhost:8000/
- Interactive API docs: http://localhost:8000/docs
- Health check: http://localhost:8000/health

Stop with `Ctrl+C`. To remove the database volume and reset all data, run `docker compose down -v` (this permanently deletes the local test data).

## Example API walkthrough

Use the `/docs` page and click **Try it out** for each request.

### 1. Join the queue

`POST /queue/join`

```json
{"user_id":"student-001"}
```

Note the returned `queue_number`.

### 2. Admit the next waiting student

`POST /queue/admit-next`

No request body. This admits the student with the lowest waiting queue number. Call it once per student you want to admit.

### 3. Reserve a seat

`POST /reservations`

```json
{
  "user_id":"student-001",
  "seat_label":"S001",
  "idempotency_key":"reserve-student-001-attempt-1"
}
```

Copy the returned `reservation_id`.

### 4. Simulate payment

`POST /reservations/1/payment` (replace `1` with your reservation ID)

```json
{
  "outcome":"success",
  "idempotency_key":"payment-student-001-attempt-1"
}
```

`outcome` may be `success`, `failure`, or `delayed`. Successful payment confirms the reservation and marks the seat BOOKED. Failed payment releases the seat. Delayed payment leaves the temporary hold pending until a later action or expiry.

### 5. Check seats and history

- `GET /seats`
- `GET /reservations/1`
- `GET /bookings/history/student-001`
- `GET /queue/student-001`
- `GET /metrics/contention`

### 6. Cancel a reservation

`POST /reservations/1/cancel`

```json
{"user_id":"student-001"}
```

## Endpoint summary

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/health` | Service health |
| GET | `/seats` | List seats; optional `?status=AVAILABLE` |
| POST | `/queue/join` | Join the queue |
| GET | `/queue/{user_id}` | Queue status and people waiting ahead |
| POST | `/queue/admit-next` | Admit the next waiting student |
| POST | `/reservations` | Hold a seat temporarily |
| GET | `/reservations/{reservation_id}` | Reservation status |
| POST | `/reservations/{reservation_id}/payment` | Simulate payment |
| POST | `/reservations/{reservation_id}/cancel` | Cancel and release a seat |
| GET | `/bookings/history/{user_id}` | Booking/reservation history |
| GET | `/metrics/contention` | Aggregate contention metrics |
| POST | `/admin/cleanup-expired` | Manually run expiry cleanup |

## Data model

- `seats`: seat label and current state (`AVAILABLE`, `HELD`, `BOOKED`)
- `queue_entries`: student, queue number, queue state, timestamps
- `reservations`: student, seat, state, expiry and idempotency key
- `payments`: simulated payment result and idempotency key
- `booking_events`: audit trail for queue/booking outcomes

See `docs/erd.md` and `docs/workflow.md`.

## Tests

The included pytest checks validate project structure and required route declarations:

```bash
pip install -r requirements.txt
pytest -q
```

These are lightweight contract checks, not a substitute for running integration tests against PostgreSQL.

## Load testing

A Locust starter scenario is in `loadtest/locustfile.py`. Install Locust and run it only after the service is running:

```bash
pip install locust
locust -f loadtest/locustfile.py --host http://localhost:8000
```

Open the Locust URL shown in the terminal, start with a small number of users, and review request rate, response time and failures. Do not claim load-test results until you actually run the test and record the measured output.

## Suggested report wording

“HoldMySeat combines an ordered waiting room with transactional seat reservation. The queue regulates admission during a traffic spike, while PostgreSQL row-level locking and uniqueness constraints protect the core booking state. Temporary holds, cancellation, payment simulation, idempotent retries and contention metrics cover common failure scenarios. Load testing is used to measure behavior under concurrent traffic.”

## Limitations

- This is a task prototype, not a production ticketing platform.
- The queue admission endpoint is intentionally simple and manually triggered.
- Payment outcomes are simulated.
- There is no user authentication, real payment gateway, frontend, Redis cache, or message broker.
- Run the concurrency/load tests and document actual results before presenting performance claims.
