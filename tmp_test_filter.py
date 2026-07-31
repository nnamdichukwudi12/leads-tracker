from app.main import templates
print('templates', templates)
print('url_encode filter exists:', 'url_encode' in templates.env.filters)
print('filter value:', templates.env.filters.get('url_encode'))
print('all filters sample:', list(templates.env.filters.keys())[:20])
