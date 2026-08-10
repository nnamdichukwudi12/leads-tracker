"""
Enhanced Google Places API service for enterprise-scale lead extraction.
Fetches 100+ results per query with pagination and deduplication.
"""
import os
import httpx
import asyncio
from typing import Optional, List, Dict, Any
from sqlmodel import Session, select
from ..database import get_engine
from ..models import Lead

GOOGLE_KEY = os.getenv('GOOGLE_PLACES_API_KEY')
GOOGLE_PLACES_NEARBY_RADIUS = int(os.getenv('GOOGLE_PLACES_NEARBY_RADIUS', '50000'))  # 50km default
BATCH_SIZE = int(os.getenv('GOOGLE_PLACES_BATCH_SIZE', '100'))
MAX_RESULTS_PER_QUERY = int(os.getenv('GOOGLE_PLACES_MAX_RESULTS', '100'))


class GooglePlacesExtractor:
    """Enhanced Google Places business lead extractor with pagination and deduplication."""
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or GOOGLE_KEY
        self.session = None
        self.seen_place_ids = set()
        
    async def _get_http_client(self) -> httpx.AsyncClient:
        """Get or create async HTTP client."""
        if not self.session:
            self.session = httpx.AsyncClient(timeout=30.0)
        return self.session
    
    async def close(self):
        """Close HTTP client."""
        if self.session:
            await self.session.aclose()
    
    async def _search_places_textquery(self, query: str, location: str | None = None) -> List[Dict[str, Any]]:
        """
        Search places using text query (findplacefromtext).
        Supports up to 20 results per request.
        """
        if not self.api_key:
            return self._get_mock_places(query)
        
        client = await self._get_http_client()
        results = []
        
        params = {
            'key': self.api_key,
            'input': query,
            'inputtype': 'textquery',
            'fields': 'name,formatted_address,formatted_phone_number,place_id,website,opening_hours,photos,business_status'
        }
        
        if location:
            params['locationbias'] = f'point:{location}'
        
        try:
            response = await client.get(
                'https://maps.googleapis.com/maps/api/place/findplacefromtext/json',
                params=params
            )
            response.raise_for_status()
            data = response.json()
            
            if data.get('status') in ['OK', 'ZERO_RESULTS']:
                candidates = data.get('candidates', [])
                for candidate in candidates:
                    place_id = candidate.get('place_id')
                    if place_id not in self.seen_place_ids:
                        self.seen_place_ids.add(place_id)
                        results.append({
                            'name': candidate.get('name'),
                            'address': candidate.get('formatted_address'),
                            'phone': candidate.get('formatted_phone_number'),
                            'email': None,
                            'place_id': place_id,
                            'website': candidate.get('website'),
                            'business_status': candidate.get('business_status'),
                            'search_type': 'text_query'
                        })
        except Exception as e:
            print(f"Error in text query search: {e}")
        
        return results
    
    async def _search_places_nearby(self, query: str, location: str | None = None, page_token: str | None = None) -> tuple[List[Dict[str, Any]], str | None]:
        """
        Search nearby places (nearbysearch).
        Supports pagination via page_token and returns up to 20 results per page.
        """
        if not self.api_key or not location:
            return [], None
        
        client = await self._get_http_client()
        results = []
        next_page_token = None
        
        params = {
            'key': self.api_key,
            'keyword': query,
            'radius': GOOGLE_PLACES_NEARBY_RADIUS,
            'location': location,
            'fields': 'name,formatted_address,formatted_phone_number,place_id,website,opening_hours,business_status'
        }
        
        if page_token:
            params['pagetoken'] = page_token
        
        try:
            response = await client.get(
                'https://maps.googleapis.com/maps/api/place/nearbysearch/json',
                params=params
            )
            response.raise_for_status()
            data = response.json()
            
            if data.get('status') in ['OK', 'ZERO_RESULTS']:
                results_data = data.get('results', [])
                for result in results_data:
                    place_id = result.get('place_id')
                    if place_id not in self.seen_place_ids:
                        self.seen_place_ids.add(place_id)
                        results.append({
                            'name': result.get('name'),
                            'address': result.get('formatted_address'),
                            'phone': result.get('formatted_phone_number'),
                            'email': None,
                            'place_id': place_id,
                            'website': result.get('website'),
                            'business_status': result.get('business_status'),
                            'search_type': 'nearby'
                        })
                
                next_page_token = data.get('next_page_token')
                # Google requires delay before using next_page_token
                if next_page_token:
                    await asyncio.sleep(2)
        except Exception as e:
            print(f"Error in nearby search: {e}")
        
        return results, next_page_token
    
    async def _get_place_details(self, place_id: str) -> Dict[str, Any]:
        """
        Get detailed information about a place including website/email extraction.
        """
        if not self.api_key:
            return {}
        
        client = await self._get_http_client()
        params = {
            'key': self.api_key,
            'place_id': place_id,
            'fields': 'name,formatted_address,formatted_phone_number,website,email,business_status,opening_hours,types,url'
        }
        
        try:
            response = await client.get(
                'https://maps.googleapis.com/maps/api/place/details/json',
                params=params
            )
            response.raise_for_status()
            data = response.json()
            
            if data.get('status') == 'OK':
                result = data.get('result', {})
                return {
                    'name': result.get('name'),
                    'address': result.get('formatted_address'),
                    'phone': result.get('formatted_phone_number'),
                    'website': result.get('website'),
                    'email': result.get('email'),
                    'business_status': result.get('business_status'),
                    'google_url': result.get('url'),
                    'types': result.get('types', [])
                }
        except Exception as e:
            print(f"Error getting place details: {e}")
        
        return {}
    
    def _get_mock_places(self, query: str, count: int = 100) -> List[Dict[str, Any]]:
        """Return mock data for testing without API key."""
        mock_data = []
        business_types = ['coffee', 'restaurant', 'hotel', 'gym', 'salon', 'clinic', 'store']
        
        for i in range(count):
            business_type = business_types[i % len(business_types)]
            mock_data.append({
                'name': f'{business_type.title()} Business {i+1}',
                'address': f'{100+i} Mock Street, Mock City, MC 12345',
                'phone': f'+1-555-{1000+i:04d}',
                'email': None,
                'place_id': f'mock_place_{i}',
                'website': f'https://mock{business_type}{i}.local',
                'business_status': 'OPERATIONAL',
                'search_type': 'mock'
            })
        
        self.seen_place_ids.update([p['place_id'] for p in mock_data])
        return mock_data
    
    async def fetch_all_results(self, query: str, location: str | None = None, max_results: int = MAX_RESULTS_PER_QUERY) -> List[Dict[str, Any]]:
        """
        Fetch all available results for a query up to max_results.
        Combines text query and nearby search pagination.
        """
        all_results = []
        
        # Phase 1: Text query search (up to 20 results)
        text_results = await self._search_places_textquery(query, location)
        all_results.extend(text_results)
        
        # Phase 2: Nearby search with pagination (up to 60 results across 3 pages)
        if location and len(all_results) < max_results:
            next_page_token = None
            page_count = 0
            max_pages = 3  # Google allows 3 pages per nearby search
            
            while page_count < max_pages and len(all_results) < max_results:
                nearby_results, next_page_token = await self._search_places_nearby(
                    query, 
                    location, 
                    next_page_token
                )
                all_results.extend(nearby_results)
                page_count += 1
                
                if not next_page_token:
                    break
                
                # Small delay between pages
                await asyncio.sleep(0.5)
        
        # Phase 3: Enrich results with detailed information
        enriched_results = []
        for result in all_results[:max_results]:
            if result.get('place_id'):
                # Add rate limiting for details API
                await asyncio.sleep(0.1)
                details = await self._get_place_details(result['place_id'])
                result.update(details)
            enriched_results.append(result)
        
        return enriched_results
    
    async def fetch_results_batch(self, query: str, location: str | None = None) -> List[Dict[str, Any]]:
        """Fetch results with default batch size (100 results)."""
        return await self.fetch_all_results(query, location, BATCH_SIZE)


async def fetch_places(query: str, location: str | None = None, max_results: int = 100) -> List[Dict[str, Any]]:
    """
    Main entry point for fetching Google Places leads.
    Returns up to 100 results per query with automatic deduplication.
    """
    extractor = GooglePlacesExtractor()
    try:
        results = await extractor.fetch_all_results(query, location, max_results)
        return results
    finally:
        await extractor.close()
