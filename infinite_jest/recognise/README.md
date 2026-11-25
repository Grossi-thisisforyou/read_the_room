# Recognise: opt-in face recognition, prepared and switched off

Lets the room recognise a booked guest who asked for that, so nobody has to pick them on the
control page. Anyone else is a stranger and gets the getting-to-know-you path.

**Status: prepared, not connected to the show, not tested on a camera.** The matching logic is
tested with stand-in numbers. The camera models are not in the repo.

It only works for a guest when all of this is true:

1. Their guest file says `"consent": {"face": true}`. Nothing sets that today.
2. They gave their own photos for it (two or three, face forward). No photo is taken from the web.
3. The two model files are in `~/models/face/` and `python3-opencv` 4.8+ is installed.

What is stored: a list of numbers per enrolled guest in their own folder (`face.json`, private,
deleted with the file). Not stored: enrolment photos, camera frames, anything about a stranger.

```python
from infinite_jest.recognise import core
emb = core.SFace()                                   # needs cv2 and the models
core.enrol(guest_folder, ["a.jpg", "b.jpg"], emb)    # refuses without consent.face
r = core.Recogniser(emb)
name = r.see(frame)      # folder name once two frames agree, else None
r.reset()                # when the room empties
```

## Before this may be switched on for guests

- The terms say "The Work does not use facial recognition or any other biometric
  identification" (Section 9). That sentence has to change first, and the entrance sign with it.
- The booking page needs its own unticked box for it and a way to hand over photos.
- A face template is biometric data. It is a special category under the GDPR, and US states
  and New York City have their own biometric rules. The school should see this before a guest
  is enrolled.
- First test: the artist's own face only.
