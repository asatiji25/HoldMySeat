# HoldMySeat booking workflow

```mermaid
flowchart TD
    A[Student joins queue] --> B[Assign server queue number]
    B --> C[Wait for admission]
    C --> D[Admit next student in order]
    D --> E{Seat available?}
    E -- No --> F[Return conflict response]
    E -- Yes --> G[Lock seat row in transaction]
    G --> H[Create temporary hold]
    H --> I{Payment outcome}
    I -- Success --> J[Confirm reservation and mark seat booked]
    I -- Failure --> K[Mark payment failed and release seat]
    I -- Delayed --> L[Keep hold pending]
    L --> M{Hold expired?}
    M -- Yes --> N[Release seat and record expiry]
    M -- No --> L
    J --> O[Return status and booking history]
    K --> P[Seat available for next student]
    N --> P
```

The database transaction is the final guard against two requests claiming the same seat. The queue controls admission order; it does not replace database concurrency control.
