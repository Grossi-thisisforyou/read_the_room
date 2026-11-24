# How OCEAN prediction worked in the Cambridge Analytica case: a factual brief

*Prepared for an art project that restages the method openly, with consenting participants. Every claim has its source after it. Where a number could not be checked against the source, the brief says so.*

## 1. The research base: myPersonality (Kosinski, Stillwell and Graepel, PNAS 2013)

**Data.** 58,466 US volunteers gave their Facebook Likes plus profile and psychometric data through the myPersonality app. Users had about 170 Likes on average; the median was 68 and the range was 1 to 700. (https://pmc.ncbi.nlm.nih.gov/articles/PMC3625324)

**Method.**
1. Build a sparse user × Like matrix: 1 if the user Liked the page, otherwise 0. (https://pmc.ncbi.nlm.nih.gov/articles/PMC3625324)
2. Reduce it with singular value decomposition (SVD) to k = 100 components. They used k = 30 for the smaller-sample variables: sexual orientation, parents' relationship status and drug use. (https://pmc.ncbi.nlm.nih.gov/articles/PMC3625324)
3. Predict numeric traits (personality, age, intelligence) with linear regression on the components, and binary traits (gender, orientation, party) with logistic regression. (https://pmc.ncbi.nlm.nih.gov/articles/PMC3625324)
4. Check everything with 10-fold cross-validation. (https://pmc.ncbi.nlm.nih.gov/articles/PMC3625324)

**Accuracy.** These are Pearson r values between predicted and questionnaire scores:
- Openness r = 0.43, close to the questionnaire's own test-retest reliability of 0.50. (https://pmc.ncbi.nlm.nih.gov/articles/PMC3625324)
- Extraversion r = 0.40. (https://pmc.ncbi.nlm.nih.gov/articles/PMC3625324)
- The text gives conscientiousness, agreeableness and emotional stability only as a group. They fall in the range 0.17–0.30, a range that also includes life satisfaction, and are roughly half of test-retest reliability. The exact per-trait values are in Figure 3, which I could not read, so they are **not verified here**. (https://pmc.ncbi.nlm.nih.gov/articles/PMC3625324)
- Binary traits, as correct-classification rates: gender 93%; Democrat vs Republican 85%; sexual orientation 88% for men and 75% for women; African American vs Caucasian American 95%. (https://pmc.ncbi.nlm.nih.gov/articles/PMC3625324)

**Example Likes.**
- High intelligence: "Thunderstorms", "The Colbert Report", "Science", "Curly Fries". Low intelligence: "Sephora", "I Love Being A Mom", "Harley Davidson", "Lady Antebellum". (https://pmc.ncbi.nlm.nih.gov/articles/PMC3625324)
- People who liked "Hello Kitty" tended to be high in Openness and low in Conscientiousness, Agreeableness and Emotional Stability. (https://pmc.ncbi.nlm.nih.gov/articles/PMC3625324)
- The ranked lists of trait-predictive Likes are in the paper's Table S1, which I did not retrieve. (https://pmc.ncbi.nlm.nih.gov/articles/PMC3625324)
- Later work from the same group used trait-specific Likes: Shwayze (extraversion), Stargate SG1 (introversion), the BBC drama *The Fall* (high openness) and Farm Town (low openness). (https://www.bps.org.uk/research-digest/study-shows-how-easy-and-effective-it-facebook-ads-target-your-personality)

## 2. Computers vs friends (Youyou, Kosinski and Stillwell, PNAS 2015)

- 86,220 volunteers completed a 100-item Big Five questionnaire. Friends and family rated them on a 10-item version: 17,622 participants had one judge and 14,410 had two. (https://www.cam.ac.uk/research/news/computers-using-digital-footprints-are-better-judges-of-personality-than-friends-and-family)
- Self-other agreement: the Likes-based computer model reached r = 0.56; Facebook friends reached r = 0.49. (https://www.gsb.stanford.edu/index%2ephp/node/404186)
- Likes needed for the model to match or beat each kind of judge: work colleague 10, friend or roommate 70, family member 150, spouse 300. The average user had about 227 Likes. (https://www.cam.ac.uk/research/news/computers-using-digital-footprints-are-better-judges-of-personality-than-friends-and-family)
- External validity: computer judgments predicted substance use, political attitudes and physical health better than human judges did, and for some outcomes better than self-reports. (https://www.gsb.stanford.edu/index%2ephp/node/404186)
- The paper's modelling details (the regression method on Likes) and the per-judge r values for spouses and family could not be fetched (PMC blocked access), so they are **not verified here**.

## 3. Kogan / GSR, "thisisyourdigitallife", and Cambridge Analytica

**The contract.** On 4 June 2014, Aleksandr Kogan's company Global Science Research (GSR) contracted with SCL. The contract laid out a pipeline (https://techcrunch.com/2018/03/29/heres-cambridge-analyticas-plan-for-voters-facebook-data/amp/):
1. Recruit a seed sample through paid online panels and score it with psychometric inventories.
2. Run the quiz app on Facebook.
3. Model the Facebook data, including Likes, against the seed scores.
4. Match the scored profiles to SCL voter records in 11 US states, with a target of at least 2 million matched records.

The contract promised a bonus if GSR delivered 2.1M matched records at $0.50 or less each. It also claimed the Like-based predictions approached test-retest reliability and beat partners and friends, a claim taken from the myPersonality literature. (https://techcrunch.com/2018/03/29/heres-cambridge-analyticas-plan-for-voters-facebook-data/amp/)

**How many took the quiz.** Sources give different figures:
- About 270,000, the figure Facebook confirmed. (https://techcrunch.com/2018/03/27/facebook-data-misuse-scandal-affects-substantially-more-than-50m-claims-wylie/)
- "About 300,000" worldwide, in the ICO's 2020 letter. (https://cy.ico.org.uk/media2/migrated/2618383/20201002_ico-o-ed-l-rtl-0181_to-julian-knight-mp.pdf)
- "Up to approximately 320,000", in the ICO's 2018 report. (https://ico.org.uk/media2/migrated/2259371/investigation-into-data-analytics-for-political-purposes-update.pdf)
- Before any of these, Wylie said a pilot of 10,000 people ran in late May 2014. (https://techcrunch.com/2018/03/27/facebook-data-misuse-scandal-affects-substantially-more-than-50m-claims-wylie/)

The ICO 2018 report says SCL arranged for Kogan to pay US citizens to take the test, but it does not give the amount. (https://ico.org.uk/media2/migrated/2259371/investigation-into-data-analytics-for-political-purposes-update.pdf)

**How friends' data reached ~87M.** Facebook's Graph API at the time let an app request data about a user's friends as well as the user, limited by the friends' privacy settings. A few hundred thousand installs therefore reached up to 87 million people, "mostly in the US", by Facebook's estimate. (https://ico.org.uk/media2/migrated/2259371/investigation-into-data-analytics-for-political-purposes-update.pdf ; https://about.fb.com/news/2018/04/restricting-data-access/)

**Data fields** (ICO 2018, §4.3.1; https://ico.org.uk/media2/migrated/2259371/investigation-into-data-analytics-for-political-purposes-update.pdf):
- From quiz takers: public profile (name, gender), date of birth, current city, photos they were tagged in, pages they had liked, timeline and news feed posts, friends list, email address, and Facebook messages.
- From their friends: public profile, date of birth, current city, tagged photos and liked pages.
- For about 30 million people, personality test results were "paired with Facebook data to seek out psychological patterns and build models".

The ICO 2020 letter mentions a dataset of "Facebook likes (570 data points for 30 million individuals)" and a social graph covering 30 million people. (https://cy.ico.org.uk/media2/migrated/2618383/20201002_ico-o-ed-l-rtl-0181_to-julian-knight-mp.pdf)

**How the models were built and used** (ICO 2020, Annex 2; https://cy.ico.org.uk/media2/migrated/2618383/20201002_ico-o-ed-l-rtl-0181_to-julian-knight-mp.pdf):
- Quiz answers were combined with Likes to model the personality traits of users and their friends (para 14).
- The GSR records were matched to SCL's US voter, demographic and consumer database by name, date of birth and location (paras 28–29).
- The outputs included "scores for voting frequency, whether likely republican or democrat, voting consistency" alongside predicted personality traits (para 29).
- Machine learning generated more predicted scores, such as partisanship, and these "were used to identify clusters of similar individuals" for political advertising (para 30).
- Data shared with SCL covered about 30 million US voters, starting with about 2.1 million in autumn 2014 (para 18).

**Wylie's testimony** (House of Commons DCMS Committee, 27 March 2018):
- He described "an app that harvests Facebook data and friend network data also" (Q1305). (https://committees.parliament.uk/oralevidence/7803/html/)
- His example of how traits were used: people with "a high degree of openness and a high degree of neuroticism" could be targeted because "you can then go out and predict how likely somebody is going to be to adopt more conspiratorial messaging" (Q1320). (https://committees.parliament.uk/oralevidence/7803/html/)
- He called the GSR data "the foundational dataset that then was modeled to create the algorithms". (https://techcrunch.com/2018/03/27/facebook-data-misuse-scandal-affects-substantially-more-than-50m-claims-wylie/)

**Did it work? Was it new?** The ICO's 2020 final letter (https://cy.ico.org.uk/media2/migrated/2618383/20201002_ico-o-ed-l-rtl-0181_to-julian-knight-mp.pdf) found:
- The techniques were "well recognised processes using commonly available technology", mostly open-source libraries such as scikit-learn. The work "does not show any proprietary technology, or processes" (para 26).
- The outputs were predictions whose "real-world accuracy" was "likely much lower" for people outside the training data. Internal communications showed SCL staff were sceptical, and concerned about how the external messaging compared with "the reality of their processing" (para 27).
- SCL's marketing claim of "over 5,000 data points per individual on 230 million adult Americans" "may have been an exaggeration" (para 10).
- The ICO could not determine from the evidence which GSR data was used in specific campaign activity (para 30).
- The GSR data "could not have been used in the Brexit Referendum" (para 19).

Kogan himself said on TV that the models were not very accurate for individuals and were useful only in aggregate. (https://techcrunch.com/2018/03/29/heres-cambridge-analyticas-plan-for-voters-facebook-data/amp/)

## 4. Does psychological targeting persuade? (Matz, Kosinski, Nave and Stillwell, PNAS 2017)

**Design.** Three field studies on Facebook reached more than 3.5 million people. (https://www.jbs.cam.ac.uk/insight/2017/how-effective-is-psychological-targeting-in-advertising/)

Facebook does not let advertisers target personality directly, so the researchers used Likes as a proxy. From about 65,000 myPersonality users, they picked Likes that correlated strongly with one trait and were neutral on the others: Shwayze for extraversion, Stargate SG1 for introversion, *The Fall* for high openness, Farm Town for low openness. They then targeted ads at the people who had Liked those pages. (https://www.bps.org.uk/research-digest/study-shows-how-easy-and-effective-it-facebook-ads-target-your-personality)

**Ads.** For a beauty retailer, extraverts saw "Dance like no one's watching (but they totally are)" and introverts saw "Beauty doesn't have to shout". (https://www.jbs.cam.ac.uk/insight/2017/how-effective-is-psychological-targeting-in-advertising/)

A crossword app ran ads matched to high or low openness; its ad copy was not available in the sources I read. (https://www.bps.org.uk/research-digest/study-shows-how-easy-and-effective-it-facebook-ads-target-your-personality)

A bubble-shooter game's audience was judged introverted from its Likes. It tested "Phew! Hard day? How about a puzzle to wind down with?" against its standard ad. (https://www.bps.org.uk/research-digest/study-shows-how-easy-and-effective-it-facebook-ads-target-your-personality)

**Effects** (matched ads compared with mismatched or standard ads; https://www.bps.org.uk/research-digest/study-shows-how-easy-and-effective-it-facebook-ads-target-your-personality):
- Beauty retailer: 1.54× more likely to lead to a purchase.
- Crossword app: 1.38× clicks and 1.31× purchases.
- Bubble game: 1.3× clicks and 1.2× purchases.
- Headline: "up to 40% more clicks and up to 50% more purchases".

The sources give relative effects only, with no absolute conversion rates, so the absolute size of the effect is small or unknown. (https://www.bps.org.uk/research-digest/study-shows-how-easy-and-effective-it-facebook-ads-target-your-personality)

## 5. Predicting personality from text

**Schwartz et al. 2013, PLOS ONE.**
- Data: about 75,000 Facebook users (about 72,000 in the personality analyses), 15.4M status updates, about 309M words. (https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0073791)
- Method: "differential language analysis", an open-vocabulary approach using 1–3-word phrases and LDA topics, compared against the fixed LIWC dictionaries. (https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0073791)
- Words that went with each trait (https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0073791):
  - Extraverts: "party", "love you", "boys", "ladies". Introverts: "computer", "Internet", "reading".
  - Neuroticism: "hate", "sick of", "depressed". Emotional stability: "sports", "vacation", "beach", "church", "team", "blessed".
  - High openness: "music", "art", "writing", "dream", "universe", "soul". Low openness: shorthand such as "2day" and "ur".
- Prediction accuracy (R, open-vocabulary vs LIWC): openness .42 vs .29, agreeableness .35 vs .25, extraversion .31 vs .27, conscientiousness .31 vs .29, neuroticism .31 vs .21. (https://ppc.sas.upenn.edu/sites/default/files/socialmediapub.pdf)

**Park et al. 2015, JPSP.**
- Sample: a model trained on 66,732 users and validated on 4,824 other users. (https://www.gsb.stanford.edu/index%2Ephp/node/428246)
- Convergence with self-report: O .43, C .37, E .42, A .35, N .35, average .38. (https://moodle.jku.at/mod/resource/view.php?id=11581)
- Against friend ratings (N = 745), the language model averaged .39 and friends averaged .32. The difference was not significant overall; it was significant only for openness (.46 vs .25). (https://moodle.jku.at/mod/resource/view.php?id=11581)
- Six-month test-retest stability averaged .70. (https://moodle.jku.at/mod/resource/view.php?id=11581)
- Words: higher extraversion went with "love", "party", "dinner with"; lower with "computer", "book", "probably". (https://moodle.jku.at/mod/resource/view.php?id=11581)

## 6. Measuring the ground truth: public-domain questionnaires

**IPIP 50-item Big-Five Factor Markers (Goldberg).**
- Content: 10 items per factor, answered on a 1–5 scale from "Very Inaccurate" to "Very Accurate". The factors are Extraversion, Agreeableness, Conscientiousness, Emotional Stability (the reverse of Neuroticism) and Intellect/Imagination (≈ Openness). The page lists each item's factor and its +/− keying. (https://ipip.ori.org/New_IPIP-50-item-scale.htm)
- Licence: the IPIP is in the public domain. (https://ipip.ori.org/New_IPIP-50-item-scale.htm)
- Scoring: +keyed items score 1–5 and −keyed items are reversed (5–1). Sum the items in each scale. (https://ipip.ori.org/newScoringInstructions.htm)
- Item order: 1 = E, 2 = A, 3 = C, 4 = ES, 5 = I, and the cycle repeats. (https://ipip.ori.org/New_IPIP-50-item-scale.htm)
- −keyed items (https://ipip.ori.org/New_IPIP-50-item-scale.htm):
  - E: 6, 16, 26, 36, 46
  - A: 2, 12, 22, 32
  - C: 8, 18, 28, 38
  - ES: 4, 14, 24, 29, 34, 39, 44, 49
  - I: 10, 20, 30

**IPIP-NEO-120 (Johnson 2014).**
- 120 items measuring 30 facets, with 4 items per facet. (https://pmc.ncbi.nlm.nih.gov/articles/PMC7871748)
- Johnson's paper gives the full item list and keying in Table 1. (https://bpb-us-e1.wpmucdn.com/sites.psu.edu/dist/1/163537/files/2023/07/IPIPNEO120.pdf)
- A US sample of 320,128 showed a mean facet α of .78. (https://pmc.ncbi.nlm.nih.gov/articles/PMC7871748)

## 7. Honest limits

- **Moderate accuracy overall.** Azucar, Marengo and Settanni's 2018 meta-analysis covered 21 papers and 23 studies. Pooled r: E .39, O .38, C .34, N .33, A .28, overall .34. Accuracy improved when several kinds of footprint were combined and when demographics were added. The authors judge accuracy "at best moderate", too low for assessing individuals but usable for groups. (https://ejournals.facultas.at/index.php/digitalpsychology/article/download/1823/1584)
  - *Caveat:* I read these figures from that PDF. I could not open the 2018 *Personality and Individual Differences* original (https://eld.bl.uk/catalog/100073550169_0x000001) to confirm them.
- **Same conclusion for Facebook data.** Marengo and Montag's 2020 Facebook meta-analysis puts accuracy at r = .33 and says predictions are not yet reliable at the individual level. (https://ejournals.facultas.at/index.php/digitalpsychology/article/view/1823)
- **A second meta-analysis agrees.** Settanni, Azucar and Marengo 2018 (CBSN) found a pooled personality r = .34. (https://iris.unito.it/bitstream/2318/1774663/4/preprint%20Settanni%20et%20al%20meta%20analysis.pdf)
- **What r ≈ .35–.40 means.** It explains about 12–16% of the variance, so many individuals are misplaced. That is the point the ICO and Kogan made. (https://cy.ico.org.uk/media2/migrated/2618383/20201002_ico-o-ed-l-rtl-0181_to-julian-knight-mp.pdf ; https://techcrunch.com/2018/03/29/heres-cambridge-analyticas-plan-for-voters-facebook-data/amp/)
- **Persuasion effects are relative, not absolute.** The Matz effects are relative lifts on low baseline click rates. Their effect on elections "remain[s] uncertain". (https://www.jbs.cam.ac.uk/insight/2017/how-effective-is-psychological-targeting-in-advertising/)

## Method we can copy (consent-first)

1. **Consent and scope.** Each participant gives informed, written consent and supplies their *own* data. Never collect data about their friends, the step that turned 300k quiz takers into 87M people. (https://ico.org.uk/media2/migrated/2259371/investigation-into-data-analytics-for-political-purposes-update.pdf)
2. **Ground truth first.** The participant completes the IPIP-50 and you score it with the published key. Keep these scores sealed from the prediction step. (https://ipip.ori.org/New_IPIP-50-item-scale.htm ; https://ipip.ori.org/newScoringInstructions.htm)
3. **Collect the footprint.** The participant exports their own platform data: Likes or follows, posts, and listening or viewing history. Mirror the GSR field list (liked pages, posts, city, birth year), but take only the participant's own records. (https://ico.org.uk/media2/migrated/2259371/investigation-into-data-analytics-for-political-purposes-update.pdf)
4. **Likes route.** Build a binary person × item matrix, reduce it with SVD, and regress each trait on the components, as Kosinski et al. did. With a small cohort, fit on a larger public training set, or score items against published trait-Like associations instead. (https://pmc.ncbi.nlm.nih.gov/articles/PMC3625324)
5. **Text route.** Extract word, phrase and topic frequencies from the person's posts and score them with open-vocabulary trait associations, as Schwartz et al. and Park et al. did. Average the Likes and text predictions; combining footprints improves accuracy. (https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0073791 ; https://ejournals.facultas.at/index.php/digitalpsychology/article/download/1823/1584)
6. **Taste and behaviour predictions.** From the predicted OCEAN profile, generate trait-matched messages, for example an extravert framing against an introvert framing as in Matz et al. Show the participant both versions and record which one they prefer. (https://www.bps.org.uk/research-digest/study-shows-how-easy-and-effective-it-facebook-ads-target-your-personality)
7. **Validate.** Unseal the questionnaire scores. For each trait, report the predicted-vs-actual correlation across the cohort and each person's error. Compare against the benchmark of r ≈ .3–.4 and the friend-judge benchmark of r ≈ .49. (https://ejournals.facultas.at/index.php/digitalpsychology/article/download/1823/1584 ; https://www.gsb.stanford.edu/index%2ephp/node/404186)
8. **Disclose and delete.** Show each participant their predicted profile, their actual profile and the gap between them, then delete the raw exports. The gap is the ICO's "real-world accuracy" point made visible. (https://cy.ico.org.uk/media2/migrated/2618383/20201002_ico-o-ed-l-rtl-0181_to-julian-knight-mp.pdf)
