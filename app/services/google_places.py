import os
import httpx

GOOGLE_KEY = os.getenv('GOOGLE_PLACES_API_KEY')

async def fetch_places(query: str, location: str | None = None) -> list:
    """Fetch leads from Google Places or return mock data when no API key is configured."""
    if not GOOGLE_KEY:
        return [
            {'name': 'Mock Coffee Shop', 'address': '123 Mock St', 'phone': '+1-555-0100', 'email': 'hello@mockcoffee.local'},
            {'name': 'Mock Restaurant', 'address': '456 Mock Ave', 'phone': '+1-555-0200', 'email': 'info@mockrestaurant.local'},
        ]

    params = {
        'key': GOOGLE_KEY,
        'input': query,
        'inputtype': 'textquery',
        'fields': 'name,formatted_address,formatted_phone_number,place_id,website,formatted_phone_number'
    }
    if location:
        params['locationbias'] = f'point:{location}'

    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get('https://maps.googleapis.com/maps/api/place/findplacefromtext/json', params=params)
        response.raise_for_status()
        data = response.json()
        if data.get('status') != 'OK':
            return []

        results: list[dict] = []
        for candidate in data.get('candidates', []):
            results.append({
                'name': candidate.get('name'),
                'address': candidate.get('formatted_address'),
                'phone': candidate.get('formatted_phone_number'),
                'email': None,
                'place_id': candidate.get('place_id'),
                'website': candidate.get('website')
            })
        return results
