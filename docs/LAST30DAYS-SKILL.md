# last30days -- Real-Time Research Synthesis Skill

Usage guide for [mvanhorn/last30days-skill](https://github.com/mvanhorn/last30days-skill), a Claude Code skill that searches 10 platforms simultaneously and synthesizes actionable intelligence from the last 30 days of community discussions.

## Why We Use It

Claude's training data has a cutoff. last30days injects fresh community intelligence directly into sessions -- what people are actually upvoting, discussing, and recommending RIGHT NOW. Useful for:

- Tracking competitor moves and industry trends
- Pre-design research (what do real engineers actually want?)
- Technology comparisons grounded in real usage data
- Monitoring AI development updates

## How It Works

Three-phase pipeline (not just search):

```
Search (10 platforms, last 30 days)
  -> Score (engagement + convergence + recency)
  -> Synthesize (patterns, consensus, actionable output)
```

### Scoring Algorithm

- Bidirectional text similarity with synonym expansion
- Engagement velocity normalization (upvotes, likes, views)
- Source authority weighting
- **Cross-platform convergence** -- topic appears on Reddit AND X AND HN = high signal
- Temporal recency decay

### Platforms

| Platform | API | Auth Required |
|----------|-----|---------------|
| Reddit | ScrapeCreators | Yes (shared key) |
| X/Twitter | xAI Responses API | Yes |
| YouTube | Transcript extraction | No |
| TikTok | ScrapeCreators | Yes (shared key) |
| Instagram Reels | ScrapeCreators | Yes (shared key) |
| Hacker News | Algolia | No (free) |
| Polymarket | Gamma API | No (free) |
| Bluesky | AT Protocol | Optional |
| Truth Social | Web scraping | No |
| General Web | Multiple providers | Optional |

## Installation

```bash
# Option 1: Marketplace (if available)
/plugin marketplace add mvanhorn/last30days-skill
/plugin install last30days@last30days-skill

# Option 2: Manual
git clone https://github.com/mvanhorn/last30days-skill ~/.claude/skills/last30days
```

### API Keys

Configure in `~/.config/last30days/.env`:

```bash
# Required for full coverage
SCRAPECREATORS_API_KEY=...    # Reddit + TikTok + Instagram (1 key, 3 sources)
XAI_API_KEY=...               # X/Twitter search

# Optional enhancements
BSKY_HANDLE=...               # Bluesky
BSKY_APP_PASSWORD=...
BRAVE_API_KEY=...             # Enhanced web search
OPENROUTER_API_KEY=...        # Additional web search
```

Three operational modes:
- **Full**: All platforms (requires all keys)
- **Partial**: Single platform + web (requires 1 key)
- **Web-only**: No API keys at all (free, limited)

## Usage

```bash
# Basic research
/last30days power system simulation trends

# Comparative mode (auto head-to-head)
/last30days PSS/E vs PowerWorld

# Quick mode (faster, less thorough)
/last30days --quick Claude Code new features

# Prediction markets
/last30days anthropic odds
```

Results save to `~/Documents/Last30Days/[topic].md`. Runs take 2-8 minutes.

## Usage Patterns

### Track Competitors
```
/last30days PowerWorld PSS/E power system software updates
/last30days browser-based engineering simulation tools
```

### Monitor AI Development
```
/last30days Claude Code new features skills
/last30days anthropic claude api updates
/last30days AI agent frameworks 2026
```

### Pre-Design Research
```
/last30days power system visualization what engineers want
/last30days MATLAB Simulink pain points switching tools
```

### Technology Decisions
```
/last30days KLU vs PARDISO sparse solver
/last30days Next.js vs Remix for SaaS dashboard
```

## Complement with Feynman

| Tool | Strength | When to Use |
|------|----------|-------------|
| **Feynman** | Deep academic research (papers, citations, peer review) | Before implementing algorithms, dissertation work |
| **last30days** | Real-time community intelligence (trending, engagement-weighted) | Market research, competitor tracking, tech decisions |

**Combined workflow:**
1. `/last30days` to find what's trending and what real users say
2. `feynman deepresearch` to go deep on the most promising findings
3. Feed both outputs into dispatch `.prompt` files as grounded context

## Architecture (for reference)

```
scripts/lib/
  openai_reddit.py    -- OpenAI Responses API + web_search for Reddit
  xai_x.py            -- xAI Responses API + x_search for X/Twitter
  hackernews.py        -- Algolia API (free)
  polymarket.py        -- Gamma API for prediction markets (free)
  reddit_enrich.py     -- Reddit thread JSON for engagement data
  score.py             -- Composite popularity-aware scoring
  dedupe.py            -- Near-duplicate detection
  normalize.py         -- Converts raw responses to standard schema
  cache.py             -- 24-hour TTL caching
  render.py            -- Markdown + JSON output
```

6-stage pipeline: Discovery -> Enrichment -> Normalization -> Scoring -> Deduplication -> Rendering
