# The booking tool

Guests sign up at **[jasperengelhardt.com/visit.html](https://jasperengelhardt.com/visit.html)**.
The page is part of the artist's website (source:
[Grossi-thisisforyou/jasperengelhardt](https://github.com/Grossi-thisisforyou/jasperengelhardt),
files `visit.html`, `terms.html` and `booking/`).

![The booking page](media/booking/visit.jpg)

## How it works

- **Pick a time.** Dec 9 to Dec 22, 12:00 to 22:00, closed Saturdays. Arrival windows of
  5 minutes, up to 6 people each. Guests stay as long as they like.
- **Armory dates.** During the artist's performances at the Armory, slots stay open and
  are marked "artist not present, performing".
- **One box.** "Yes, I agree to the Terms and Conditions. (18+)", with a small line
  beside it: *"By booking, I agree to a performance personalised just for me, woven from
  my digital footprint."* Being researched is a condition of attending, stated at the
  point of booking. Anyone who does not want that is asked not to book.
- **Terms.** [terms.html](https://jasperengelhardt.com/terms.html) is a long terms
  document written as part of the work. Section 11 sets the limits of the research
  (see [research](research.md)).
- **Storage.** The site is static. Bookings go to a private Google Sheet in the artist's
  own Google Drive through a small Google Apps Script web app (`booking/Code.gs`).
  The page itself only ever reads how many places are left in each window, never names.
- **Emails.** The script sends each guest a confirmation (with a cancel link) and a
  reminder the morning before, and sends the artist the day's list.
- **Deletion.** The script deletes every booking on Dec 23, 2026, as the terms promise.
- **On the day.** Check in at the front desk of 72 Fifth Avenue; the artist meets guests
  in the lobby and walks them up to room 401.

No booking data is stored in either repository.
