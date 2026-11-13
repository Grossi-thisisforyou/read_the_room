# INFINITE JEST: how visitor data is handled

*A one-page note for The New School (Mannes, 3rd floor), December 2026. These
are the artist's default choices and can be changed. This is not legal advice;
the school's counsel or risk office should confirm it.*

## What the piece does

INFINITE JEST is a room that watches each visitor for about a minute and guesses
their personality on the Big Five (OCEAN) model. It then shows them the images
and sound it predicts will hold them, measures whether they do, and finally
shows the visitor everything it inferred and how weak the inference is. It
openly restages the psychographic targeting used by Cambridge Analytica, as a
critique.

## What is sensed

- **One phone (Nokia N900):** a low-resolution grayscale camera (160x120 pixels,
  4 frames a second), a microphone level, the touchscreen, the keyboard, the
  motion sensor and the proximity sensor.
- **Derived only:** position, size in frame, amount of movement, whether a face
  is turned to the device, how much and how loudly someone speaks, touches,
  answers to on-screen either/or questions, and how many characters they typed.

## What is never done

- No recording. Camera frames and audio are never written to disk.
- No listening to words. The mic gives only a level and a "someone is
  speaking" flag. No transcripts, no speech content. (Recording conversations
  without consent can be eavesdropping under NY Penal Law 250.)
- No identification. No face recognition, face templates or face
  geometry, and no comparison against any outside source. No guesses about age,
  gender, race, health or emotion.
- No internet. Everything runs on a Raspberry Pi and the phone, on a closed
  local network. Nothing leaves the room. Nothing is sold, shared or reused.
- No typed text kept. If a visitor types something, only the character
  count is used.

## Retention

Everything about a visitor is held in memory only and deleted when they leave:
within about 15 seconds of them leaving (end of each visit), when
the connection drops, and on a manual "blackout". The machine's logs keep only
counts and timings, with no ids. Nothing is kept for training, research or
documentation.

## Choice and opt-out

- An entrance notice is posted at every entrance, at eye level, in large type,
  with a camera and microphone icon.
- Anyone can walk past without engaging. Covering the top of the phone for 3
  seconds stops the profiling, deletes what was gathered, and shows "you are not
  being read". A staff member can pause the whole system ("blackout") at any time.
- Under 18s only with an accompanying adult.
- Documentation of the piece uses staged footage with consenting performers, or
  signed releases. Visitor footage is never used, since none is kept.

## Reference points

- **NYC Biometric Identifier law (Admin Code 22-1201):** may apply to exhibitions.
  The piece does not collect identifying biometrics, but the entrance sign is
  posted anyway and nothing is ever sold.
- **NY Civil Rights Law 50/51:** no visitor likeness is used for trade or
  promotion.
- **EU AI Act Art. 5:** not binding here, but it bans emotion recognition in
  education and manipulative techniques. The piece does no emotion recognition,
  uses its technique on no one covertly, and shows every visitor everything it
  inferred.
- **IRB:** no data is kept and no findings are drawn, so this is an artwork, not
  human-subjects research. A short written "not human subjects research" note
  from the IRB office can be requested to be safe.

## Entrance notice (proposed wording)

> **THIS ROOM WATCHES YOU.**
> A camera and microphone in this artwork observe how you move, look and
> sound, and guess your personality. At the end you will see what it guessed.
> It does not identify you, record you, listen to your words, or connect to the
> internet. Everything is deleted when you leave. Nothing is shared or sold.
> Entering means you agree. To not be read, cover the top of the phone for three
> seconds, or ask staff to pause the room. You may leave at any time.
> Under 18 only with an adult.
> *This work stages psychographic profiling in order to question it.*
> INFINITE JEST · Parsons / Mannes, December 2026
