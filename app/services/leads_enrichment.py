"""
Lead enrichment pipeline with email extraction and company data enhancement.
"""
import asyncio
import os
import httpx
from typing import Optional, Dict, Any
from .email_validator import get_email_validator

CLEARBIT_API_KEY = os.getenv('CLEARBIT_API_KEY')
HUNTER_API_KEY = os.getenv('HUNTER_API_KEY')
RESEARCH_TIMEOUT = int(os.getenv('RESEARCH_TIMEOUT', '10'))  # seconds

class LeadEnricher:
    """Enriches lead data with company info and email extraction."""
    
    def __init__(self):
        self.http_client = None
        self.validator = get_email_validator()
    
    async def get_http_client(self) -> httpx.AsyncClient:
        """Get or create async HTTP client."""
        if not self.http_client:
            self.http_client = httpx.AsyncClient(timeout=RESEARCH_TIMEOUT)
        return self.http_client
    
    async def close(self):
        """Close HTTP client."""
        if self.http_client:
            await self.http_client.aclose()
    
    async def extract_email_from_website(self, website_url: str | None) -> Optional[str]:
        """
        Extract business email from company website.
        Looks for common email patterns: contact@, info@, hello@, etc.
        """
        if not website_url:
            return None
        
        try:
            client = await self.get_http_client()
            
            # Ensure URL has protocol
            url = website_url if website_url.startswith('http') else f'https://{website_url}'
            
            response = await client.get(url, follow_redirects=True)
            html_content = response.text.lower()
            
            # Extract domain from URL
            domain_part = url.split('//')[1].split('/')[0].replace('www.', '')
            
            # Common email patterns to search for
            email_patterns = [
                f'contact@{domain_part}',
                f'info@{domain_part}',
                f'hello@{domain_part}',
                f'support@{domain_part}',
                f'sales@{domain_part}',
                f'business@{domain_part}',
            ]
            
            # Search for emails in HTML content
            import re
            email_regex = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
            emails_found = re.findall(email_regex, html_content)
            
            if emails_found:
                # Prefer emails matching domain
                domain_emails = [e for e in emails_found if domain_part in e]
                if domain_emails:
                    return domain_emails[0]
                # Return any found email
                return emails_found[0]
            
            return None
        
        except Exception as e:
            print(f"Error extracting email from {website_url}: {e}")
            return None
    
    async def enrich_from_clearbit(self, company_name: str | None, website: str | None) -> Dict[str, Any]:
        """
        Enrich lead data using Clearbit API.
        Returns company details including industry, size, etc.
        """
        if not CLEARBIT_API_KEY:
            return {}
        
        if not (company_name or website):
            return {}
        
        try:
            client = await self.get_http_client()
            
            # Clearbit Company API endpoint
            params = {}
            if website:
                params['domain'] = website.replace('https://', '').replace('http://', '').replace('www.', '')
            elif company_name:
                params['name'] = company_name
            
            headers = {'Authorization': f'Bearer {CLEARBIT_API_KEY}'}
            
            response = await client.get(
                'https://company-stream.clearbit.com/v1/domains/find',
                params=params,
                headers=headers
            )
            
            if response.status_code == 200:
                data = response.json()
                company = data.get('company', {})
                return {
                    'company_name': company.get('name'),
                    'industry': company.get('category', {}).get('industry'),
                    'company_size': company.get('metrics', {}).get('employees'),
                    'founded_year': company.get('founded', {}).get('year'),
                    'location': company.get('location'),
                    'linkedin_url': company.get('linkedin', {}).get('url'),
                    'tech_stack': company.get('tech'),
                }
        
        except Exception as e:
            print(f"Error enriching from Clearbit: {e}")
        
        return {}
    
    async def enrich_from_hunter(self, company_domain: str | None) -> Optional[str]:
        """
        Find business email using Hunter.io API.
        Returns company email if found.
        """
        if not HUNTER_API_KEY or not company_domain:
            return None
        
        try:
            client = await self.get_http_client()
            domain = company_domain.replace('https://', '').replace('http://', '').replace('www.', '')
            
            response = await client.get(
                'https://api.hunter.io/v2/domain-search',
                params={
                    'domain': domain,
                    'limit': 1,
                    'type': 'generic',
                    'api_key': HUNTER_API_KEY
                }
            )
            
            if response.status_code == 200:
                data = response.json()
                emails = data.get('data', {}).get('emails', [])
                if emails:
                    # Return first email found
                    return emails[0].get('email')
        
        except Exception as e:
            print(f"Error enriching from Hunter: {e}")
        
        return None
    
    async def enrich_lead(self, lead_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Complete lead enrichment pipeline.
        
        Attempts to:
        1. Extract email from website
        2. Find company email via Hunter
        3. Enrich company data via Clearbit
        
        Returns enriched lead data.
        """
        enriched = {}
        
        # Try to get email from various sources
        email = lead_data.get('email')
        website = lead_data.get('website')
        company_name = lead_data.get('name')
        
        # Extract from website if no email
        if not email and website:
            email = await self.extract_email_from_website(website)
        
        # Try Hunter.io
        if not email and website:
            email = await self.enrich_from_hunter(website)
        
        if email:
            enriched['email'] = email
            # Validate the email
            validation = await self.validator.validate_and_verify(email, use_smtp=False)
            enriched['email_valid'] = validation.get('valid')
        
        # Enrich company data
        company_enrichment = await self.enrich_from_clearbit(company_name, website)
        enriched.update(company_enrichment)
        
        return enriched


async def enrich_lead_batch(leads: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
    """
    Enrich multiple leads in parallel with rate limiting.
    """
    enricher = LeadEnricher()
    try:
        # Enrich in batches to avoid overwhelming external APIs
        enriched_leads = []
        batch_size = 5
        
        for i in range(0, len(leads), batch_size):
            batch = leads[i:i + batch_size]
            tasks = [enricher.enrich_lead(lead) for lead in batch]
            results = await asyncio.gather(*tasks)
            
            # Merge enrichment results with original leads
            for original, enrichment in zip(batch, results):
                merged = {**original, **enrichment}
                enriched_leads.append(merged)
            
            # Small delay between batches
            if i + batch_size < len(leads):
                await asyncio.sleep(1)
        
        return enriched_leads
    
    finally:
        await enricher.close()
