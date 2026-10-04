"""Render the last seven daily WakaTime summaries into the profile README."""
import base64
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
import http.client
import json
import os
from pathlib import Path
import re
import time
import urllib.error
import urllib.request
from zoneinfo import ZoneInfo


def duration(seconds):
    minutes = int(seconds // 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f'{hours} hrs {minutes} mins'
    return f'{minutes} mins' if minutes else '0 secs'


def render(payload):
    days = payload.get('data', [])
    if len(days) != 7:
        raise ValueError('Expected seven daily summaries; leave the README unchanged')
    languages = defaultdict(float)
    for day in days:
        for language in day['languages']:
            languages[language['name']] += language['total_seconds']
    total = sum(languages.values())
    if total <= 0:
        raise ValueError('No coding activity returned; leave the README unchanged')
    visible = sorted(((name, seconds) for name, seconds in languages.items() if name != 'Other'),
                     key=lambda item: (-item[1], item[0]))[:25]
    name_width = max(len(name) for name, _ in visible)
    start = date.fromisoformat(days[0]['range']['date']).strftime('%d %B %Y')
    end = date.fromisoformat(days[-1]['range']['date']).strftime('%d %B %Y')
    lines = ['```python', f'From: {start} - To: {end}', '', f'Total Time: {duration(total)}', '']
    for name, seconds in visible:
        percent = seconds / total * 100
        quarters = round(percent)
        blocks, remainder = divmod(quarters, 4)
        graph = '█' * blocks + ('░▒▓█'[remainder] if remainder else '')
        graph = graph.ljust(25, '░')
        lines.append(f'{name:<{name_width}}   {duration(seconds):<21} {graph}   {percent:05.2f} %')
    return '\n'.join(lines + ['```'])


def main():
    auth = base64.b64encode(os.environ['WAKATIME_API_KEY'].encode()).decode()

    def fetch(path):
        for attempt in range(4):
            # Both official hosts serve the same authenticated API.
            base = 'https://api.wakatime.com/api/v1' if attempt % 2 == 0 else 'https://wakatime.com/api/v1'
            request = urllib.request.Request(base + path, headers={'Authorization': 'Basic ' + auth})
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    return json.load(response)
            except urllib.error.HTTPError as error:
                if error.code not in (429, 500, 502, 503, 504) or attempt == 3:
                    raise
            except (urllib.error.URLError, http.client.RemoteDisconnected, TimeoutError):
                if attempt == 3:
                    raise
            time.sleep(2 ** attempt)

    user = fetch('/users/current')['data']
    today = datetime.now(ZoneInfo(user.get('timezone') or 'America/New_York')).date()
    dates = [(today - timedelta(days=offset)).isoformat() for offset in range(6, -1, -1)]

    def daily(day):
        response = fetch(f'/users/current/summaries?start={day}&end={day}')
        if len(response.get('data', [])) != 1:
            raise ValueError('Expected one summary per date')
        return response['data'][0]

    # Fetch days separately: a large historical backfill can exceed the API's
    # response deadline when all seven days are requested at once.
    with ThreadPoolExecutor(max_workers=3) as pool:
        payload = {'data': list(pool.map(daily, dates))}
    block = render(payload)
    path = Path('README.md')
    original = path.read_text()
    updated, count = re.subn(r'(?s)(<!--START_SECTION:waka-->).*?(<!--END_SECTION:waka-->)',
                             lambda match: match[1] + '\n\n' + block + '\n\n' + match[2], original)
    if count != 1:
        raise ValueError('Expected exactly one WakaTime section')
    if updated != original:
        path.write_text(updated)
    print('WakaTime README generated from seven daily summaries')


if __name__ == '__main__':
    main()
