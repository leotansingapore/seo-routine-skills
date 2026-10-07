# Banned Patterns Reference — Complete List

This file is the single source of truth. Every pattern here is prohibited in all output. No exceptions, no context-dependent allowances, no "it sounds fine here." If it's on this list, it does not appear in the output.

---

## 1. Banned Words

These words became statistically overrepresented in published text after widespread LLM adoption in 2023. Their presence — especially in clusters — is one of the strongest signals of AI-generated content.

### Absolute Ban (never use regardless of context)

- delve / delves / delving
- tapestry (figurative — "rich tapestry of")
- underscore (as a verb meaning "emphasize")
- pivotal
- crucial
- vital (when meaning "important," not "necessary for life")
- intricate / intricacies
- multifaceted
- nuanced (as a standalone adjective to praise complexity)
- landscape (as abstract noun — "the evolving landscape of")
- interplay
- testament (as in "a testament to")
- fostering / foster (figurative — "fostering innovation")
- garner / garnered
- showcase / showcasing
- underscore / underscoring
- emphasizing (as a sentence-ending participle)
- highlighting (as a sentence-ending participle — "highlighting its importance")
- encompassing
- align with / aligns with (figurative — "aligns with our mission")
- resonate / resonates with
- vibrant
- enduring (as in "enduring legacy")
- enhance / enhancing
- pivotal moment
- focal point
- indelible mark
- deeply rooted
- groundbreaking (figurative)
- nestled
- renowned
- exemplifies
- profound
- boasts (as in "the city boasts")
- diverse array
- commitment to (as puffery — "commitment to excellence")
- natural beauty
- in the heart of
- rich (figurative — "rich history," "rich culture")
- robust (outside engineering/statistics)
- leveraging / leverage (outside finance)
- holistic
- synergy / synergies
- paradigm (outside Kuhn)
- ecosystem (outside biology, unless referring to actual tech ecosystems with specific products)
- stakeholder (unless you're naming specific stakeholders)
- empower / empowering
- innovative / innovation (unless describing a specific, named invention)
- transformative
- cutting-edge
- state-of-the-art
- next-generation
- unlock (figurative — "unlock potential")
- harness (figurative — "harness the power of")
- navigate (figurative — "navigate challenges")
- craft / crafted (figurative — "carefully crafted")
- curated / curation (outside museums/galleries)
- reimagine / reimagined
- spearheaded
- galvanized
- catapulted

### Contextual Ban (use only when the literal meaning is intended)

- key (as adjective — "key factor." Use "main," "primary," or name the specific factor)
- significant (use only with statistical significance or measurable outcomes)
- valuable (replace with what specifically makes it valuable)
- explore / exploring (as in "explores the themes of" — say what it actually does)
- comprehensive (replace with specific scope — "covers all 12 regions" not "comprehensive coverage")
- dynamic (replace with what actually changes and how)
- seamless / seamlessly (nothing is seamless — describe how it works)
- streamline / streamlined (say what was removed or simplified)

---

## 2. Banned Phrases

### Significance and Legacy Phrases
- stands as / serves as [a testament/reminder/symbol]
- is a testament to
- marks a pivotal moment / key turning point
- reflects broader trends
- underscores / highlights its importance / significance
- symbolizing its ongoing / enduring / lasting [legacy/impact]
- contributing to the broader [field/movement/trend]
- setting the stage for
- marking / shaping the [future/direction]
- represents / marks a shift
- evolving landscape
- indelible mark on
- deeply rooted in
- plays a crucial / vital / significant / pivotal role
- in the broader context of

### Puffery Phrases
- boasts a [vibrant/thriving/diverse]
- offers a diverse array / wide range
- rich cultural heritage
- commitment to excellence / innovation / sustainability
- nestled in the heart of
- a beacon of [hope/progress/innovation]
- at the forefront of
- pushing the boundaries of
- raising the bar for
- world-class
- best-in-class
- thought leader / thought leadership
- game-changer / game-changing
- a force to be reckoned with

### AI Transition Phrases
- Additionally, (at sentence start)
- Furthermore,
- Moreover,
- In addition,
- It's worth noting / It is worth noting
- It's important to note / It is important to note
- It's crucial to remember
- Notably,
- Interestingly,
- Importantly,

### AI Conclusion Phrases
- In summary,
- In conclusion,
- Overall,
- To summarize,
- To sum up,
- In essence,
- Ultimately, (as a conclusion opener)
- All in all,
- At the end of the day,
- The bottom line is

### Hedging Phrases
- may vary
- could potentially
- it should be noted that
- it remains to be seen
- only time will tell
- while not without its challenges

### Chatbot Remnants
- I hope this helps
- Would you like me to
- Let me know if
- Here's a breakdown of
- Here's an overview of
- Certainly!
- Of course!
- Great question!
- That's a great point
- You're absolutely right
- Is there anything else
- as of my last update / knowledge cutoff
- based on available information
- while specific details are limited

### Vague Attribution Phrases
- experts say / experts argue / experts agree
- industry observers note
- critics argue / some critics
- several sources / publications
- has been described as
- widely regarded as
- is considered to be
- according to reports

### Challenge-and-Future Pattern
- Despite its [positive], [subject] faces several challenges
- Despite these challenges
- faces challenges typical of
- the future of [X] faces several challenges, including
- future investments in [X] could enhance
- despite their promising applications

### Negative Parallelism Phrases
- Not only X, but also Y
- Not just X, but Y
- It's not about X — it's about Y
- It's not X, it's Y
- No X, no Y, just Z
- While X, it's also Y

---

## 3. Banned Formatting Patterns

### Inline-Header Bullet Lists
The pattern where each bullet starts with a **bolded term:** followed by descriptive text.
```
BAD:
- **Discovery:** The initial phase where...
- **Implementation:** The phase where teams...
- **Review:** The final assessment of...

GOOD (if a list is needed):
- Discovery: initial research and problem mapping
- Implementation: building and testing the solution
- Review: measuring results against the original goal

BETTER (if items connect to each other):
Write as prose. "Discovery feeds implementation, which produces
the data you need for review."
```

### Excessive Boldface
Bold is for one purpose: the first mention of a defined term. Not for emphasis. Not for key phrases. Not for making a wall of text "scannable."

### Title Case Headings
Use sentence case. "How the scoring system works" not "How The Scoring System Works."

### Emoji in Headers or Bullets
Never. Not as bullet markers, not as section decorations, not as emphasis.

### Unnecessary Small Tables
If a table has two columns and three rows, it's probably prose. Write it as prose unless the data genuinely needs tabular comparison.

### Markdown Artifacts in Non-Markdown Contexts
No `**bold**` syntax in documents that don't render markdown. No `#` heading markers in prose. No backtick code formatting for non-code terms.

---

## 4. Banned Sentence Structures

### The Superficial -ing Closer
Sentences that end with a present participle phrase adding no information:
- "...highlighting its importance in the region"
- "...underscoring the significance of this development"
- "...contributing to the broader narrative"
- "...reflecting the diverse nature of"
- "...showcasing a commitment to"
- "...fostering a sense of community"
- "...ensuring continued growth and development"

**Fix:** Cut the -ing clause. If the sentence feels incomplete, the main clause was too vague — rewrite it.

### The Copula Dodge
Replacing "is" or "has" with fancier verbs:
- "serves as a hub" → "is a hub"
- "stands as a reminder" → CUT (puffery)
- "represents a shift" → "changed [what specifically]"
- "features a diverse population" → "has [number] residents from [places]"
- "boasts a rich history" → "was founded in [year] and [what happened]"
- "offers a wide range" → "has [specific things]"

### The False Range
"From X to Y" where X and Y are not on the same scale:
- "from innovation to sustainability" — no scale
- "from local to global impact" — borderline, only if describing actual geographic expansion
- "from strategy to execution" — acceptable, there's a real sequence

### The Elegant Variation Loop
Same concept, different words each time:
- "the initiative... the program... the effort... the endeavor"
- "researchers... scholars... academics... experts in the field"

**Fix:** Pick one word. Use it every time. Readers prefer clarity over variety.

### The Setup-Pivot
"While [seemingly positive thing], [subject] also [dramatic reveal]"
This is AI's version of creating drama. Just state both facts.

---

## 5. Banned Content Patterns

### The Significance Assertion
Any sentence whose only purpose is to tell the reader that something is important, without saying what it does or what changes because of it.

### The Ecosystem Padding
Unsupported claims about ecological significance, conservation status, or environmental impact inserted into articles about places, species, or organizations.

### The Media Coverage Inventory
Listing outlets that covered a subject as proof of importance: "Featured in The New York Times, BBC, and The Guardian." Either summarize what those outlets said or cite them as sources without inventory.

### The Social Media Mention
"Maintains an active social media presence" or "has a strong online following." Either describe specific relevant social media activity or leave it out.

### The "Despite" Sandwich
Positive claim → "Despite challenges" → Return to positive. This is AI's default structure for appearing balanced. Real balance comes from naming specific tradeoffs, not from templated acknowledgment of challenges.

### The Future Speculation Section
"Future developments may include..." "Ongoing investments could lead to..." "As the field continues to evolve..." If you don't know what will happen, don't speculate. If specific plans exist, report them as plans with named sources.

### The Didactic Disclaimer
"It's important to note that results may vary." "While this approach has benefits, individual circumstances differ." These add nothing. Cut them.

---

## 6. Quick-Check Clusters

AI patterns rarely appear alone. These clusters are strong detection signals — if you find one pattern, scan for its usual companions:

**Cluster A — The Puffery Stack:** "vibrant" + "rich" + "diverse" + "nestled" + "in the heart of" + "boasts"

**Cluster B — The Significance Stack:** "pivotal" + "crucial" + "underscores" + "testament" + "enduring legacy" + "broader trends"

**Cluster C — The Structure Stack:** Title Case headings + inline-header bullets + rule of three + conclusion section + "Additionally" transitions

**Cluster D — The Hedge Stack:** "may vary" + "it's important to note" + "while challenges remain" + "despite" + vague attribution

**Cluster E — The Copula Dodge Stack:** "serves as" + "stands as" + "represents" + "features" + "offers" + "marks"

If you find two or more items from the same cluster in a single paragraph, that paragraph needs a full rewrite, not a word swap.
