"""Prompt templates for the content scraper."""

# Template for content classification
CLASSIFIER_PROMPT = '''You are a highly accurate content classifier for a sophisticated news aggregation service. Your task is to analyze and classify articles into one of the following distinct categories:

- **city**: Articles that focus on local news specific to a city. Ensure to include both the city and its state/province/region in the `city_slug` field. For example, use "Seattle, WA" instead of just "Seattle", or "London, UK" instead of just "London".
- **global**: Articles that cover international or national news, not limited to a specific city or region.
- **industry**: Articles that pertain to a specific industry or business sector. Identify and specify the industry sector in the `industry_slug` field.
- **trash**: Content that is not a news article, such as spam or irrelevant material.

**URL ANALYSIS**: Pay special attention to URL patterns that indicate non-news content:
- Job sites (jobs., /careers/, /employment/)
- Advertising pages (/advertising/, /ads/, /promote/)
- About/contact pages (/about/, /contact/, /team/)
- Service pages (/services/, /products/, /pricing/)
- User-generated content (/user/, /profile/, /account/)
- File downloads (/download/, .pdf, .doc)
- These should typically be classified as "trash"

Your response must be in JSON format, strictly adhering to the following structure:
```json
{{
  "label": "city|global|industry|trash",
  "city_slug": "Seattle, WA", // Only for city articles - ALWAYS include state/province
  "industry_slug": "fintech" // Only for industry articles
}}
```

Please classify the following article based on its URL, title, and content:

**URL**: {url}

**Title**: {title}

**Content**: {text}
'''

# Template for global/industry articles
GLOBAL_INDUSTRY_PROMPT = '''Analyze the following news article content and its metadata:

CONTENT:
   ${markdown.substring(0, 4000)}

METADATA:
   ${metadataString}

   # Requirements for every summary written
## GLOBAL STYLE RULES
    1. **Wire‑service voice** (AP/Reuters): concise, neutral, instantly scannable yet authoritative.  
2. **Lead with the single most news‑worthy fact** in ≤ 20 words, plain Subject‑Verb order.  
    *Ex:* "Seattle voters approved a new transit tax Tuesday."  
    3. **Active voice only.** Ban "is being," "has been," "there is/are," unless inside a quotation.  
    4. **Never open with meta‑phrases** ("This article…," "According to…," "Overall," etc.).  
    5. **Include one vivid hard detail** (statistic, dollar figure, or short, clearly attributed quote) *when supplied by the article*.  
6. **Keyword discipline:** weave ≤ 3 natural high‑value search terms; **never repeat** a term.  
7. **Sentence music:** vary length (10‑25 words), mix simple and compound, aim for Flesch Reading Ease ≈ 80.  
    8. **Trim filler adverbs** ("very," "extremely," "significantly") unless inside a quote.  
    9. **Concrete content only:** every sentence must convey a distinct fact, action, quote, or data point—**no meta‑commentary** (e.g., "This response highlights…," "The move underscores…").  
    10. **Tasteful echo for emphasis** is allowed ("The ruling is narrow—narrow by design.") but avoid formulaic patterns.  
    11. **Capture legal/procedural pivots** (e.g., a court labeling a measure "administrative") in *at least one* sentence.  
12. **Conflict → action → next‑step:** whenever officials pledge a response, state *what* they will do and *why* it matters.  
    13. **No sentence may be copied verbatim** from the source; paraphrase unless quoting.  
    14. **Avoid near‑duplicate wording across tiers;** each tier should feel like a logical expansion.  
15. **Optional context line** (1 sentence) may link the story to broader policy/history if it truly aids understanding.

    ## TIER PROGRESSION
    * **2–3‑sentence summary:** strict brief; covers the "who‑what‑when‑where" plus one clear "so‑what."  

    ## DELIVERABLE FIELDS (KEEP EXACT ORDER & HEADINGS)
    1. **Score:** 0–100 (apply rubric below).  
    2. **Summary (2‑3 sentences):** wire‑service brief obeying all style rules.  
    3. **Title:** This is CRITICALLY IMPORTANT. Extract the article's original title. Use the article's headline; if absent, craft a concise, descriptive, SEO‑friendly title (no generic fillers).  Never use generic titles like "News article from [date]." Never use any AI filler titles.
4. **Topic:** choose **one** — Government | Finance | Sports | Local News (prefer "Local News" if city/region is materially affected).  
5. **Date:** CRITICAL PUBLICATION DATE EXTRACTION. This is one of the most important fields. Follow this exact process:
   
   **STEP 1 - METADATA ANALYSIS:** First examine the metadata for publication date fields:
   - Look for: 'date', 'article:published_time', 'og:published_time', 'pubdate', 'published', 'datePublished'
   - These often contain the most reliable publication dates
   
   **STEP 2 - CONTENT ANALYSIS:** If metadata lacks clear dates, analyze the article content:
   - Search for publication indicators: "Published:", "Posted:", "Date:", timestamps near headlines
   - Check bylines (author sections) for publication dates
   - Look for datelines at article start (e.g., "SEATTLE, Dec 15 -")
   - Find timestamps in HTML elements or structured data
   
   **STEP 3 - RELATIVE DATE CONVERSION:** Handle relative dates:
   - "2 hours ago" → Calculate actual date/time
   - "yesterday" → Previous calendar day
   - "today" → Current date
   - Days of week → Convert to actual dates
   
   **STEP 4 - DATE PRIORITIZATION:** If multiple dates found:
   - Publication date > Event date
   - Earlier timestamps near headline > later timestamps in content
   - Structured metadata > plain text mentions
   
   **STEP 5 - FORMAT RESPONSE:** 
   - Return the exact date string as found (don't reformat)
   - If no publication date found after exhaustive search: "Date not found"
   - Every news article HAS a publication date - search thoroughly
   
6. **New Main Topic:** choose **one** — Politics, Government, Business, Economy, Technology, Science, Health, Environment, Education, Sports, Arts, Entertainment, International Affairs, Crime, Social Issues, Culture, Transportation, Infrastructure, Religion, Agriculture, Food.
    7. **Subtopics:** Generate 2 relevant subtopics that reflect the specific focus of the article. These subtopics do not need to fit the predefined list but should represent key themes, events, or issues mentioned in the article.

    ### RUBRIC
    1. **Industry or World Relevance (25)** – industry/world impact (0‑15); local voices/data (0‑10)  
2. **Importance & Impact (20)** – magnitude (0‑10); longevity (0‑5); policy/behavior change (0‑5)  
3. **Newsworthiness & Timeliness (15)** – recency (0‑8); urgency/follow‑up (0‑4); novelty (0‑3)  
4. **Credibility & Sourcing (15)** – named sources (0‑6); verifiable data (0‑5); diversity (0‑4)  
5. **Clarity & Quality (15)** – logical flow (0‑6); grammar (0‑4); visual aids if present (0‑3); engaging lead (0‑2)  
6. **Bias, Balance & Tone (10)** – fairness (0‑5); neutral language (0‑3); fact/opinion separation (0‑2)

    ### BANNED‑WORD LIST
    this article, the article, the text, the piece, overall, in conclusion, to conclude,  
    in summary, summarizing, according to the article, according to the text, describes,  
    discusses, explains that, it can be seen that, it is clear that, indeed, moreover,  
    furthermore, additionally, very, extremely, significantly, really, basically,  
    interestingly, importantly, needless to say

    ### PREFERRED VERB STARTERS
    announces, approves, arrests, awards, bans, bars, cancels, charges, cites, clears,  
    confirms, condemns, delays, denies, enacts, files, grants, halts, implements,  
    imposes, indicts, launches, lifts, limits, moves, orders, passes, plans, pledges,  
    proposes, ratifies, rejects, releases, renews, rescinds, reveals, seeks, settles,  
    signs, stiffens, sues, suspends, targets, unveils, upholds, warns, wins, withdraws

    ### RESPONSE FORMAT (EXACTLY)
    Respond with a JSON object containing the following fields:
    ```json
    {
      "score": "Your score from 0-100 based on rubric",  // 0-100 based on rubric
      "short_summary": "your 2-3 sentence summary",
      "title": "the article title or your created title",
  "topic": "Government | Finance | Sports | Local News",
  "date": "Exact date string as found or Date not found",
      "main_topic": "Selected new main topic from the new main topic list",
      "subtopics": ["Subtopic 1", "Subtopic 2"],
    }
    ```

*If any element is genuinely indeterminable, supply a best‑guess placeholder—except "Date," which must be the exact string found or "Date not found" if missing. Always include a Title.*
'''

# Template for city articles
CITY_PROMPT = '''Analyze the following news article content and its metadata:

CONTENT:
   ${markdown.substring(0, 4000)}

METADATA:
   ${metadataString}

   # Requirements for every summary written
## GLOBAL STYLE RULES
    1. **Wire‑service voice** (AP/Reuters): concise, neutral, instantly scannable yet authoritative.  
2. **Lead with the single most news‑worthy fact** in ≤ 20 words, plain Subject‑Verb order.  
    *Ex:* "Seattle voters approved a new transit tax Tuesday."  
    3. **Active voice only.** Ban "is being," "has been," "there is/are," unless inside a quotation.  
    4. **Never open with meta‑phrases** ("This article…," "According to…," "Overall," etc.).  
    5. **Include one vivid hard detail** (statistic, dollar figure, or short, clearly attributed quote) *when supplied by the article*.  
6. **Keyword discipline:** weave ≤ 3 natural high‑value search terms; **never repeat** a term.  
7. **Sentence music:** vary length (10‑25 words), mix simple and compound, aim for Flesch Reading Ease ≈ 80.  
    8. **Trim filler adverbs** ("very," "extremely," "significantly") unless inside a quote.  
    9. **Concrete content only:** every sentence must convey a distinct fact, action, quote, or data point—**no meta‑commentary** (e.g., "This response highlights…," "The move underscores…").  
    10. **Tasteful echo for emphasis** is allowed ("The ruling is narrow—narrow by design.") but avoid formulaic patterns.  
    11. **Capture legal/procedural pivots** (e.g., a court labeling a measure "administrative") in *at least one* sentence.  
12. **Conflict → action → next‑step:** whenever officials pledge a response, state *what* they will do and *why* it matters.  
    13. **No sentence may be copied verbatim** from the source; paraphrase unless quoting.  
    14. **Avoid near‑duplicate wording across tiers;** each tier should feel like a logical expansion.  
15. **Optional context line** (1 sentence) may link the story to broader policy/history if it truly aids understanding.

    ## TIER PROGRESSION
    * **2–3‑sentence summary:** strict brief; covers the "who‑what‑when‑where" plus one clear "so‑what."  
    * **6‑sentence summary:** must add **new** concrete facts or one brief attributed quote **and** one clause explaining local significance. No generic commentary.  
    * **8‑sentence summary:** expand the 6‑sentence version with **two** fresh lines:  
    – (a) authoritative background (historical, policy, or financial)  
    – (b) **one** additional hard detail (data point **or** short quote).  
    *Both added lines must present tangible information, never filler.*

    ## DELIVERABLE FIELDS (KEEP EXACT ORDER & HEADINGS)
    1. **Score:** 0–100 (apply rubric below).  
    2. **Summary (2‑3 sentences):** wire‑service brief obeying all style rules.  
    3. **Summary (6 sentences):** newsletter brief meeting Tier rules above.  
    4. **Summary (8 sentences):** mini‑feature meeting Tier rules above.  
    5. **Title:** This is CRITICALLY IMPORTANT. Extract the article's original title. Use the article's headline; if absent, craft a concise, descriptive, SEO‑friendly title (no generic fillers).  Never use generic titles like "News article from [date]." Never use any AI filler titles.
6. **Topic:** choose **one** — Government | Finance | Sports | Local News (prefer "Local News" if city/region is materially affected).  
7. **Date:** CRITICAL PUBLICATION DATE EXTRACTION. This is one of the most important fields. Follow this exact process:
   
   **STEP 1 - METADATA ANALYSIS:** First examine the metadata for publication date fields:
   - Look for: 'date', 'article:published_time', 'og:published_time', 'pubdate', 'published', 'datePublished'
   - These often contain the most reliable publication dates
   
   **STEP 2 - CONTENT ANALYSIS:** If metadata lacks clear dates, analyze the article content:
   - Search for publication indicators: "Published:", "Posted:", "Date:", timestamps near headlines
   - Check bylines (author sections) for publication dates
   - Look for datelines at article start (e.g., "SEATTLE, Dec 15 -")
   - Find timestamps in HTML elements or structured data
   
   **STEP 3 - RELATIVE DATE CONVERSION:** Handle relative dates:
   - "2 hours ago" → Calculate actual date/time
   - "yesterday" → Previous calendar day
   - "today" → Current date
   - Days of week → Convert to actual dates
   
   **STEP 4 - DATE PRIORITIZATION:** If multiple dates found:
   - Publication date > Event date
   - Earlier timestamps near headline > later timestamps in content
   - Structured metadata > plain text mentions
   
   **STEP 5 - FORMAT RESPONSE:** 
   - Return the exact date string as found (don't reformat)
   - If no publication date found after exhaustive search: "Date not found"
   - Every news article HAS a publication date - search thoroughly
   
8. **New Main Topic:** choose **one** — Politics, Government, Business, Economy, Technology, Science, Health, Environment, Education, Sports, Arts, Entertainment, International Affairs, Crime, Social Issues, Culture, Transportation, Infrastructure, Religion, Agriculture, Food.
    9. **Subtopics:** Generate 2 relevant subtopics that reflect the specific focus of the article. These subtopics do not need to fit the predefined list but should represent key themes, events, or issues mentioned in the article.

    ### RUBRIC
    1. **Local Relevance (25)** – city/region impact (0‑15); local voices/data (0‑10)  
2. **Importance & Impact (20)** – magnitude (0‑10); longevity (0‑5); policy/behavior change (0‑5)  
3. **Newsworthiness & Timeliness (15)** – recency (0‑8); urgency/follow‑up (0‑4); novelty (0‑3)  
4. **Credibility & Sourcing (15)** – named sources (0‑6); verifiable data (0‑5); diversity (0‑4)  
5. **Clarity & Quality (15)** – logical flow (0‑6); grammar (0‑4); visual aids if present (0‑3); engaging lead (0‑2)  
6. **Bias, Balance & Tone (10)** – fairness (0‑5); neutral language (0‑3); fact/opinion separation (0‑2)

    ### BANNED‑WORD LIST
    this article, the article, the text, the piece, overall, in conclusion, to conclude,  
    in summary, summarizing, according to the article, according to the text, describes,  
    discusses, explains that, it can be seen that, it is clear that, indeed, moreover,  
    furthermore, additionally, very, extremely, significantly, really, basically,  
    interestingly, importantly, needless to say

    ### PREFERRED VERB STARTERS
    announces, approves, arrests, awards, bans, bars, cancels, charges, cites, clears,  
    confirms, condemns, delays, denies, enacts, files, grants, halts, implements,  
    imposes, indicts, launches, lifts, limits, moves, orders, passes, plans, pledges,  
    proposes, ratifies, rejects, releases, renews, rescinds, reveals, seeks, settles,  
    signs, stiffens, sues, suspends, targets, unveils, upholds, warns, wins, withdraws

    ### RESPONSE FORMAT (EXACTLY)
    Respond with a JSON object containing the following fields:
    ```json
    {
      "score": "Your score from 0-100 based on rubric",  // 0-100 based on rubric
      "short_summary": "your 2-3 sentence summary",
      "medium_summary": "your 6-sentence summary",
      "long_summary": "your 8-sentence summary",
      "title": "the article title or your created title",
  "topic": "Government | Finance | Sports | Local News",
  "date": "Exact date string as found or Date not found",
      "main_topic": "Selected new main topic from the new main topic list",
      "subtopics": ["Subtopic 1", "Subtopic 2"],
    }
    ```

*If any element is genuinely indeterminable, supply a best‑guess placeholder—except "Date," which must be the exact string found or "Date not found" if missing. Always include a Title.*
'''
