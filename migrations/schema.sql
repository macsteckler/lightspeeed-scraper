-- A. Articles table (single bucket)
CREATE TABLE IF NOT EXISTS public.news_articles (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  url              TEXT UNIQUE NOT NULL,
  url_canonical    TEXT UNIQUE NOT NULL,
  title            TEXT,
  summary_short    TEXT,
  summary_medium   TEXT,
  summary_long     TEXT,
  audience_scope   TEXT NOT NULL,  -- '[city:seattle]' | '[global]' | '[industry:fintech]'
  date_posted      TIMESTAMPTZ,
  is_embedded      BOOLEAN DEFAULT FALSE,
  vector_id        TEXT,
  created_at       TIMESTAMPTZ DEFAULT now()
);

-- B. Heavy-dedupe registry
CREATE TABLE IF NOT EXISTS public.processed_urls (
  url           TEXT PRIMARY KEY,
  status        TEXT,                   -- 'trash' | 'processed'
  processed_at  TIMESTAMPTZ DEFAULT now()
);

-- C. Simple job queue (Supabase only, no Redis)
CREATE TABLE IF NOT EXISTS public.scrape_jobs (
  id            BIGSERIAL PRIMARY KEY,
  job_type      TEXT NOT NULL,          -- 'article' | 'source' | 'batch'
  payload       JSONB NOT NULL,
  status        TEXT DEFAULT 'queued',  -- 'queued' | 'in_progress' | 'done' | 'error'
  error_message TEXT,
  links_found   INTEGER,
  links_skipped INTEGER,
  articles_saved INTEGER,
  errors        INTEGER,
  created_at    TIMESTAMPTZ DEFAULT now(),
  updated_at    TIMESTAMPTZ DEFAULT now()
);

-- D. Prompt storage (already provided according to PRD)
CREATE TABLE IF NOT EXISTS public.scraper_prompts (
  id           SERIAL PRIMARY KEY,
  prompt       TEXT NOT NULL,
  description  TEXT NOT NULL UNIQUE,
  model        TEXT,
  created_at   TIMESTAMPTZ DEFAULT now(),
  updated_at   TIMESTAMPTZ DEFAULT now()
);

-- Create indexes
CREATE UNIQUE INDEX IF NOT EXISTS idx_news_articles_canon ON public.news_articles(url_canonical);
CREATE INDEX IF NOT EXISTS idx_scrape_jobs_status ON public.scrape_jobs(status);

-- Helper function for worker to claim jobs
CREATE OR REPLACE FUNCTION public.claim_job()
RETURNS TABLE (id BIGINT, job_type TEXT, payload JSONB) AS $$
BEGIN
  RETURN QUERY
  UPDATE public.scrape_jobs
  SET status = 'in_progress', updated_at = now()
  WHERE id = (
    SELECT id FROM public.scrape_jobs
    WHERE status = 'queued'
    ORDER BY id
    LIMIT 1
    FOR UPDATE SKIP LOCKED
  )
  RETURNING id, job_type, payload;
END;
$$ LANGUAGE plpgsql;

-- Insert default prompts
INSERT INTO public.scraper_prompts (prompt, description, model)
VALUES (
  'You are a content classifier for a news aggregation service. 
  
  Classify the following article into one of these categories:
  - city: Local news about a specific city
  - global: International or national news
  - industry: News about a specific industry or business sector
  - trash: Not a news article, spam, or irrelevant content
  
  For city articles, always include both the city AND state/province/region in the city_slug field.
  For example, use "Seattle, WA" instead of just "Seattle", or "London, UK" instead of just "London".
  
  For industry, identify the specific industry sector.
  
  Respond with JSON only, in this format:
  {
    "label": "city|global|industry|trash",
    "city_slug": "Seattle, WA", // Only for city articles - ALWAYS include state/province
    "industry_slug": "fintech" // Only for industry articles
  }
  
  Article to classify:
  Title: {title}
  
  Content: {text}',
  'classifier',
  'gpt-4o-mini'
)
ON CONFLICT (description) DO NOTHING;

INSERT INTO public.scraper_prompts (prompt, description, model)
VALUES (
  'Analyze the following news article in markdown format and its metadata:
   Markdown Content:
   ${markdown.substring(0, 4000)}
   Metadata:
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
    5. **Title:** This is CRITICALLY IMPORTANT. Extract the article''s original title. Use the article''s headline; if absent, craft a concise, descriptive, SEO‑friendly title (no generic fillers).  Never use generic titles like "News article from [date]." Never use any AI filler titles.
    6. **Topic:** choose **one** — Government | Finance | Sports | Local News (prefer "Local News" if city/region is materially affected).  
    7. **Date:** The publication date of the article. This is CRITICALLY IMPORTANT. Extract the date from the metadata or the article content but look at the metadata first just for the data. Look for date fields in the metadata (e.g., ''date'', ''article:published_time'', etc.). If not found in metadata, search the article content. Provide the date in YYYY-MM-DD format. If no clear date is found, respond with "Date not found". Every news article has a date so you need to extract it. 
        Thoroughly search the entire content for any date information if not in the metadata. The date could be in the byline, in the article, in the metadata, or in the URL. It is somewhere in the markdown and you need to find it. 
        Look for dates in various formats, including but not limited to:
        - Explicit date mentions (e.g., "Published on June 1, 2024")
        - Datelines at the beginning of articles
        - Timestamps in metadata
        - References to "today", "yesterday", or days of the week
        - Look at the byline to see if it says when the article was published.
        - Any other indicators of when the article was published or the event occurred
        If multiple dates are found, prioritize the one that seems to be the publication date.
        Provide the full date string as found in the article, don''t try to reformat it.
        If no date is found after an exhaustive search, respond with "Date not found".
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
    Score: [Your score]  
    Summary (2-3 sentences): [your 2‑3 sentence summary]  
    Summary (6 sentences): [your 6‑sentence summary]  
    Summary (8 sentences): [your 8‑sentence summary]  
    Title: [The article title or your created title]  
    Topic: [Chosen topic from the list]  
    Date: [YYYY‑MM‑DD or "Date not found"]  
    New Main Topic: [Selected new main topic]  
    Subtopics:  
    - [Subtopic 1]  
    - [Subtopic 2]  

    *If any element is genuinely indeterminable, supply a best‑guess placeholder—except "Date," which must be "Date not found" if missing. Always include a Title.*

  Replace the content with the following:
  Title: {title}
  
  Content: {text}',
  'city_prompt',
  'gpt-4o-mini'
)
ON CONFLICT (description) DO NOTHING;

INSERT INTO public.scraper_prompts (prompt, description, model)
VALUES (
  'Analyze the following news article in markdown format and its metadata:
   Markdown Content:
   ${markdown.substring(0, 4000)}
   Metadata:
   ${metadataString}
   # Requirements for every summary written
    ## GLOBAL STYLE RULES
    1. **Wire‑service voice** (AP/Reuters): concise, neutral, instantly scannable yet authoritative.  
    2. **Lead with the single most news‑worthy fact** in ≤ 20 words, plain Subject‑Verb order.  
    *Ex:* "Tesla announces new battery technology that doubles vehicle range."  
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
    * **6‑sentence summary:** must add **new** concrete facts or one brief attributed quote **and** one clause explaining industry significance. No generic commentary.  
    * **8‑sentence summary:** expand the 6‑sentence version with **two** fresh lines:  
    – (a) authoritative background (historical, policy, or financial)  
    – (b) **one** additional hard detail (data point **or** short quote).  
    *Both added lines must present tangible information, never filler.*

    ## DELIVERABLE FIELDS (KEEP EXACT ORDER & HEADINGS)
    1. **Score:** 0–100 (apply rubric below).  
    2. **Summary (2‑3 sentences):** wire‑service brief obeying all style rules.  
    3. **Summary (6 sentences):** newsletter brief meeting Tier rules above.  
    4. **Summary (8 sentences):** mini‑feature meeting Tier rules above.  
    5. **Title:** This is CRITICALLY IMPORTANT. Extract the article''s original title. Use the article''s headline; if absent, craft a concise, descriptive, SEO‑friendly title (no generic fillers).  Never use generic titles like "News article from [date]." Never use any AI filler titles.
    6. **Topic:** choose **one** — Government | Finance | Sports | Industry News (prefer "Industry News" if a specific sector is materially affected).  
    7. **Date:** The publication date of the article. This is CRITICALLY IMPORTANT. Extract the date from the metadata or the article content but look at the metadata first just for the data. Look for date fields in the metadata (e.g., ''date'', ''article:published_time'', etc.). If not found in metadata, search the article content. Provide the date in YYYY-MM-DD format. If no clear date is found, respond with "Date not found". Every news article has a date so you need to extract it. 
        Thoroughly search the entire content for any date information if not in the metadata. The date could be in the byline, in the article, in the metadata, or in the URL. It is somewhere in the markdown and you need to find it. 
        Look for dates in various formats, including but not limited to:
        - Explicit date mentions (e.g., "Published on June 1, 2024")
        - Datelines at the beginning of articles
        - Timestamps in metadata
        - References to "today", "yesterday", or days of the week
        - Look at the byline to see if it says when the article was published.
        - Any other indicators of when the article was published or the event occurred
        If multiple dates are found, prioritize the one that seems to be the publication date.
        Provide the full date string as found in the article, don''t try to reformat it.
        If no date is found after an exhaustive search, respond with "Date not found".
    8. **New Main Topic:** choose **one** — Politics, Government, Business, Economy, Technology, Science, Health, Environment, Education, Sports, Arts, Entertainment, International Affairs, Crime, Social Issues, Culture, Transportation, Infrastructure, Religion, Agriculture, Food.
    9. **Subtopics:** Generate 2 relevant subtopics that reflect the specific focus of the article. These subtopics do not need to fit the predefined list but should represent key themes, events, or issues mentioned in the article.

    ### RUBRIC
    1. **Industry Relevance (25)** – sector/market impact (0‑15); industry voices/data (0‑10)  
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
    Score: [Your score]  
    Summary (2-3 sentences): [your 2‑3 sentence summary]  
    Summary (6 sentences): [your 6‑sentence summary]  
    Summary (8 sentences): [your 8‑sentence summary]  
    Title: [The article title or your created title]  
    Topic: [Chosen topic from the list]  
    Date: [YYYY‑MM‑DD or "Date not found"]  
    New Main Topic: [Selected new main topic]  
    Subtopics:  
    - [Subtopic 1]  
    - [Subtopic 2]  

    *If any element is genuinely indeterminable, supply a best‑guess placeholder—except "Date," which must be "Date not found" if missing. Always include a Title.*

  Replace the content with the following:
  Title: {title}
  
  Content: {text}',
  'global_industry_prompt',
  'gpt-4o-mini'
)
ON CONFLICT (description) DO NOTHING; 