def _build_prompt(title: str, description: str, transcript_text: str) -> str:
    return f"""You are an expert at analyzing video transcripts to extract structured information for a video recommendation system.

## Your Task

**STEP 1:** Determine the content_type first — this will guide your entire extraction strategy.

**STEP 2:** Based on the content type, extract:
- **Summary** — objective 2-4 sentence description
- **Topics** — what the video is about: key subjects (skills, concepts, techniques, etc.) that receive substantial focus
- **Entities** — specific instances and key things central to the video (people, organizations, products, concepts, events etc.)
- **Tags** — searchable labels derived from topics, entities, and video nature

---

# STEP 1: Content Type Classification

Classify the video's **PRIMARY purpose** first. This determines how you approach extraction.

## Content Type Definitions

**ENTERTAINMENT** — Content consumed primarily for enjoyment, storytelling, or artistic expression
- Examples: sitcoms, web series, sketches, daily vlogs, travel vlogs, challenge videos, prank videos, let's plays, gameplay highlights, reaction videos, storytime videos, photography showcases, concert performances, artist documentaries

**EDUCATIONAL** — Teaching skills, explaining concepts, or providing how-to guidance
- Examples: coding tutorials, cooking recipes, makeup tutorials, fitness workouts, courses, lectures, DIY projects, repair guides, concept explainers, science explainers, language learning, instrument lessons, drawing tutorials, career advice, math lessons, gaming strategy guides

**REVIEW** — Evaluating, comparing, or showcasing products/services/media
- Examples: tech reviews, product reviews, unboxing videos, "X vs Y" comparisons, buying guides, software reviews, movie reviews, book reviews, game reviews, restaurant reviews, long-term reviews, shopping hauls with evaluations

**INTERVIEW** — Conversation-driven content with guests or subjects
- Examples: podcasts, video podcasts, one-on-one interviews, celebrity interviews, talk show clips, panel discussions, roundtables, AMAs, fireside chats, hot seat interviews

**NEWS** — Reporting on current events, investigating issues, or documenting reality
- Examples: breaking news, news updates, documentaries, mini-docs, investigative journalism, news commentary, event coverage, true crime documentaries, business case studies, explainer journalism, timeline videos

**LIFESTYLE** — Personal development, mindset, wellness, and life optimization
- Examples: motivational speeches, self-help content, productivity advice, habit building, transformation stories, morning routines (habit-focused), mental health content, meditation guides, philosophy videos, goal setting, relationship advice, fitness motivation stories

**OTHER** — Content that doesn't fit above categories or has insufficient data
- Examples: music videos (pure music), ASMR videos, clip compilations without narrative, silent films, pure B-roll, corrupted transcripts, abstract/experimental videos, unedited live streams

---

# STEP 2: Extract Structured Information

Now that you know the content type, extract the following fields:

## CANONICAL NAMING GUIDELINES:
- Use widely recognized forms: "react" not "React.js"
- People: "firstname lastname" lowercase: "elon musk"
- Products: include identifiers: "iphone 15 pro" not "iphone"
- Concepts: industry-standard terms: "machine learning" not "ML"
- De-duplicate: keep one canonical form per concept

---

## 1. Summary (`short_summary`)

- **2-4 sentences** maximum
- Objective, factual description of what the video covers
- Focus on the PRIMARY content, not minor tangents
- No marketing language or subjective claims

**Example:** "This video demonstrates how to make traditional Italian carbonara pasta from scratch. The chef explains the importance of egg temperature, proper pasta water ratio, and timing. Common mistakes like adding cream or overcooking eggs are addressed with practical solutions."

---

## 2. Topics (`topics`)

Main subjects, skills, and concepts the video focuses on. Extract moderately specific topics that receive substantial coverage - not overly specific details or tangential mentions.

**What to look for** (these are just examples to guide your thinking):
- **Educational videos** often include skills taught, concepts explained, techniques demonstrated etc.
- **Entertainment videos** might discuss various subjects - extract sparingly, only topics that receive substantial focus
- **Review videos** typically focus on product categories, features being evaluated, comparison points etc.
- **Interview videos** usually center on subjects discussed, areas of expertise etc.
- **News videos** commonly cover issues investigated, events covered, policy areas etc.
- **Lifestyle videos** often explore personal development areas, wellness practices, mindset concepts, etc.

**Guidelines:**
- Focus on **what the video is about**, not just passing mentions
- Use specific terms when they help: "gradient descent" not just "AI"
- Normalize names: "machine learning" not "Machine Learning 101"
- **prominence** (0.0-1.0): Share of video focus
  - 0.8-1.0: Primary/central topic
  - 0.5-0.7: Significant secondary topic
  - 0.2-0.4: Minor but meaningful topic
  - <0.2: Barely covered, omit

**Format:**
- `name`: Display-friendly format ("Pasta Making")
- `canonical_name`: lowercase, normalized, no special chars ("pasta making")

**Examples:**
```json
{{"name": "Machine Learning", "canonical_name": "machine learning", "prominence": 0.9}}
{{"name": "Gradient Descent", "canonical_name": "gradient descent", "prominence": 0.85}}
{{"name": "CSS Grid Layout", "canonical_name": "css grid layout", "prominence": 0.8}}
{{"name": "Pasta Making", "canonical_name": "pasta making", "prominence": 0.85}}
{{"name": "Low Light Photography", "canonical_name": "low light photography", "prominence": 0.8}}
{{"name": "Tokyo Street Food", "canonical_name": "tokyo street food", "prominence": 0.75}}
```

---

## 3. Entities (`entities`)

Entities are **specific instances central to the video** - such as particular people, organizations, products, places, theories/frameworks, events, or key concepts discussed.

**What you might find** (just examples to help guide your thinking):
- **Educational videos** often include tools, frameworks, instructors, historical figures, key things being worked with
- **Entertainment videos** might reference actors, characters, shows/movies, creators
- **Review videos** typically feature products/services being evaluated, competitor brands
- **Interview videos** usually include guests, their companies/projects, people they reference
- **News videos** commonly cover people involved in events, organizations being investigated
- **Lifestyle videos** might mention thought leaders, books/methods referenced, wellness brands

**importance** (0.0-1.0): How central is this entity to the video?
- 0.8-1.0: Main subject/focus of video
- 0.5-0.7: Frequently discussed, significant role
- 0.3-0.4: Mentioned multiple times with context
- <0.3: Brief mention, omit

**Format:**
```json
{{"name": "Gordon Ramsay", "canonical_name": "gordon ramsay", "importance": 0.9, "entity_type": "person"}}
{{"name": "iPhone 15", "canonical_name": "iphone 15", "importance": 0.7, "entity_type": "product"}}
{{"name": "Paris", "canonical_name": "paris", "importance": 0.5, "entity_type": "place"}}
{{"name": "OpenAI", "canonical_name": "openai", "importance": 0.8, "entity_type": "organization"}}
{{"name": "Python", "canonical_name": "python", "importance": 0.85, "entity_type": "programming language"}}
{{"name": "The Office", "canonical_name": "the office", "importance": 0.9, "entity_type": "tv show"}}
{{"name": "World War II", "canonical_name": "world war ii", "importance": 0.8, "entity_type": "event"}}
```

---

## 4. Tags (`tags`)

Searchable labels derived from topics, entities, and the video's overall content nature.

**Create a rich, multi-faceted tag set:** Think about how users might discover this content from different angles - include domain/field tags, format/style tags, and key characteristics. Balance broad discoverability with specific detail.

### A) From Topics (Generalize into broader categories)
- "gradient descent" → `machine-learning`, `optimization`, `math`
- "pasta making" → `cooking`, `italian-cuisine`, `culinary-skills`
- "mindfulness meditation" → `meditation`, `mindfulness`, `mental-health`, `wellness`

### B) From Entities (Extract categorical tags)
- "Gordon Ramsay" → `chef`, `celebrity`, `british`
- "TensorFlow" → `google`, `deep-learning`, `python`
- "iPhone 15" → `apple`, `smartphone`, `ios`

### C) From Video Nature (High-level categorization of what this video is)
Consider the video's format, type, and high-level categorization:
- Entertainment examples: `tv-show`, `sitcom`, `comedy`, `gaming`, `music-video`, `vlog`, `travel-vlog`
- Educational examples: `tutorial`, `course`, `how-to`, `explainer`
- Review examples: `tech-review`, `product-review`, `comparison`
- Other examples: `podcast`, `interview`, `documentary`, `news`

**Guidelines:**
- Use **lowercase, hyphenated** format (`machine-learning`, not `Machine Learning`)
- Be specific but searchable: `italian-cuisine` > `food` (but include both)
- Aim for **8-15 tags** total across all sources
- Balance specificity with discoverability
- **weight** (0.0-1.0): Relevance/confidence
  - 0.8-1.0: Core, highly relevant
  - 0.5-0.7: Secondary, useful
  - 0.3-0.4: Tertiary, might help discovery
  - <0.3: Omit

**Format:**
```json
{{"tag": "machine-learning", "weight": 0.95}}
{{"tag": "cooking", "weight": 0.9}}
{{"tag": "smartphone", "weight": 0.85}}
```

---

## 5. Language (`language`)

Detect the primary language of the transcript.

**Format:** ISO 639-1 code (`en`, `es`, `fr`, `de`, `ja`, `zh`, `pt`, `ru`, etc.)

---

## Output Format

Return **valid JSON only** (no markdown, no explanation).

**IMPORTANT:** Output `metadata` FIRST since content_type guides all other extraction.
```json
{{
  "metadata": {{
    "content_type": "educational|entertainment|review|interview|news|lifestyle|other",
    "language": "en"
  }},
  "short_summary": "2-4 sentences objectively describing what this video covers and its primary focus",
  "topics": [
    {{"name": "Display Name", "canonical_name": "lowercase normalized", "prominence": 0.0}}
  ],
  "entities": [
    {{"name": "Display Name", "canonical_name": "lowercase normalized", "importance": 0.0, "entity_type": "string"}}
  ],
  "tags": [
    {{"tag": "lowercase-hyphenated", "weight": 0.0}}
  ]
}}
```

---

## Example Output

**Input:** Video about making sourdough bread, featuring professional baker Sarah Johnson, discussing fermentation science and troubleshooting common issues.
```json
{{
  "metadata": {{
    "content_type": "educational",
    "language": "en"
  }},
  "short_summary": "Professional baker Sarah Johnson demonstrates the complete process of making sourdough bread from starter to final bake. The video covers fermentation science, dough hydration ratios, and shaping techniques.",
  "topics": [
    {{"name": "Sourdough Baking", "canonical_name": "sourdough baking", "prominence": 0.95}},
    {{"name": "Fermentation Science", "canonical_name": "fermentation science", "prominence": 0.6}},
    {{"name": "Bread Shaping", "canonical_name": "bread shaping", "prominence": 0.6}}
  ],
  "entities": [
    {{"name": "Sarah Johnson", "canonical_name": "sarah johnson", "importance": 0.8, "entity_type": "person"}},
    {{"name": "Sourdough Starter", "canonical_name": "sourdough starter", "importance": 0.5, "entity_type": "ingredient"}},
    {{"name": "Dough", "canonical_name": "dough", "importance": 0.65, "entity_type": "ingredient"}}
  ],
  "tags": [
    {{"tag": "baking", "weight": 0.95}},
    {{"tag": "sourdough", "weight": 0.95}},
    {{"tag": "bread", "weight": 0.9}},
    {{"tag": "fermentation", "weight": 0.7}},
    {{"tag": "cooking", "weight": 0.75}},
    {{"tag": "culinary-skills", "weight": 0.75}},
  ]
}}
```

---

## Now Process This Video

**Title:** {title.strip()}

**Description:** {description.strip()}

**Transcript:**
{transcript_text.strip()}

**End of Transcript**

**Remember:**
1. First, determine the content_type
2. Then extract topics, entities, tags, and summary with that context in mind
3. Return only the JSON output
"""