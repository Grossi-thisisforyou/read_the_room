# OCEAN and the Cambridge Analytica research

The piece borrows its method from psychographic targeting: predict a person's
personality from their digital footprint, then shape what they see to fit it. This page
says how that method worked, how the room uses it, and what happened when we tested it.

## What Cambridge Analytica did

The full sourced brief is in
[research/cambridge-analytica-ocean-method.md](research/cambridge-analytica-ocean-method.md).
In short:

1. **The science.** Researchers at Cambridge (Kosinski, Stillwell and Graepel, 2013)
   showed that Facebook Likes predict the Big Five personality traits, known as OCEAN:
   Openness, Conscientiousness, Extraversion, Agreeableness, Neuroticism. With 58,000
   volunteers they reached r = .43 for Openness and .40 for Extraversion. A later study
   found that a model using about 300 Likes judged a person as well as their spouse did.
2. **The harvest.** In 2014 a personality-quiz app paid a few hundred thousand people to
   take a test and, through Facebook's friends permissions, reached up to 87 million
   profiles. Those records were modelled into OCEAN scores for voters.
3. **The targeting.** Messages were written to match a personality: an anxious, open
   person gets a different ad from a calm, conventional one. Field studies (Matz et al.,
   2017) found trait-matched ads got noticeably more clicks than mismatched ones.
4. **The limits.** Meta-analyses put footprint-based prediction at about r = .34: useful
   for groups, unreliable for any single person. The UK Information Commissioner's 2020
   review found the methods were neither new nor as powerful as claimed.

That gap between the claim and the evidence is part of the piece.

## How the room profiles a visitor

Two layers, both disclosed at booking.

**Before the visit: research.** Booking requires agreeing to the Terms, which say the
visit is "personalised just for me, woven from my digital footprint". The limits, from
Section 11 of the [terms](https://jasperengelhardt.com/terms.html):

- only people who actually booked, only public material, matched to them with certainty;
- no logins, private accounts, data brokers, or family and other private people;
- no sensitive categories (health, sexuality, religion, politics, immigration, money);
- kept offline and deleted on Dec 23, 2026.

Research supplies the *personal material* the room addresses the visitor with: facts,
quotes, public pictures. None of it is in this repository.

**During the visit: live reading.** The room reads behaviour, not identity:

1. **Features.** How long the visitor stays, how still they are, when they speak and for
   how long, how they react when the sound drops or the picture changes.
2. **OCEAN estimate.** The features update five trait scores, each with a cap on how
   confident the room may become (Extraversion is the easiest to read from behaviour;
   Agreeableness and Neuroticism the hardest).
3. **Choosing the scene.** A bandit (Thompson sampling) tries the five scenes and keeps
   what holds this visitor longest, measured against their own baseline.
4. **The reveal.** The room shows its profile, says honestly how weak such predictions
   are ("studies find about r = .2; this room was never tested"), and deletes everything.

No face recognition, no demographics, no emotion detection, and the microphone never
records or transcribes.

## What we tested

The artist ran the full method on themself first, with their own consent.

- **Ground truth:** the public-domain IPIP-50 personality questionnaire, scored with its
  published key and sealed away from the predictions.
- **Prediction:** a reader built a file from public sources only (47 data points) and
  predicted the five traits, 14 yes/no habits, which of three invitations would appeal,
  and which room the subject would stay in.

**Method v1** (read the public footprint the way Cambridge Analytica read Likes) got 2 of
5 traits within 15 points and 9 of 14 habits, close to chance. Every miss went the same
way: press stories, acting roles and a formal website read as a guarded, reactive
person; the questionnaire said very outgoing, warm and calm.

**Method v2** fixed that with a few rules: start from the person's reference group
(published findings on performers), give media narrative and roles played zero weight,
discount anything older than five years, count behaviours over tone, read hardship by
its outcome, and move a trait only when three independent cues agree. A reader who had
not seen the answers got **4 of 5 traits within 15 points**, and the average error fell
from 24.8 to 9.8 points. The room the subject stayed in longest was predicted correctly.

Honest caveats: the v2 rules were written after seeing one person's answers, so this is
a fit, not a proof; the next guest is the real test. Single yes/no habits stayed at
chance either way, so the room now asks those questions in the conversation instead of
predicting them. No individual scores are published here.

## What the research changed in the piece

- Research supplies **content**; the live loop in the room decides **the scene**.
- The conversation asks short questions that a footprint can't answer.
- The reveal says how unreliable the reading is, because that is what the evidence says.
