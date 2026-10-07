# Read the Room

A short dance piece in dim light with a live percussionist, a free-jazz duo. The audience is the subject. The show profiles the people watching it, the way Cambridge Analytica profiled voters, and does it in plain sight. It plays to them until they love it, then it tells them too much about themselves.

Status: concept.

## The idea

Political targeting worked because people did not know it was happening. This piece flips that. Everyone in the room is told, before they enter, that the show will read them. They say yes. And it still goes too far.

The performance runs in three movements:

1. **Listening.** Dance and drums in near darkness. The projection shows the profiling machinery warming up: the questionnaire answers arriving, the five personality scores (the OCEAN or Big Five model) being computed, the audience sorted into clusters.
2. **Pleasing.** The duo steers the piece toward what the profiles say this room wants: tempo, density, color, imagery. The projection follows the opted-in preferences. The aim is to be liked, extremely.
3. **Overreach.** The machine starts to share. Cluster labels, predictions, the kind of ad each group "would respond to", all aimed at the room as a whole. It says more than anyone is comfortable with. The method is on the wall, and so is its creepiness.

## Consent model

This is a hard rule of the piece, not a detail.

- **Consent at the threshold.** The RSVP and a sign-in at the door say plainly: this show reads and profiles its audience. Attending with a profile is the opt-in.
- **Declining is easy.** Anyone can skip the questionnaire and still watch. They are simply not in the data.
- **Only volunteered data.** Nothing is taken from phones, Wi-Fi, Bluetooth or the room's signals. No one is looked up online. The only input is what each person types into the questionnaire themselves.
- **No names on the wall.** Results are shown as clusters and room-level numbers, never as a named or recognisable person.
- **Deleted after the show.** Answers are kept only for the night and wiped at the end. The audience is told this too.

The provocation lands harder this way: they agreed, and it still felt like too much.

## Staging

- Dancer (Baby) and a live percussionist, improvising as a free-jazz duo.
- Dim light, one projection surface behind or around the dancer.
- A small screen or printed cue sheet for the duo showing the current room profile, so they can play toward it.
- The profiling dashboard is part of the projection, not hidden backstage.

## Technical sketch

```
RSVP / door sign-in (consent text)
        |
        v
Short questionnaire on the guest's own phone (opt-in, about 10 questions)
        |
        v
Local laptop: score Big Five traits per answer set, no names stored
        |
        v
Room profile: cluster counts and averages
     |                     |
     v                     v
Projection (Isadora)   Cue sheet for dancer and drummer
        |
        v
"Overreach" scene: room-level predictions shown on the wall
        |
        v
Wipe all answers after the show
```

- **Questionnaire:** a simple web form on a local network or a short link, using a public short Big Five inventory (for example the 10-item TIPI). Each submission gets a random id, no name.
- **Scoring and clustering:** a small script on the laptop turns answers into five scores and groups the room into a few clusters.
- **Language model (optional):** writes the dashboard text and the "overreach" lines from the room-level numbers only.
- **Projection:** Isadora reads the room profile (for example over OSC) and shifts color, tempo of the imagery and footage choice.

## What this piece does not do

It does not collect data from devices, intercept signals, research guests online, or profile anyone who has not opted in. The Cambridge Analytica method is the subject, shown and critiqued openly, not a tool used on unknowing people.
