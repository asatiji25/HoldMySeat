from pydantic import BaseModel, Field

class JoinQueueRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=100)

class ReserveRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=100)
    seat_label: str = Field(min_length=1, max_length=10)
    idempotency_key: str = Field(min_length=1, max_length=150)

class PaymentRequest(BaseModel):
    outcome: str = Field(pattern="^(success|failure|delayed)$")
    idempotency_key: str = Field(min_length=1, max_length=150)

class CancelRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=100)
