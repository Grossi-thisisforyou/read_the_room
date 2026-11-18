# The arc of one visit

A score for one visitor, from the dark room to the deleted file. Timings
assume handheld mode (the visitor picks up the N900). Line ids in brackets
point into `corpus/`; every line can be cut from the score page.

The engine's phases are `idle → approach → profiling → hook → release → wipe`.
The dramaturgy below adds **beats** inside those phases. A beat is a text
cue, not a new phase: the engine can derive each one from `phase`, `phase_t`
and the profile, so no contract change is needed.

## Timing changes this needs

The current defaults give the confession 6 s and the wipe 4 s. Nobody can read
a dossier in 6 s, and the confession is the point of the piece.

| `[visit]` key | now | proposed | why |
|---|---|---|---|
| `release_time` | 6 | **50** | ~13 data lines at 2 s, then ~6 confession lines at 3.5 s |
| `wipe_time` | 4 | **12** | the deletion has to be watched, line by line |
| `max_visit` | 180 | 180 | keep: the hook should end before boredom does |
| `profiling_timeout` | 20 | 24 | room for 3 prompts at 7 s each |

During `release` the engine should type the reveal line by line (2 s for the
evidence, numbers and segment; 3.5 s for each confession line) and not cut it
short if the visitor walks off: the confession plays to the room.

## Overview

| t (s) | phase | beat | wall | phone | sound (suggestion) |
|---|---|---|---|---|---|
| — | idle | **attract** | one line every 25–40 s, then black | `pick me up` loop | sub-bass, one pulse |
| 0 | approach | **lift** | log: `DEVICE LIFTED` | `there you are.` | first kick |
| 0–3 | approach | **consent** | log: subject acquired | consent screen | kick, filter closed |
| 3–24 | profiling | **calibration** | dossier fills with live numbers | 3 either/or prompts | filter opens |
| 24–60 | hook | **testing** | scene changes every 8–12 s, hook-flavoured log | tailored whispers | the scene's sound |
| 60–110 | hook | **lock** | one scene wins; log turns to the visitor | whispers get closer | full drive |
| ~110 | hook | **the hinge** | one exact behaviour named, then silence | one line | drop to sub-bass for 4 s |
| 110–150 | hook | **deepening** | the scene at full intensity, sparse words | `nobody else gets this one.` | peak |
| any | hook | **stillness** | after 5 s still: one whisper on the wall | — | strip to sub-bass |
| put down | release | **confession** | the dossier, line by line | `put me down. it's over.` | 112 bpm, decaying |
| +50 | wipe | **deletion** | each line struck out, then gone | `gelöscht.` / `deleted.` | noise burst, then nothing |
| +62 | idle | **afterimage** | `nothing about you was kept.` for 8 s, then attract | `pick me up` | silence, then the pulse |

## Beat by beat

### Attract (idle)

The room is nearly black. The phone lies on its plinth, screen faintly lit.
Every 25 to 40 s one line surfaces on the wall in the log or the whisper, holds
for 6 s and sinks back. Never two in a row of the same register. Lines may use
the day's counters (visits today, average stay), which the logs are allowed to
keep because they are counts with no ids. If the room has been empty more than
10 minutes, the lines get lonelier and further apart (`attract.long`).

The phone: `pick me up`, then other `phone.attract` lines, one per minute.

The point: the room is already watching before anyone arrives. It is a feed
that never closes.

### Lift (approach, 0 s)

The instant the phone is lifted, the wall cuts from black to the surveil scene
and stamps one log line (`approach.lift`). The phone says one whisper of
arrival (`phone.lift`). The tone is not welcome. It is recognition, as if it
had been waiting for this particular person.

### Consent (approach, 0–3 s)

The phone shows the consent screen (`phone.consent`): it watches, it listens
to level only, it keeps nothing, cover the top edge to stop. Touch to enter.
This is non-negotiable for a school building, and it is also dramaturgy:
the visitor signs the terms and conditions, like everyone always does.

### Calibration (profiling, 3–24 s)

The dossier scene. The wall fills with log lines that carry live numbers
(`profiling.log`): grip, tilt range, distance, time to first touch. The phone
asks three either/or prompts (`prompts`), roughly one every 7 s, drawn from
the bank without repeats. The whisper is polite and curious here, like a
quiz on a social app. The visitor should feel it is a game. It is a
measurement.

If the visitor ignores a prompt for 8 s, the phone moves on and the wall logs
the silence (`profiling.no_answer`). Not answering is still an answer.

### Testing (hook, 24–60 s)

Scenes change every 8 to 12 s as the bandit tests them. Each scene has its own
log lines and whispers (`hook.<scene>`), plus whispers tailored to the
visitor's strongest trait (`whisper.<trait><pole>`). The wall speaks less
than in calibration: one log line per scene change, one whisper every 10 s.
The remaining two prompts are asked here, one each 15 s or so.

### Lock (hook, ~60–110 s)

When the same scene wins twice in a row, the room locks. The log turns from
the scene to the visitor (`hook.lock`): `RETENTION 0.81` `THIS ONE HOLDS YOU`.
The whispers get closer and more singular: `this was made from you.`

### The hinge (hook, once, ~100–120 s)

The moment the piece turns from seductive to uncanny. The wall names one exact
behaviour taken from the strongest evidence, in the whisper register
(`hinge`): `you turn me faster when it gets loud.` `you answered before i
finished asking.` Then 4 s of silence and near black. Then the scene returns
at full strength, as if nothing happened.

Only once per visit. Only if the profile has at least one evidence line with
confidence above 0.4; otherwise skip it. A wrong hinge is worse than none.

### Deepening (hook, 110–150 s)

Full intensity, few words. This is the custom-made intimacy at its height:
`nobody else gets this one.` `i kept this one for you.` The room is
saying what every feed says, and for a moment it is true.

### Stillness (hook, any time)

When the phone has been held still for 5 s (`steer.still_s >= 5`), the image
settles and one whisper appears large on the wall (`stillness`). The visitor
learns that stillness is rewarded with words, and starts to perform stillness.
That is the loop.

### Confession (release, 50 s)

Triggered by putting the phone down (8 s) or by the 180 s limit. The wall
drops the scene to the afterimage and the dossier is typed line by line,
headed `AKTE / FILE` (German layer) or `FILE`. Order:

1. 3 to 4 evidence lines: what it saw, and which trait that is said to predict
   (`dossier.observe` + `dossier.infer`).
2. The five traits as numbers with confidence.
3. The segment label, as an ad platform would show it (`labels`).
4. Which scene held them, and why it was chosen (it worked, not because it
   was true).
5. The confession proper (`confession.*`): one version is picked per visit.
   It admits the confidence is not accuracy, that one minute of behaviour
   predicts personality at about r = .2, and ends on the line the piece
   lives for: *it still felt like it knew you.*

The phone, meanwhile: `put me down. it's over.` or a calm `phone.release`.

### Deletion (wipe, 12 s)

One version of `wipe.*` per visit. The wall strikes through the dossier line
by line, bottom to top, then erases it to black. The last line stays alone
for 2 s: `nothing about you was kept.` The phone shows the German stamp
`gelöscht.` (or `deleted.`) and then returns to `pick me up`.

## How the arc changes per trait mix

The bandit chooses the scene; the text adapts to the strongest trait. These
are the defaults the corpus is written for.

| Segment | Pacing | Wall density | Whisper stance | Likely scenes | Hinge style |
|---|---|---|---|---|---|
| **E+ The Performer** | fast, prompts at 5 s | high | flattering attention: `they can see you from the door.` | mirror, writing | speed: `you answered before i finished.` |
| **E− The Observer** | slow, prompts at 10 s | very low, long black gaps | permission: `you don't have to say anything.` | dark, fall | distance: `you held me at arm's length the whole time.` |
| **O+ The Seeker** | normal | medium, stranger lines | novelty: `it changed while you looked.` | writing, fall | exploration: `you turned me upside down before i asked.` |
| **O− The Literalist** | normal | low, plain lines | plainness: `this is exactly what it looks like.` | dark, wound | literal: `you held me the right way up.` |
| **C+ The Auditor** | steady | numbers, timestamps | precision: `00:47. on schedule.` | dark | timing: `you waited exactly as long each time.` |
| **C− The Drifter** | loose | fragments | looseness: `lose the thread.` | writing, fall | wandering: `you never held one angle for long.` |
| **A+ The Opt-In** | gentle | medium | gratitude: `thank you for staying.` | mirror | compliance: `you answered every question.` |
| **A− The Contrarian** | sharp | medium | dare: `you don't have to like this.` | wound, fall | resistance: `you chose the other one every time.` |
| **N+ The Live Wire** | slower, softer | low | calculated comfort: `it's okay. stay a little.` | wound, mirror | time: `you have been here 01:40. you haven't checked the time.` |
| **N− The Cold Surface** | fast | medium | cold: `colder. you can take it.` | wound, dark | steadiness: `your hands did not move for 40 seconds.` |

Rule for the Live Wire in particular: comfort, never alarm. Shaky hands are never named on the wall (a visitor may have a tremor), and shake is not used as dossier evidence. The menace is
that the comfort was calculated, which the confession admits.

## When someone refuses to play

| Situation | Detected by | What the room does |
|---|---|---|
| **Opts out** (covers the top edge 3 s) | profiler `opted_out` | Phone: `you are not being read.` Wall: one log line (`refusal.optout`), then the dark scene with no words until they leave. No reveal, no wipe theatre: just `nothing was taken.` The refusal is honoured completely and quietly. |
| **Ignores the prompts** | 3 prompts with no answer | Wall logs it once (`refusal.silent`): `NO ANSWERS. NOTED.` The phone stops asking. The silence goes into the dossier as one line. |
| **Picks up and puts down within 15 s** | release before 15 s | Short confession (`confession.short`): `that was 11 seconds. it was enough to start a file.` then the wipe. |
| **Shakes it hard, bangs it** | `shake > 0.8` repeatedly | Glitch, then one calm whisper (`refusal.shake`): `i'm still here.` Never scold. |
| **Turns it upside down and leaves it** | flip held > 20 s | The wall stays inverted, the log notes it (`refusal.flip`). |
| **Talks over it, a group arrives** | voiced high, presence wide | `refusal.group`: `you came as a crowd. we read you as one.` |
| **Puts it down mid-prompt** | phone down | Normal release. The unanswered prompt is not mentioned. |
| **Comes back again** | cannot be detected, by design | Never claim recognition. One attract line says it: `have we met. we would not know.` |
