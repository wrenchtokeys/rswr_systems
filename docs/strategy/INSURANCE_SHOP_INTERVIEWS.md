# The five insurance-shop interviews

**Written:** 2026-09-17 · **Owner:** Drake · **Decides:** the Path B question in
`PRODUCT_DIRECTION.md` (system of record for insurance/TPA shops — yes, no, or not yet).
**Status:** 0 of 5 held. Record each one in §6 as it happens.

This is the script for the calls `IMPROVEMENT_SESSIONS.md` D1 and D2 have asked for since
2026-08-07. Nothing in Track D gets built until these are written up. The spine (quotes, claim
tracking, price book) is on prod, so on these calls you can show a shop something real rather
than describe a plan.

---

## 1. What the five calls have to answer

Four questions. If you hang up with these answered, the call worked.

| # | Question | Why it decides Path B |
|---|---|---|
| Q1 | **How does insurance money actually reach this shop today** — which networks, what the shop had to do to get on them, and what it costs them per job to be on them? | Whether a shop our size can be credentialed at all is the gate D1 names. Nobody can build their way past it. |
| Q2 | **Where is the daily pain: getting the claim submitted, or getting paid what was authorized?** | B5 already tracks expected vs received. If the pain is short-pay and follow-up, Tier 1 is most of the value and Path B is optional. If the pain is submission, Path B is the product. |
| Q3 | **Would billing from inside the software change what they buy?** Not "would you like it" — "what would you cancel, and what would you pay?" | The only evidence that Path B has a customer. |
| Q4 | **How do they price glass, and would their own history be enough** for the cash and fleet side? | Decides whether a NAGS licence is ever worth its recurring cost, or whether B6 already covers what they need. |

Everything else in the script exists to get honest answers to these four.

## 2. Who to call, and how to get 25 minutes

**Pick shops that look like this:**
- Independent (not a Safelite location), 2–8 technicians, doing replacements as the main line
  of work, and saying "we take insurance" on their site or Google listing. A shop that is
  all cash-and-fleet cannot answer Q1–Q3.
- At least two on a TPA network today (Safelite Solutions, LYNX Services) and at least one
  that deliberately is not — the non-network shop tells you what the network costs.
- Not family, not a friend's shop. Three of the five should be in a different metro from
  yours so the answers are not about your local market.

**Where they come from:** the Google Maps results for "auto glass" in three cities, filtered
to independents with 20+ reviews; the shops your Mygrant rep will name if asked "who else
around here does insurance volume"; the two shops that already asked about the product.

**The ask** (phone, not email — owners answer the phone):

> "I run a windshield repair shop in Arkansas and I built the software my shop runs on.
> I'm trying to work out whether it should handle insurance billing, and I don't want to
> guess at how that works in a shop like yours. Could I get 25 minutes on the phone, at a
> time you're not slammed? I'm not selling anything on this call."

If they ask what the software does, one sentence — "jobs, invoices, quotes, and it tracks
what an insurer still owes you" — and back to the ask. The demo is a reward at the end,
not the opener.

**Before you dial:** their Google reviews (do customers mention insurance?), their site
(network logos? "we bill your insurance directly"?), and whether they list NAGS or "OEM
pricing" anywhere. Write down what you think their answer to Q1 will be, so you notice
when the real one is different.

## 3. The 25 minutes

Times are a guide; let the shop run long on whatever they care about most, and cut the
section they are bored by. **Ask about what happened last week, not what they would do
in general.** A shop's opinion of a feature is worth nothing; the story of the last claim
that paid short is worth the whole call.

### 0. Open — 2 min

- Who you are: a shop owner first, who built software for his own shop and his dad's, and is
  deciding what to build next.
- What you want: how insurance work actually goes in their shop. Not selling today.
- Ask to record or say you'll take notes. Ask how long they have.

### 1. Their week — 4 min

The point is the mix. A shop that is 70 % insurance answers Q1–Q3 very differently from one
that is 20 %.

- "Roughly, out of last week's jobs, how many were insurance, how many the customer paid, how
  many fleet?"
- "Who takes the call when a customer says 'I've got a claim number'? What happens next, in
  order?"
- "What's on the desk when that happens — which screen, which piece of paper?"

**Listen for:** the name of the system they submit in; a person whose whole job is claims;
"we just call it in".

### 2. How the money flows — 8 min (this is the call)

**Getting on** (Q1):
- "Which networks are you on — Safelite Solutions, LYNX, anyone else? Any insurer direct?"
- "How did you get on? Who did you talk to, what did they need from you, how long did it
  take?" — you are listening for a credentialing path a two-tech shop could walk.
- "Is there a fee, a rate schedule, or a discount off list that comes with being on the
  network? What does a network job pay you compared to a cash job on the same glass?"
- If they are **not** on a network: "Was that a choice? What did you do the last time a
  customer with a claim called?" (Cash-and-file, walk them to the network, turn them away?)

**The claim, start to finish** (Q2):
- "Take the last insurance job that's fully paid. Walk me through it from the first call to
  the money landing — every step, and who did it."
- "Where does the dispatch or authorization number come from, and where do you write it
  down?"
- "How do you submit — the portal, EDI through your shop software, a phone call, a fax?"
- "How long from install to payment, typically? Longest lately?"

**Short-pay** (Q2):
- "When the check comes and it's less than the authorization — how often is that? How do you
  find out?"
- "What do you do about it? Who chases it, how, and how long do you keep chasing before you
  write it off?"
- "What did you write off last month?" — a number here is gold.

**Listen for:** whether short-pay is a monthly line item or a rare annoyance; whether anyone
reconciles at all; whether they can answer "what's outstanding right now" without looking.

### 3. Pricing — 4 min (Q4)

- "When you price a replacement for a cash customer, where does the number come from?"
- "Do you pay for NAGS? What does it cost you a year, and how often do you actually open it?"
- "Same glass, same truck, six months apart — is that the same price? How do you remember?"
- "If your software showed you 'you charged $450 for this glass on this model last time',
  would that replace what you do now, or sit next to it?"

**Listen for:** a NAGS subscription they resent; pricing from a supplier's quote rather than a
catalog; the price living in one person's head.

### 4. Software today — 3 min

- "What do you pay for, monthly, to run the shop? Which of those would you drop tomorrow if
  you could?"
- "When did you last switch a system? What made you finally do it?"
- "What would a new system have to do on day one for you to move?"

**Listen for:** the switching trigger. It is almost never a feature; it is usually a person
leaving, a price increase, or a lost check.

### 5. The decision question — 3 min (Q3)

Ask both halves, in this order, and write the answers down separately.

- "Suppose a system tracked every claim — what was authorized, what came in, what's short,
  what's outstanding — but you still submitted the way you do today. Would that change what
  you pay for? What would it be worth a month?"
- "Now suppose it also submitted the claim to the network for you, from the same screen.
  Different answer? What would you cancel?"
- "What would make you *not* trust it with insurance work?"

**Listen for:** whether the second answer is materially different from the first. If it is
not, Path B is not what they are buying.

### 6. Close — 1 min

- "Can I show you what I've got in a week and get your reaction?" (This is the trial ask.
  Book the time now.)
- "Who else should I be talking to?" — every call should produce the next one.
- "If I write up what I learned from these calls, do you want a copy?" Most say yes; it is
  the cheapest goodwill there is.

## 4. What not to do

- **Don't pitch.** The moment you describe a feature, the rest of the call is them being
  polite about it. The demo is booked at the end, not given in the middle.
- **Don't ask "would you use…".** Ask what they did last time. Future-tense answers are
  always yes and mean nothing.
- **Don't lead.** "Short-pay must be a nightmare" gets a yes. "What happened with the last
  short check" gets a story.
- **Don't correct them** on how the industry works. If they say something you think is wrong,
  ask another question; they are the evidence.
- **Don't let a shop that is 10 % insurance count as one of the five.** Note it, thank them,
  and find another.

## 5. Capture, the same day

One record per call. Fill it within an hour while it is fresh; the numbers fade first.

```
Shop:                         City:            Techs:        Called on:
Mix last week:  ___ insurance / ___ cash / ___ fleet   (out of ___ jobs)
Networks:       [ ] Safelite Solutions  [ ] LYNX  [ ] insurer direct: ______  [ ] none (by choice? Y/N)
Getting on:     who / how long / what it took:
Cost of network: fee or discount off list:            network vs cash on same glass: $___ vs $___
Submits via:    [ ] portal  [ ] EDI in shop software (which: ______)  [ ] phone  [ ] fax
Install → paid: typical ___ days   worst lately ___ days
Short-pay:      how often ___   found out how ___   who chases ___   written off last month $___
Can they say what's outstanding right now without looking?  Y / N
Pricing:        source ______   NAGS? Y/N  $___/yr   opens it ___ times/month
                "last price for this glass on this model" — replaces / sits beside / no
Software:       paying $___/mo for ______   would drop ______   last switch: when/why
Q3a  tracking only:      changes what they buy? Y/N   worth $___/mo
Q3b  + submission:       different answer? Y/N       would cancel ______   worth $___/mo
Trust breaker:
Demo booked:    Y/N  date        Referral:                 Wants the write-up: Y/N
The one sentence I'll remember from this call:
```

## 6. After five: the decision rule

Write the five records into the table below, then answer the four questions in one
paragraph each in `PRODUCT_DIRECTION.md` §The decision. The rule, agreed in advance so the
answers cannot be bent to fit:

- **Path B is on** if at least three of five say submission (Q3b) changes what they would
  buy *and* at least one of them described a credentialing route a shop of two techs could
  realistically walk, at a cost they could name. Then D1 Tier 2 (assisted submission) gets a
  session and a NAGS quote gets requested.
- **Path B stays a memo** if fewer than three say Q3b changes their answer, or nobody could
  describe how a small shop gets on a network. Then B5 (tracking) is the insurance product,
  and the go-to-market effort goes to the three non-family trial shops instead.
- **Either way**, if three or more say "last price for this glass on this model" would
  replace how they price today, B6 gets the follow-ups it was scoped without (per-customer
  pricing, a printed price list) before anyone spends on NAGS.

| # | Shop | Metro | Techs | Insurance share | Network(s) | Q1 route exists? | Q2 pain | Q3a $/mo | Q3b changes answer? | Q4 book enough? | Held on |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | | | | | | | | | | | |
| 2 | | | | | | | | | | | |
| 3 | | | | | | | | | | | |
| 4 | | | | | | | | | | | |
| 5 | | | | | | | | | | | |

## History

| Date | Change |
|---|---|
| 2026-09-17 | Written. The spine is on prod; the interviews are the head of the go-to-market step. |
