# Read the Room

A short dance piece in dim light with a live percussionist, a free-jazz duo. The audience is the subject. The show profiles the people watching it, the way Cambridge Analytica profiled voters, and does it in plain sight. It plays to them until they love it, then it tells them too much about themselves.

Status: concept.

## The idea

Political targeting worked because people did not know it was happening. This piece flips that. Everyone in the room is told, before they enter, that the show will read them. They say yes. And it still goes too far.

The performance runs in three movements:

1. **Listening.** Dance and drums in near darkness. The projection shows the profiling machinery warming up: the questionnaire answers arriving, the five personality scores (the OCEAN or Big Five model) being computed, the audience sorted into clusters.
2. **Pleasing.** The duo steers the piece toward what the profiles say this room wants: tempo, density, color, imagery. The projection follows the opted-in preferences. The aim is to be liked, extremely.
3. **Overreach.** The machine starts to share. Cluster labels, predictions, the kind of ad each group "would respond to", all aimed at the room as a whole. It says more than anyone is comfortable with. The method is on the wall, and so is its creepiness. It also shows how the room said yes, for example "most of you ticked the box in under 4 seconds". Then the lights find the microphones: the projection shows where each one sits and what it "heard" all night, as room-level sound (when the room went quiet, when it laughed, when it clapped). Everyone was told about them, and it still feels like too much.

## Consent model

This is a hard rule of the piece, not a detail.

- **A checkbox in the RSVP.** Like terms and conditions, but short and plain: two or three sentences right next to the box, saying the show will profile the people who tick it and that microphones in the room listen to the audience as a whole. The box starts unticked. Ticking it is the opt-in.
- **Reminder at the door.** A sign at the entrance repeats the same sentences.
- **Declining is easy.** Anyone can leave the box unticked or skip the questionnaire and still watch. They are simply not in the data.
- **Only volunteered data.** Nothing is taken from phones, Wi-Fi, Bluetooth or other signals. No one is looked up online. The inputs are what each person types into the questionnaire and the announced room mics.
- **Room mics, announced.** A few small microphones around the room feed a Raspberry Pi. The RSVP and the door sign say so. The Pi only measures room-level sound: loudness, laughter, applause, silence. It never records, stores or transcribes speech, and it cannot tell one person from another.
- **No names on the wall.** Results are shown as clusters and room-level numbers, never as a named or recognisable person.
- **Deleted after the show.** Answers and sound levels are kept only for the night and wiped at the end. The audience is told this too.

The provocation lands harder this way: they agreed, and it still felt like too much.

## Staging

- Dancer (Baby) and a live percussionist, improvising as a free-jazz duo.
- Dim light, one projection surface behind or around the dancer.
- A small screen or printed cue sheet for the duo showing the current room profile, so they can play toward it.
- The profiling dashboard is part of the projection, not hidden backstage.
- Small microphones placed around the room, out of the way but not hidden, revealed in the overreach movement.

## Technical sketch

```
RSVP with an unticked consent checkbox (plain text next to it)
        |
        v
Short questionnaire on the guest's own phone (opt-in, about 10 questions)
        |
        v
Local laptop: score Big Five traits per answer set, no names stored
        |
        v
Room mics -> Raspberry Pi: room-level sound only (loudness, laughter, applause, silence), no speech kept
        |
        v
Room profile: cluster counts, averages and room sound
     |                     |
     v                     v
Projection (Isadora)   Cue sheet for dancer and drummer
        |
        v
"Overreach" scene: room-level predictions shown on the wall
        |
        v
Wipe all answers and sound levels after the show
```

- **Questionnaire:** a simple web form on a local network or a short link, using a public short Big Five inventory (for example the 10-item TIPI). Each submission gets a random id, no name. The RSVP also logs how long each person took to tick the box, with no name attached, only for the room-level number in the overreach scene. It is deleted with everything else.
- **Room mics:** a few USB or wireless microphones into the Raspberry Pi. A short script turns the audio into a handful of numbers several times a second (level, laughter, applause, silence) and throws the audio away straight after. Only the numbers are sent on, for example over OSC.
- **Scoring and clustering:** a small script on the laptop turns answers into five scores and groups the room into a few clusters.
- **Language model (optional):** writes the dashboard text and the "overreach" lines from the room-level numbers only.
- **Projection:** Isadora reads the room profile (for example over OSC) and shifts color, tempo of the imagery and footage choice.

## What this piece does not do

It does not collect data from devices, intercept signals, record or transcribe what anyone says, hide its microphones, research guests online, or profile anyone who has not opted in. The Cambridge Analytica method is the subject, shown and critiqued openly, not a tool used on unknowing people.
