from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import os
import threading
import time

from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from .database import Base, engine, get_db, SessionLocal
from .models import Seat, QueueEntry, Reservation, Payment, BookingEvent, utcnow
from .schemas import JoinQueueRequest, ReserveRequest, PaymentRequest, CancelRequest

HOLD_MINUTES = int(os.getenv("HOLD_MINUTES", "5"))
QUEUE_BATCH_SIZE = int(os.getenv("QUEUE_BATCH_SIZE", "50"))
SEAT_COUNT = int(os.getenv("SEAT_COUNT", "500"))
_cleanup_started = False

def record_event(db, user_id, seat_label, event_type, details=""):
    db.add(BookingEvent(user_id=user_id, seat_label=seat_label,
                        event_type=event_type, details=details))

def seed_seats(db: Session):
    if db.query(Seat).count() == 0:
        for number in range(1, SEAT_COUNT + 1):
            db.add(Seat(label=f"S{number:03d}", status="AVAILABLE"))
        db.commit()

def cleanup_expired_once(db: Session):
    now = utcnow()
    expired = db.execute(
        select(Reservation).where(
            Reservation.status == "HELD",
            Reservation.expires_at <= now
        ).with_for_update(skip_locked=True)
    ).scalars().all()
    for reservation in expired:
        seat = db.execute(
            select(Seat).where(Seat.id == reservation.seat_id).with_for_update()
        ).scalar_one()
        reservation.status = "EXPIRED"
        seat.status = "AVAILABLE"
        record_event(db, reservation.user_id, seat.label, "RESERVATION_EXPIRED",
                     f"Reservation {reservation.id} expired")
    if expired:
        db.commit()
    return len(expired)

def cleanup_loop():
    while True:
        try:
            from .database import SessionLocal
            with SessionLocal() as db:
                cleanup_expired_once(db)
        except Exception:
            # A later pass retries cleanup; errors are also visible in server logs.
            pass
        time.sleep(5)

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _cleanup_started
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        seed_seats(db)
    if not _cleanup_started:
        threading.Thread(target=cleanup_loop, daemon=True).start()
        _cleanup_started = True
    yield

app = FastAPI(
    title="HoldMySeat API",
    description="A queue-based concert ticket booking backend with temporary reservations.",
    version="1.0.0",
    lifespan=lifespan
)

@app.get("/")
def root():
    return {"project": "HoldMySeat", "status": "running", "docs": "/docs"}

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/seats")
def list_seats(status: str | None = None, db: Session = Depends(get_db)):
    query = select(Seat)
    if status:
        normalized = status.upper()
        if normalized not in {"AVAILABLE", "HELD", "BOOKED"}:
            raise HTTPException(400, "status must be AVAILABLE, HELD, or BOOKED")
        query = query.where(Seat.status == normalized)
    seats = db.execute(query.order_by(Seat.id)).scalars().all()
    return [{"label": s.label, "status": s.status} for s in seats]

@app.post("/queue/join", status_code=201)
def join_queue(body: JoinQueueRequest, db: Session = Depends(get_db)):
    # Rejoining returns the existing active queue entry for the same user.
    existing = db.execute(select(QueueEntry).where(
        QueueEntry.user_id == body.user_id,
        QueueEntry.status.in_(["WAITING", "ADMITTED"])
    ).order_by(QueueEntry.id.desc())).scalars().first()
    if existing:
        return {"queue_number": existing.queue_number, "status": existing.status,
                "message": "Existing queue entry returned"}
    next_number = db.execute(select(func.coalesce(func.max(QueueEntry.queue_number), 0) + 1)).scalar_one()
    entry = QueueEntry(user_id=body.user_id, queue_number=next_number, status="WAITING")
    db.add(entry)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Queue number collision; please retry")
    db.refresh(entry)
    record_event(db, body.user_id, "-", "QUEUE_JOINED", f"Queue number {entry.queue_number}")
    db.commit()
    return {"queue_number": entry.queue_number, "status": entry.status}

@app.get("/queue/{user_id}")
def queue_status(user_id: str, db: Session = Depends(get_db)):
    entry = db.execute(select(QueueEntry).where(
        QueueEntry.user_id == user_id
    ).order_by(QueueEntry.id.desc())).scalars().first()
    if not entry:
        raise HTTPException(404, "User has not joined the queue")
    ahead = db.execute(select(func.count()).select_from(QueueEntry).where(
        QueueEntry.status == "WAITING",
        QueueEntry.queue_number < entry.queue_number
    )).scalar_one()
    return {"user_id": user_id, "queue_number": entry.queue_number,
            "status": entry.status, "waiting_ahead": ahead}

@app.post("/queue/admit-next")
def admit_next(db: Session = Depends(get_db)):
    # One queue entry is admitted per call; call repeatedly to admit a batch.
    available = db.execute(select(Seat.id).where(Seat.status == "AVAILABLE").limit(1)).first()
    if not available:
        raise HTTPException(409, "No seats currently available")
    entry = db.execute(select(QueueEntry).where(
        QueueEntry.status == "WAITING"
    ).order_by(QueueEntry.queue_number).with_for_update(skip_locked=True).limit(1)).scalars().first()
    if not entry:
        raise HTTPException(404, "No students are waiting")
    entry.status = "ADMITTED"
    entry.admitted_at = utcnow()
    db.commit()
    return {"user_id": entry.user_id, "queue_number": entry.queue_number,
            "status": "ADMITTED", "message": "Student may now reserve a seat"}

@app.post("/reservations", status_code=201)
def reserve_seat(body: ReserveRequest, db: Session = Depends(get_db)):
    existing = db.execute(select(Reservation).where(
        Reservation.idempotency_key == body.idempotency_key
    )).scalars().first()
    if existing:
        seat = db.get(Seat, existing.seat_id)
        return {"reservation_id": existing.id, "seat_label": seat.label,
                "status": existing.status, "expires_at": existing.expires_at,
                "message": "Existing reservation returned for idempotent retry"}

    queue_entry = db.execute(select(QueueEntry).where(
        QueueEntry.user_id == body.user_id,
        QueueEntry.status == "ADMITTED"
    ).order_by(QueueEntry.id.desc())).scalars().first()
    if not queue_entry:
        raise HTTPException(403, "Join the queue and wait to be admitted before reserving")

    seat = db.execute(select(Seat).where(
        Seat.label == body.seat_label
    ).with_for_update()).scalars().first()
    if not seat:
        raise HTTPException(404, "Seat not found")
    if seat.status != "AVAILABLE":
        record_event(db, body.user_id, seat.label, "RESERVATION_REJECTED", "Seat not available")
        db.commit()
        raise HTTPException(409, "Seat is not available")

    seat.status = "HELD"
    reservation = Reservation(
        user_id=body.user_id, seat_id=seat.id, status="HELD",
        created_at=utcnow(),
        expires_at=utcnow() + timedelta(minutes=HOLD_MINUTES),
        idempotency_key=body.idempotency_key
    )
    db.add(reservation)
    record_event(db, body.user_id, seat.label, "SEAT_HELD",
                 f"Temporary hold for {HOLD_MINUTES} minutes")
    db.commit()
    db.refresh(reservation)
    return {"reservation_id": reservation.id, "seat_label": seat.label,
            "status": reservation.status, "expires_at": reservation.expires_at,
            "hold_minutes": HOLD_MINUTES}

@app.post("/reservations/{reservation_id}/cancel")
def cancel_reservation(reservation_id: int, body: CancelRequest, db: Session = Depends(get_db)):
    reservation = db.execute(select(Reservation).where(
        Reservation.id == reservation_id
    ).with_for_update()).scalars().first()
    if not reservation:
        raise HTTPException(404, "Reservation not found")
    if reservation.user_id != body.user_id:
        raise HTTPException(403, "Reservation belongs to another user")
    if reservation.status not in {"HELD", "CONFIRMED"}:
        raise HTTPException(409, f"Cannot cancel reservation in {reservation.status} state")
    seat = db.execute(select(Seat).where(Seat.id == reservation.seat_id).with_for_update()).scalar_one()
    reservation.status = "CANCELLED"
    seat.status = "AVAILABLE"
    record_event(db, body.user_id, seat.label, "RESERVATION_CANCELLED", f"Reservation {reservation.id}")
    db.commit()
    return {"reservation_id": reservation.id, "status": reservation.status,
            "seat_label": seat.label, "seat_status": seat.status}

@app.post("/reservations/{reservation_id}/payment")
def simulate_payment(reservation_id: int, body: PaymentRequest, db: Session = Depends(get_db)):
    old_payment = db.execute(select(Payment).where(
        Payment.idempotency_key == body.idempotency_key
    )).scalars().first()
    if old_payment:
        return {"payment_id": old_payment.id, "status": old_payment.status,
                "message": "Existing payment returned for idempotent retry"}
    reservation = db.execute(select(Reservation).where(
        Reservation.id == reservation_id
    ).with_for_update()).scalars().first()
    if not reservation:
        raise HTTPException(404, "Reservation not found")
    if reservation.status != "HELD":
        raise HTTPException(409, f"Reservation is {reservation.status}, not HELD")
    if reservation.expires_at <= utcnow():
        seat = db.execute(select(Seat).where(Seat.id == reservation.seat_id).with_for_update()).scalar_one()
        reservation.status = "EXPIRED"
        seat.status = "AVAILABLE"
        db.commit()
        raise HTTPException(409, "Reservation expired")
    if body.outcome == "delayed":
        payment_status = "DELAYED"
        # Delayed is simulated as pending; reservation remains HELD until expiry.
    elif body.outcome == "failure":
        payment_status = "FAILED"
        reservation.status = "PAYMENT_FAILED"
        seat = db.execute(select(Seat).where(Seat.id == reservation.seat_id).with_for_update()).scalar_one()
        seat.status = "AVAILABLE"
    else:
        payment_status = "SUCCESS"
        reservation.status = "CONFIRMED"
        seat = db.execute(select(Seat).where(Seat.id == reservation.seat_id).with_for_update()).scalar_one()
        seat.status = "BOOKED"
    payment = Payment(reservation_id=reservation.id, idempotency_key=body.idempotency_key,
                      status=payment_status)
    db.add(payment)
    seat_label = db.get(Seat, reservation.seat_id).label
    record_event(db, reservation.user_id, seat_label, "PAYMENT_" + payment_status,
                 f"Reservation {reservation.id}")
    db.commit()
    db.refresh(payment)
    return {"payment_id": payment.id, "reservation_id": reservation.id,
            "payment_status": payment.status, "reservation_status": reservation.status}

@app.get("/reservations/{reservation_id}")
def reservation_status(reservation_id: int, db: Session = Depends(get_db)):
    reservation = db.get(Reservation, reservation_id)
    if not reservation:
        raise HTTPException(404, "Reservation not found")
    seat = db.get(Seat, reservation.seat_id)
    return {"reservation_id": reservation.id, "user_id": reservation.user_id,
            "seat_label": seat.label, "status": reservation.status,
            "created_at": reservation.created_at, "expires_at": reservation.expires_at}

@app.get("/bookings/history/{user_id}")
def booking_history(user_id: str, db: Session = Depends(get_db)):
    rows = db.execute(select(Reservation, Seat).join(Seat, Reservation.seat_id == Seat.id)
                      .where(Reservation.user_id == user_id)
                      .order_by(Reservation.id.desc())).all()
    return [{"reservation_id": r.id, "seat_label": s.label, "status": r.status,
             "created_at": r.created_at, "expires_at": r.expires_at} for r, s in rows]

@app.get("/metrics/contention")
def contention_metrics(db: Session = Depends(get_db)):
    total = db.query(BookingEvent).count()
    rejected = db.query(BookingEvent).filter(BookingEvent.event_type == "RESERVATION_REJECTED").count()
    held = db.query(BookingEvent).filter(BookingEvent.event_type == "SEAT_HELD").count()
    expired = db.query(BookingEvent).filter(BookingEvent.event_type == "RESERVATION_EXPIRED").count()
    cancelled = db.query(BookingEvent).filter(BookingEvent.event_type == "RESERVATION_CANCELLED").count()
    return {"events_recorded": total, "successful_holds": held,
            "rejected_attempts": rejected, "expired_reservations": expired,
            "cancelled_reservations": cancelled}

@app.post("/admin/cleanup-expired")
def cleanup_expired(db: Session = Depends(get_db)):
    count = cleanup_expired_once(db)
    return {"expired_reservations_released": count}
