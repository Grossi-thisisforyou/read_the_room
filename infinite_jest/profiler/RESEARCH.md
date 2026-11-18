# Research notes behind the profiler

Gathered 2026-11-13 from web research. Figures marked *(unverified)* came from
memory or secondary sources and should be checked before they are quoted in
public text.

## What Cambridge Analytica actually did

**The model.** The myPersonality project (Stillwell, Kosinski) had Facebook users
take a personality quiz and share their Likes. Kosinski, Stillwell & Graepel,
PNAS 2013, used about 58,000 of them. They reduced the user × Like matrix with SVD
to about 100 components and regressed OCEAN scores on those components. Openness
was predicted about as well as the test agrees with itself when retaken
(r ≈ .43); the other traits came in around .29 to .40 *(unverified per-trait
values)*. https://pubmed.ncbi.nlm.nih.gov/23479631/

Youyou et al., PNAS 2015: with 10 Likes the model matched a colleague's
judgement of someone's personality, with 70 a friend's, with 150 a family
member's and with 300 a spouse's.
https://www.sciencedaily.com/releases/2015/01/150112154456.htm

**The harvest (2014).** Aleksandr Kogan's company GSR built the quiz app
"thisisyourdigitallife" for SCL. About 270,000 people took it for pay. Facebook's
Graph API v1.0 also exposed their friends' data, so up to 87 million people were
affected. https://www.thejakartapost.com/life/2018/04/05/facebook-says-data-leak-hits-87-million-users-widening-privacy-scandal.html

The UK ICO's 2020 report: SCL matched the data to voter files, scored people with
off-the-shelf tools (scikit-learn), and clustered them for targeting. It used
"well recognised processes using commonly available technology". There was
"a degree of scepticism within SCL" about its own models, and the claim of "5,000+
data points on 230 million adult Americans" "may have been an exaggeration".
https://committees.parliament.uk/publications/2847/documents/27736/default/

**Message tailoring.** Matz et al., PNAS 2017, ran real Facebook ads that reached
about 3.5 million people. Ads matched to an audience's trait (extravert or
introvert, high or low openness) got up to about 40% more clicks and about 50%
more purchases. The absolute click rates were tiny.
https://pubmed.ncbi.nlm.nih.gov/29133409/

Alexander Nix, Concordia Summit 2016: "personality drives behavior". He claimed
CA had a model of every US adult. His usual example: a gun-rights ad built on a
burglary threat for "neurotic, conscientious" voters, and a father-and-son
hunting ad for "closed, agreeable" ones *(wording unverified)*.

**The loop.** Test and learn: split the audience, write variants, buy ads,
measure, fund the winners, repeat. The 2016 Trump campaign ran 50,000 to 60,000
Facebook ad variants a day; that was the campaign's own team, not necessarily
CA. https://www.axios.com/2017/12/15/how-facebook-fueled-trumps-campaign-1513306043

**Military heritage.** Nigel Oakes founded the Behavioural Dynamics Institute
(1990) and SCL (1993). Its method was Target Audience Analysis: study a group,
find what motivates it, and aim at changing behaviour rather than attitudes.
https://en.wikipedia.org/wiki/SCL_Group

**Did it work?** Kogan told MPs his scores were "highly inaccurate". Scholars
called the psychographic element "mainly branding". There is no good evidence it
swung an election. https://www.nature.com/articles/d41586-018-05056-6 ,
https://qz.com/1240331/cambridge-analytica-psychology-the-science-isnt-that-good-at-manipulation

### Method moves restaged in the room

| In the room | Real counterpart |
|---|---|
| either/or prompts on the phone | the quiz as bait (thisisyourdigitallife) |
| inferring from how you move, look and sound | Likes → SVD → OCEAN |
| segment labels ("THE LURKER") | CA's clusters, Nix's "neurotic, conscientious" audiences |
| tempo, sound and text tailored per trait | Matz 2017 ads, Nix's gun ads |
| bandit over five scenes, reward = being held | test and learn, 50k ad variants a day |
| machine confidence shown next to real accuracy | Nix's claims against the ICO findings |
| reveal, then delete | the 2018 disclosure |

## Behaviour → OCEAN: what a phone can see

Almost every cue correlates with a trait at r ≈ .1 to .3, which explains 1 to 9% of
the variance. That's useless for diagnosing one person and fine as a dramatic
prior. E is easiest to read, O shows through taste and exploration, and C, A
and N are close to zero at first meeting (Connelly & Ones 2010 meta-analysis).
https://people.ict.usc.edu/~gratch/CSCI534/Readings/ConnellyOnes-personality2010.pdf

| Signal | Trait (sign) | Rough r | Source |
|---|---|---|---|
| walking speed | C+, E+, O+, N− | .05 to .15 | Stephan/Sutin 2018, https://hrs.isr.umich.edu/bibcite/reference/14472 |
| coming close | E+, N− | .2 to .3, inconsistent | Perry 2013, https://www.frontiersin.org/articles/10.3389/fnhum.2013.00907/text |
| movement energy, expansiveness | E+ | .2 to .4 | Borkenau & Liebler 1992; Naumann 2009 |
| looking at faces or the screen | E+ (aversion N+) | .1 to .3 | Hoppe 2018, https://www.frontiersin.org/journals/human-neuroscience/articles/10.3389/fnhum.2018.00105/pdf |
| talkativeness | E+ | ≈ .3 | Mehl 2006, https://pubmed.ncbi.nlm.nih.gov/16737378/ |
| loudness, speech rate | E+ | .2 to .3 | Stern 2021 |
| voice pitch | ~0 | < .1 | Stern 2021; Ostermann 2025 (not used) |
| fast answers | C−, N+ | < .15, speculative | design licence only |
| touch and phone behaviour | mostly E | modest (weeks of data) | Stachl 2020 PNAS, https://www.pubmed.gov/32665436/ |
| picking the unknown option | O+ | ≈ .1, often null | CBB 2024, https://link.springer.com/article/10.1007/s42113-024-00224-6 |
| liking abstract or dark art | O+ | .2 to .3 | Feist & Brady 2004; Chamorro-Premuzic 2009 |
| intense music | O+ | .15 to .2 | Rentfrow & Gosling 2003, https://pubmed.ncbi.nlm.nih.gov/12793587/ |
| energetic dance music, techno | E+, A+ | ≈ .2 | Rentfrow & Gosling 2003 |

These set the signs and relative sizes of `ocean.WEIGHTS` and the caps in
`ocean.CONFIDENCE_CAP`.
