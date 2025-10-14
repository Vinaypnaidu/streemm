def _build_prompt(title: str, description: str, transcript_text: str) -> str:
    return f"""You are an expert video analyst extracting information for a video recommendation system that uses both keyword search (BM25) and semantic similarity (KNN).

VIDEO INPUT:
Title: {title.strip()}
Description: {description.strip()}
Transcript:
{transcript_text.strip()}

END OF TRANSCRIPT.

EXTRACTION STRATEGY:
Extract ONLY information that helps users discover similar or related videos. Think carefully about what makes THIS video unique and findable.

STEP 1: IDENTIFY THE VIDEO TYPE
First, determine what type of content this is using the categories and examples below.

VIDEO TYPE CLASSIFICATION & EXAMPLES:

1. ENTERTAINMENT - Content consumed primarily for enjoyment, storytelling, or artistic expression
   Examples: sitcoms, TV show clips, web series, short films, sketches, daily vlogs, travel vlogs, challenge videos, prank videos, let's plays, gameplay highlights, reaction videos, storytime videos, photography showcases, concert performances, artist documentaries

2. EDUCATIONAL - Teaching skills, explaining concepts, or providing how-to guidance
   Examples: coding tutorials, cooking recipes, makeup tutorials, fitness workouts, courses, lectures, DIY projects, repair guides, concept explainers, science explainers, language learning, instrument lessons, drawing tutorials, career advice, math lessons, gaming strategy guides

3. REVIEW - Evaluating, comparing, or showcasing products/services/media
   Examples: tech reviews, product reviews, unboxing videos, "X vs Y" comparisons, buying guides, software reviews, movie reviews, book reviews, game reviews, restaurant reviews, long-term reviews, shopping hauls with evaluations

4. INTERVIEW - Conversation-driven content with guests or subjects
   Examples: podcasts, video podcasts, one-on-one interviews, celebrity interviews, talk show clips, panel discussions, roundtables, AMAs, fireside chats, hot seat interviews

5. NEWS - Reporting on current events, investigating issues, or documenting reality
   Examples: breaking news, news updates, documentaries, mini-docs, investigative journalism, news commentary, event coverage, true crime documentaries, business case studies, explainer journalism, timeline videos

6. LIFESTYLE - Personal development, mindset, wellness, and life optimization
   Examples: motivational speeches, self-help content, productivity advice, habit building, transformation stories, morning routines (habit-focused), mental health content, meditation guides, philosophy videos, goal setting, relationship advice, fitness motivation stories

7. OTHER - Content that doesn't fit or has insufficient data
   Examples: music videos (pure music), ASMR videos, clip compilations without narrative, silent films, pure B-roll, corrupted transcripts, abstract/experimental videos, unedited live streams

GREY AREA DECISION GUIDE:
Some content types can be tricky to classify. Here are some common patterns to help guide your thinking, but use your judgment based on the video's primary purpose:

- Gaming content: Tutorials/strategy guides often work as educational, entertainment gameplay as entertainment, game reviews as review
- Fitness content: Structured workout tutorials often work as educational, motivation/transformation stories as lifestyle  
- Cooking content: Recipe tutorials often work as educational, restaurant reviews as review, cooking vlogs as entertainment
- Music content: Production tutorials often work as educational, concerts/performances as entertainment, pure music videos as other
- Solo Q&A: Teaching/advice-focused often works as educational, personal life/mindset as lifestyle, casual chat as entertainment

When content blends multiple types, choose based on what the creator's main intent seems to be and what would help users discover similar content.

STEP 2: EXTRACT BASED ON VIDEO TYPE
Once you've identified the type, here are example extraction patterns to guide you. Adapt these based on what would help users find similar videos.

EXAMPLE EXTRACTION PATTERNS BY TYPE:

1. ENTERTAINMENT
   PRIORITY: entities (CRITICAL) > topics (LOW - sparse)
   
   TOPIC EXTRACTION GUIDANCE FOR ENTERTAINMENT:
   Topics typically answer: "What type/genre/style of entertainment is this?"
   Generally extract 1-3 broad categorization tags. Mix high-level (e.g., "comedy", "music", "gaming") with slightly more specific style/genre tags (e.g., "indie rock", "battle royale") when helpful for discovery. Using both levels together when possible (e.g., "music" + "indie rock") creates stronger search signals.
   Entities carry most of the specificity, so keep topics focused on categorization rather than unique details. 
   
   Entertainment is diverse - here are some example patterns to guide you. There could be more, so decide accordingly what to extract:
   
   A) NARRATIVE CONTENT (sitcoms, series, short films, vlogs):
      Typically helpful: Show/series name and main characters (entities) + broad genre/format (topics)
      Less useful: Very specific plot elements or overly specific details that don't help categorize
      
      EXTRACT entities: Characters, show names, locations featured, channel names (3-8 typical)
         Examples: "michael scott", "stranger things", "dwight schrute", "the office"
      
      EXTRACT topics: Usually broad genre/format/style tags (2-5 topics typical)
         Examples: "comedy", "sitcom", "workplace comedy", "horror series", "travel vlog", "daily vlog"
   
   B) GAMING CONTENT (let's plays, gameplay, gaming commentary):
      Typically helpful: Game title (entity) is primary + gameplay genre/style (topics) adds context
      Less useful: Specific level names, mission numbers, or momentary gameplay events

      EXTRACT entities: Game titles, characters, streamers, gaming channels (1-6 typical)
         Examples: "minecraft", "call of duty warzone", "pewdiepie", "valorant"
      
      EXTRACT topics: Often includes "gaming" + specific genre or gameplay style (1-4 topics typical)
         Examples: "gaming", "survival horror", "battle royale", "speedrunning", "fighting games"
   
   C) REACTION & COMMENTARY (reactions, commentary videos):
      Typically helpful: What's being reacted to (entity) + type of analysis if it's a defining focus
      Less useful: Specific quotes, timestamps, or personal opinions expressed in the reaction

      EXTRACT entities: Content being reacted to, creators reacting, original creators (1-6 typical)
         Examples: "game of thrones finale", "super bowl halftime show", "kendrick lamar"
      
      EXTRACT topics: Type/style of commentary when it defines the video (1-4 topics typical)
         Examples: "reaction content", "music analysis", "film critique", "sports commentary", "movie review"
   
   D) PERFORMANCE & MUSIC (concerts, behind-the-scenes, artist content):
      Typically helpful: Artist/song name (entity) + "music" + genre when relevant creates strong signals
      Less useful: Specific lyrics, setlist order, or crowd reaction details

      EXTRACT entities: Artists, bands, song titles, venues, tour names (1-6 typical)
         Examples: "taylor swift", "eras tour", "anti-hero song", "coachella", "billie eilish"
      
      EXTRACT topics: Often includes "music" + genre or performance type (1-4 topics typical)
         Examples: "music", "pop music", "indie rock", "live concert", "acoustic performance", "jazz improvisation"

2. EDUCATIONAL
   PRIORITY: topics (CRITICAL) > entities (MODERATE)
   
   TOPIC EXTRACTION GUIDANCE FOR EDUCATIONAL:
   Topics are the primary search mechanism for educational content. Extract broader subject areas AND more specific topics when relevant.
   Match topic specificity to the video's scope and essence: a general "Introduction to Programming" course gets broader topics like "programming" and "computer science", while a focused "CSS Flexbox Layout Guide" gets slightly more specific topics like "css", "web development", and "layout design".
   Generally extract 3-8 topics. Focus on what's actually being taught, not just mentioned.
   
   Educational content focuses on teaching - here are some example patterns to guide you. There could be more, so decide accordingly what to extract:
   
   A) TECHNICAL TUTORIALS (coding, software, tech skills):
      Typically helpful: Domains and concepts (topics) + specific tools/frameworks (entities)
      Less useful: Specific code snippets, variable names, or function names from examples
      Entity guidance: Focus on tools/frameworks that are central to what's being taught.
      
      EXTRACT entities: Languages, frameworks, tools, IDEs, libraries that are prominently featured in the video (2-6 typical)
         Examples: "python", "react", "visual studio code", "pandas library", "postgresql", "figma"
      
      EXTRACT topics: Technical domains, programming concepts, skill areas (3-8 topics typical)
         Examples: "programming", "web development", "javascript", "data science", "machine learning", "graphic design", "version control", "database management"
   
   B) CREATIVE & PRACTICAL SKILLS (art, cooking, fitness, DIY):
      Typically helpful: Skill domains and techniques (topics) + tools/materials that are central to instruction (entities)
      Less useful: Specific measurements, ingredient quantities, or step numbers
      Entity guidance: Focus on tools/equipment that are prominently featured or central to what's being taught. For example: including "instant pot" is helpful in "Beginner's guide to Instant Pot cooking" since it is highly relevant to the video, while basic cookware in recipe videos is typically less useful.
      
      EXTRACT entities: Tools, equipment, materials, things that are prominently featured in the video (2-6 typical)
         Examples: "air fryer", "instant pot", "watercolor paints", "procreate app", "resistance bands", "kettlebell"
      
      EXTRACT topics: Craft domains, techniques, skill categories (3-8 topics typical)
         Examples: "cooking", "italian cuisine", "baking", "painting", "portrait drawing", "digital art", "fitness", "weight training", "yoga", "woodworking", "furniture building", "home renovation"
   
   C) ACADEMIC & PROFESSIONAL (courses, lectures, career advice):
      Typically helpful: Academic/professional fields and concepts (topics) + frameworks/resources that are featured (entities)
      Less useful: Specific lecture numbers, assignment names, or chapter titles
      Entity guidance: Focus on frameworks, books, or platforms that are specifically being taught, reviewed, or recommended - not just casually mentioned in passing.
      
      EXTRACT entities: Frameworks, methodologies, books, certifications, platforms that are prominently featured in the video (2-6 typical)
         Examples: "atomic habits book", "coursera", "aws certification"
      
      EXTRACT topics: Academic fields, professional domains, skill areas (3-8 topics typical)
         Examples: "mathematics", "algebra", "physics", "biology", "world history", "economics", "business management", "leadership skills", "public speaking", "financial planning", "resume writing"

3. REVIEW
   PRIORITY: entities (CRITICAL) > topics (MODERATE)
   
   TOPIC EXTRACTION GUIDANCE FOR REVIEW:
   Topics typically capture product categories, features being evaluated, or use cases discussed - but entities (the actual products) are the primary search mechanism.
   
   Typically helpful: Specific products being reviewed (entities) + product categories and features (topics)
   Less useful: Specific prices, timestamps, or minor spec details

   EXTRACT entities: Specific products with models, brands, software names that are being reviewed in the video (2-8 typical)
      Examples: "iphone 15 pro max", "airpods pro gen 2", "notion app", "m3 macbook pro", "tesla model 3"
   
   EXTRACT topics: Product categories, features being evaluated, or use cases (2-6 topics typical)
      Examples: "smartphone photography", "noise cancellation", "productivity software", "electric vehicles", "wireless earbuds", "budget laptops"

4. INTERVIEW
   PRIORITY: entities & topics (both CRITICAL)
   
   TOPIC EXTRACTION GUIDANCE FOR INTERVIEW:
   Topics capture the major discussion themes and subject areas that get meaningful exploration during the conversation.
   Balance broad themes with specific topics when they receive substantial discussion time. For example: a space podcast might extract both "space exploration" and "black holes" if black holes are discussed in depth.
   Generally extract 3-8 topics based on the depth and breadth of conversation.
   
   Typically helpful: People and organizations involved (entities) + discussion themes and subject areas (topics)
   Less useful: Specific anecdotes, personal stories, or tangential mentions

   EXTRACT entities: Full names of guests, hosts, companies, organizations, projects mentioned (3-8 typical)
      Examples: "lex fridman", "sam altman", "openai", "y combinator", "tesla", "spacex"
   
   EXTRACT topics: Discussion themes - both broad subjects and specific subject areas explored (3-8 topics typical)
      Examples: "artificial intelligence", "machine learning", "entrepreneurship", "venture capital", "space exploration", "black holes", "mental health", "cognitive behavioral therapy", "climate change", "solar energy"

5. NEWS
   PRIORITY: entities (CRITICAL) > topics (MODERATE)
   
   TOPIC EXTRACTION GUIDANCE FOR NEWS:
   Topics help categorize the type of news story and the broader issues being covered - think news categories and policy areas rather than specific incident details.
   Balance story types with issue domains. For example: a banking collapse story might extract both "financial crisis" and "banking regulation" to capture different search angles.
   Generally extract 3-8 topics based on the scope of coverage.
   
   Typically helpful: Specific people, places, organizations, and events (entities) + news categories and issue areas (topics)
   Less useful: Specific dates, times, minor witnesses, or tangential details

   EXTRACT entities: People, organizations, locations, specific events/incidents covered in the video (3-8 typical)
      Examples: "silicon valley bank", "sam bankman-fried", "spacex starship", "chatgpt", "federal reserve"
   
   EXTRACT topics: News categories, issue areas, policy domains, phenomena covered (3-8 topics typical)
      Examples: "financial crisis", "banking regulation", "cryptocurrency", "space exploration", "artificial intelligence", "tech industry", "nuclear safety", "climate policy", "healthcare reform", "election coverage"

6. LIFESTYLE
   PRIORITY: entities & topics (both CRITICAL)
   
   TOPIC EXTRACTION GUIDANCE FOR LIFESTYLE:
   Topics capture life domains, philosophical approaches, wellness categories, and self-improvement areas that help users find content in similar personal development niches.
   Balance broad life areas with specific practices or frameworks that receive meaningful coverage. For example: a productivity video might extract both "productivity" and "time management" when time management is a key focus.
   Generally extract 2-5 topics and 2-5 entities based on what's prominently featured.
   
   Lifestyle focuses on personal development - here are some example patterns to guide you. There could be more, so decide accordingly what to extract:
   
   A) MOTIVATIONAL & MINDSET (speeches, success stories):
      Typically helpful: Speakers and programs featured (entities) + philosophical frameworks and life domains (topics)
      Less useful: Specific daily routine timestamps, personal anecdotes, or motivational quotes

      EXTRACT entities: Speakers, books referenced, specific programs/challenges featured in the video (2-6 typical)
         Examples: "david goggins", "atomic habits book", "75 hard program", "tony robbins", "jocko willink"
      
      EXTRACT topics: Mental frameworks, philosophical approaches, life domains (2-6 topics typical)
         Examples: "personal development", "mental toughness", "discipline", "stoicism", "habit formation", "morning routines", "goal setting", "resilience"
   
   B) WELLNESS & SELF-HELP (meditation, productivity, personal growth):
      Typically helpful: Methods, teachers, and resources (entities) + wellness categories and optimization areas (topics)
      Less useful: Specific meditation durations, routine step numbers, or app feature lists

      EXTRACT entities: Methods, teachers, books, apps, programs featured in the video (2-6 typical)
         Examples: "wim hof method", "headspace app", "getting things done book", "tim ferriss", "james clear"
      
      EXTRACT topics: Wellness practices, productivity systems, self-optimization areas (2-6 topics typical)
         Examples: "meditation", "mindfulness", "breathwork", "productivity", "time management", "habit building", "sleep optimization", "stress management", "digital minimalism"

7. OTHER
   PRIORITY: Minimal extraction - use title/description only
   
   CONTENT GUIDANCE FOR OTHER:
   This category is for content that doesn't fit other types or lacks sufficient information for proper extraction. Common examples include pure music videos, ASMR, ambient content, or videos with corrupted/missing transcripts.
   Extract very minimally (1-3 items total) based only on title and description since the content itself doesn't provide extractable structure.
   
   Typically helpful: Basic categorization or artist/content identification when clearly evident
   
   EXTRACT entities: Only if clearly identifiable from title/description (0-3 typical)
      Examples: "hans zimmer" (for a music video), "lofi girl" (for ambient streams)
   
   EXTRACT topics: Only basic genre or content type tags (0-3 typical)
      Examples: "music video", "asmr", "ambient music", "nature sounds", "white noise"
   
   Note: Always mention in your reasoning that extraction is limited due to insufficient content structure.

SCORING GUIDANCE:
Rate prominence/importance (0.0-1.0) based on: "Would someone searching for X want to find THIS video?"
  
  0.8-1.0: CENTRAL to the video's value/identity
    Main character in sitcom, primary tool in tutorial, product being reviewed, interview guest
  
  0.5-0.7: SIGNIFICANT but not the main draw
    Recurring side character, important sub-topic, competing product mentioned, co-host
  
  0.3-0.4: MEANINGFUL but brief
    One-time appearance, example to illustrate concept, background location, referenced work
  
  Below 0.3: DON'T EXTRACT - creates noise
    Passing mentions, generic tools, meta-references

CANONICAL NAMING:
- Use widely recognized forms: "react" not "React.js"
- People: "firstname lastname" lowercase: "elon musk"
- Products: include identifiers: "iphone 15 pro" not "iphone"
- Concepts: industry-standard terms: "machine learning" not "ML"
- De-duplicate: keep one canonical form per concept

ENTITY TYPE CLASSIFICATION:
For better semantic search, classify each entity by type. Here are some examples (there could be more, use your judgment):

- person: individuals, celebrities, hosts, guests, speakers
  Examples: "elon musk", "joe rogan", "serena williams"

- product: specific products, gadgets, devices with models
  Examples: "iphone 15 pro", "airpods pro", "macbook air"

- tool: software, apps, platforms, instruments, equipment
  Examples: "photoshop", "excel", "github", "blender"

- framework: programming frameworks, methodologies, systems, APIs
  Examples: "react", "django", "tensorflow", "kubernetes"

- organization: companies, institutions, groups, channels
  Examples: "google", "nasa", "united nations", "red cross"

- location: places, venues, cities, landmarks, geographical locations
  Examples: "new york city", "grand canyon", "eiffel tower", "tokyo"

- book: books, publications, written works
  Examples: "sapiens", "thinking fast and slow", "the lean startup"

- method: specific techniques, programs, challenges, named approaches
  Examples: "pomodoro technique", "intermittent fasting", "agile methodology"

- show: TV shows, series, web series, programs
  Examples: "breaking bad", "the office", "stranger things"

- game: video games, board games
  Examples: "minecraft", "fortnite", "chess", "pokemon"

- song: songs, albums, music tracks
  Examples: "bohemian rhapsody", "thriller album", "shape of you"

- event: specific events, tours, conferences, incidents, launches
  Examples: "world cup 2022", "apple keynote", "olympics", "tech crunch disrupt"

- other: for entities that are not specific enough or you are not sure about

OUTPUT FORMAT (JSON only, no extra text):
{{
  "content_analysis": {{
    "primary_type": "entertainment|educational|review|interview|news|lifestyle|other",
    "secondary_type": "optional subtype or blend description",
    "reasoning": "1-2 sentences: WHY you classified it this way AND what extraction strategy you'll use"
  }},
  "short_summary": "2-4 sentences objectively describing what this video covers and its primary focus",
  "topics": [
    {{"name": "Display Name", "canonical_name": "lowercase normalized", "prominence": 0.0-1.0}}
  ],
  "entities": [
    {{"name": "Display Name", "canonical_name": "lowercase normalized", "importance": 0.0-1.0, "entity_type": ""}}
  ],
  "metadata": {{
    "content_type": "entertainment|educational|review|interview|news|lifestyle|other",
    "language": "detected language code"
  }}
}}

CRITICAL RULES:
- Follow PRIORITY guidance for each type - extract more of what matters most
- Every extraction must help find similar videos
- When in doubt, extract LESS not more - noise is worse than missing info (like generic stuff is not useful)
- When extracting topics, think about search behavior: use common terms that people would actually search for to find this type of content. Topics should be general or moderately specific based on what's helpful for discovery or grouping similar videos - not ultra-specific stuff.
- JSON only response, no markdown, no explanations outside JSON

BEFORE YOU START:
Your goal is to extract ONLY information that helps users discover similar or related videos. Think carefully about what makes THIS video unique and findable. 
"""