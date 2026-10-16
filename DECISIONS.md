HoldMySeat — Design Decisions

1. Most Technically Challenging Part

One of the most challenging parts of this project was understanding how to manage seat availability and prevent the same seat from being booked by multiple users. I tested this by booking seat S001 for one user and then trying to reserve the same seat for another user. The second request was rejected with a 409 Conflict response, which helped me understand how the backend handles unavailable seats. This helped me see why checking seat availability is an important part of a ticket booking system.

2. Important Design Decision and Trade-off

One important design decision was to use a queue-based approach for managing users who want to book concert tickets. This helps organise booking requests instead of allowing everyone to proceed directly to seat reservation. I also used a temporary seat hold of five minutes before payment confirmation. This gives users time to complete payment, but it also means that expired holds need to be handled properly so that seats can become available again.

3. Limitation or Failure Case

One limitation is that I have tested the basic booking flow and duplicate-seat rejection, but I have not yet tested the system with many users making booking requests simultaneously. Although the backend rejected a second reservation for an already booked seat, more testing is needed to understand how the system behaves under heavy traffic. Testing concurrent requests would help identify possible issues and improve confidence in the booking process.

4. What I Would Improve With Another Week

If I had another week, I would focus on improving the testing of the system. I would test multiple users trying to reserve seats at the same time and verify that expired reservations release seats correctly. I would also add more automated tests for payment failures, repeated requests, and reservation expiry. These improvements would help make the system more reliable and prepare it to handle more realistic booking situations.
