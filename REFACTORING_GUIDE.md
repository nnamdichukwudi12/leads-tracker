# Leads Tracker - Enterprise Refactoring Guide

## Overview

Your leads-tracker app has been refactored into an enterprise-grade lead extraction and cold email campaign platform. The system now provides:

- **100+ Results per Query** from Google Maps with zero duplicates
- **Advanced Email Validation** with SMTP verification and bounce detection
- **Lead Enrichment** with company data and automatic email extraction
- **Campaign-Ready Lists** for cold email outreach
- **Safe Server Management** with rate limiting and async processing

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                   Google Places API                         │
│  (Text Query + Nearby Search with Pagination = 100+ results)│
��────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│              Lead Enrichment Pipeline                       │
│  - Website Email Extraction                                │
│  - Hunter.io Integration (find business emails)            │
│  - Clearbit Integration (company data)                     │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│            Email Validation & Verification                 │
│  - Syntax Validation (email-validator)                     │
│  - Disposable Email Detection                              │
│  - SMTP Verification (optional, rate-limited)              │
│  - Bounce Detection & Suppression List                     │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│          Deduplication & Database Storage                  │
│  - Place ID deduplication (most reliable)                  │
│  - Email deduplication                                     │
│  - Phone normalization & deduplication                     │
│  - Name + Address matching                                 │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│          Campaign-Ready Lead List                          │
│  - Verified emails only                                    │
│  - Company enrichment data                                 │
│  - Ready for cold email campaigns                          │
└─────────────────────────────────────────────────────────────┘
```

## New Files & Components

### 1. `app/services/google_places_enhanced.py`
**Enhanced Google Places API extraction with pagination**

Features:
- Text query search (20 results)
- Nearby search with pagination (up to 60 results across 3 pages)
- Place details enrichment
- Automatic deduplication via `seen_place_ids`
- Rate limiting and error handling

**Usage:**
```python
from app.services.google_places_enhanced import GooglePlacesExtractor

extractor = GooglePlacesExtractor()
results = await extractor.fetch_all_results(
    query="coffee shops",
    location="40.7128,-74.0060",  # Optional: lat,lon
    max_results=100
)
await extractor.close()
```

### 2. `app/services/email_validator.py`
**Advanced email validation with SMTP verification**

Features:
- Syntax validation using `email-validator`
- Disposable email detection (tempmail, guerrillamail, etc.)
- SMTP verification with rate limiting (configurable)
- Verification caching to avoid redundant checks
- Handles MX record lookups and SMTP RCPT TO checks

**Configuration:**
```env
SMTP_VERIFICATION_ENABLED=true|false  # Enable SMTP verification (default: false)
SMTP_VERIFICATION_TIMEOUT=5           # SMTP connection timeout in seconds
SMTP_VERIFICATION_RATE_LIMIT=10       # Max concurrent verifications
```

**Usage:**
```python
from app.services.email_validator import validate_email_async

result = await validate_email_async("contact@example.com", use_smtp=True)
# Returns: {
#   'valid': bool,
#   'verified': bool|None,
#   'reasons': list,
#   'details': str
# }
```

### 3. `app/services/leads_enrichment.py`
**Lead enrichment with email extraction and company data**

Features:
- Website email extraction via regex scraping
- Hunter.io API integration for business emails
- Clearbit API integration for company data
- Batch processing with rate limiting
- Async/await for efficient processing

**Configuration:**
```env
CLEARBIT_API_KEY=your_key          # Clearbit company data
HUNTER_API_KEY=your_key            # Hunter.io email finding
RESEARCH_TIMEOUT=10                # API call timeout
```

**Usage:**
```python
from app.services.leads_enrichment import enrich_lead_batch

leads = [
    {'name': 'Acme Corp', 'website': 'acme.com'},
    {'name': 'TechCo', 'website': 'techco.io'}
]

enriched = await enrich_lead_batch(leads)
# Each lead now has: email, company_name, industry, linkedin_url, etc.
```

### 4. `app/services/leads_pipeline.py`
**Complete end-to-end lead processing pipeline**

This is the main orchestrator that coordinates all services:

**`process_place_leads_enhanced()`**
- Fetches 100+ results from Google Places
- Enriches with company data and emails
- Validates and verifies emails
- Deduplicates across multiple strategies
- Saves to database
- Returns campaign-ready leads

**`fetch_and_prepare_campaign_leads()`**
- Runs complete pipeline
- Filters for verified emails only
- Groups leads by company
- Returns JSON-ready campaign data

**Usage:**
```python
from app.services.leads_pipeline import fetch_and_prepare_campaign_leads

campaign_data = await fetch_and_prepare_campaign_leads(
    query="restaurants in New York",
    location="40.7128,-74.0060",
    max_results=100
)

# Returns:
# {
#   'total_leads_processed': 100,
#   'total_leads_added': 85,
#   'campaign_ready_leads': 62,
#   'leads_with_emails': 78,
#   'leads_by_company': {...},
#   'leads': [...]
# }
```

## Configuration

Update your `.env` file with these new options:

```env
# Google Places
GOOGLE_PLACES_MAX_RESULTS=100
GOOGLE_PLACES_NEARBY_RADIUS=50000    # meters
GOOGLE_PLACES_BATCH_SIZE=100

# Email Validation
SMTP_VERIFICATION_ENABLED=false       # START WITH FALSE
SMTP_VERIFICATION_TIMEOUT=5
SMTP_VERIFICATION_RATE_LIMIT=10       # concurrent checks
SMTP_VERIFICATION_BATCH_SIZE=100

# Lead Enrichment
CLEARBIT_API_KEY=your_key_here
HUNTER_API_KEY=your_key_here
RESEARCH_TIMEOUT=10
```

## Usage Workflow

### Step 1: Extract Leads from Google Maps
```bash
curl -X POST http://localhost:8000/leads/fetch \
  -H "Content-Type: application/json" \
  -d '{
    "query": "local coffee shops",
    "location": "40.7128,-74.0060"
  }'
```

### Step 2: View Leads in Dashboard
Navigate to http://localhost:8000/dashboard to:
- Search leads
- View enriched company data
- Filter by verified status
- Export to CSV

### Step 3: Create Cold Email Campaign
```bash
curl -X POST http://localhost:8000/campaigns/create \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d '{
    "subject": "Partnership Opportunity",
    "body": "Hi {{name}}, we partner with {{company}} businesses...",
    "lead_ids": [1,2,3,4,5],
    "send_now": "on"
  }'
```

## Key Features Explained

### 1. Zero Duplicate Results

The system uses **4-layer deduplication**:

1. **Place ID** (most reliable - unique Google Maps identifier)
2. **Email** (exact match, case-insensitive)
3. **Normalized Phone** (all digits, min 7 digits)
4. **Name + Address** (normalized text comparison)

```python
# From leads_pipeline.py
if is_duplicate_lead(session, candidate):
    continue  # Skip duplicate
```

### 2. Safe Email Verification

**SMTP verification is disabled by default** because it requires:
- MX record lookups (DNS)
- SMTP connections to mail servers
- Proper error handling for various server responses

To enable safely:

```env
SMTP_VERIFICATION_ENABLED=true
SMTP_VERIFICATION_RATE_LIMIT=5    # Start low!
```

**How it works:**
1. Syntax validation (always enabled)
2. Disposable email detection (always enabled)
3. SMTP check (only if enabled + email passes syntax/disposable checks)
   - Looks up MX records for domain
   - Connects to mail server on port 25
   - Uses RCPT TO command (non-destructive)
   - Respects timeouts and rate limits

### 3. Lead Enrichment Pipeline

For each lead, the system attempts:

1. **Website Email Extraction** (regex scraping)
   - Looks for `contact@domain`, `info@domain`, etc.

2. **Hunter.io API** (if key provided)
   - Finds generic business emails
   - Rate-limited to 1 call per lead

3. **Clearbit API** (if key provided)
   - Gets company name, industry, size
   - Gets LinkedIn URL
   - Gets tech stack

### 4. Campaign-Ready Lists

Leads are only included in campaigns if they have:
- ✓ Valid email syntax
- ✓ Not on disposable email list
- ✓ Passed SMTP verification (if enabled) or syntax only (if disabled)
- ✓ Not in suppression list
- ✓ Not already in database (no duplicates)

## Database Models

### Lead
```python
class Lead(SQLModel, table=True):
    id: int (primary key)
    name: str
    email: str (indexed)
    phone: str
    address: str
    source: str = 'google_places_enhanced'
    place_id: str (unique, indexed)
    
    # Enriched data
    enriched_company: str
    enriched_linkedin: str
    enriched_source: str
    
    # Verification
    verified: bool
    verification_details: str
    
    # Normalized for deduplication
    normalized_phone: str
    normalized_name: str
    normalized_address: str
    
    # Timestamps
    created_at: datetime
    updated_at: datetime
```

### Suppression
```python
class Suppression(SQLModel, table=True):
    id: int (primary key)
    email: str (indexed)
    reason: str  # e.g., "Bounce", "Unsubscribe"
    source: str  # 'bounce', 'send', 'manual'
    created_at: datetime
```

## Performance Considerations

### API Rate Limiting
- **Google Places**: 20 results per request, pagination avoids repeated calls
- **Hunter.io**: ~1000 calls/month on free tier
- **Clearbit**: ~1000 calls/month on free tier
- **SMTP**: Configurable rate limit (default 10 concurrent)

### Email Verification Performance
```python
# DO: Safe approach (syntax only)
SMTP_VERIFICATION_ENABLED=false    # Uses syntax validation only
# Processes 100 emails in ~5 seconds

# CAUTION: Full SMTP verification
SMTP_VERIFICATION_ENABLED=true     # Connects to mail servers
SMTP_VERIFICATION_TIMEOUT=5        # Timeout per check
SMTP_VERIFICATION_RATE_LIMIT=5     # Max 5 concurrent
# Processes 100 emails in ~60-120 seconds depending on servers
```

### Database Deduplication
The 4-layer deduplication is efficient because:
1. `place_id` has unique index (fastest)
2. `email` has index (second fastest)
3. `normalized_phone` has index (third fastest)
4. Name + Address combo uses two indexed columns

All lookups are O(log n) operations.

## Error Handling & Logging

The pipeline includes detailed logging:

```
[1/5] Fetching 100 results from Google Places for 'coffee shops'...
[1/5] Found 95 candidates
[2/5] Enriching 95 leads with company data...
[2/5] Warning: Enrichment failed: Connection timeout
[3/5] Validating emails...
[3/5] Email validation complete
[4/5] Processing and deduplicating 95 leads...
  [1/95] Added Starbucks Coffee (contact@starbucks.com)
  [2/95] Added Blue Bottle Coffee (info@bluebottle.com)
  Skipping Local Cafe - email suppressed
  Skipping Joe's Coffee - duplicate
  [3/95] Added Intelligentsia Coffee (hello@intelligentsia.com)
[4/5] Successfully added 3 new leads
[5/5] Summary:
     Total leads processed: 95
     Leads added to database: 3
     Leads with verified emails: 3
     Campaign-ready leads: 3
```

## Troubleshooting

### Issue: Getting fewer than 100 results
**Solution**: Not all queries return 100 results. Try:
- More specific query: "Italian restaurants" instead of "restaurants"
- Different location parameters
- Nearby search requires valid location

### Issue: No emails being extracted
**Solution**: 
1. Enable Hunter.io API key (`HUNTER_API_KEY`)
2. Enable Clearbit API key (`CLEARBIT_API_KEY`)
3. Some businesses don't have websites in Google Places

### Issue: SMTP verification timing out
**Solution**:
- Disable SMTP verification: `SMTP_VERIFICATION_ENABLED=false`
- Increase timeout: `SMTP_VERIFICATION_TIMEOUT=10`
- Reduce rate limit: `SMTP_VERIFICATION_RATE_LIMIT=3`

### Issue: Duplicate leads appearing
**Solution**: Duplicates shouldn't appear due to 4-layer deduplication. If they do:
1. Check place_id format in Google data
2. Verify email normalization (strip/lowercase)
3. Rebuild normalized_phone fields with migration

## Next Steps

1. **Get API Keys**
   - Google Places API (required for live data)
   - Hunter.io (recommended for email finding)
   - Clearbit (recommended for company data)

2. **Enable Features Gradually**
   - Start with `SMTP_VERIFICATION_ENABLED=false`
   - Test with small queries first (5-10 results)
   - Increase batch sizes as you scale

3. **Set Up Campaigns**
   - Test campaign email template
   - Create suppression rules for bounces
   - Monitor reply tracking via IMAP

4. **Monitor Performance**
   - Watch API usage and quotas
   - Monitor database size as leads accumulate
   - Optimize enrichment settings based on results

## Support & Contributing

For issues or improvements:
1. Check logs in `/logs` directory
2. Test with smaller queries first
3. Report errors with full stack trace and query parameters
