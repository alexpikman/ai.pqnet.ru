import json, subprocess
from datetime import datetime

def update():
    try:
        cmd = ['git', 'log', '-n 15', '--pretty=format:%h|%an|%ad|%s', '--date=short']
        result = subprocess.run(cmd, cwd='/var/www/ai.pqnet.ru', capture_output=True, text=True, encoding='utf-8')
        commits = []
        for line in result.stdout.split('\n'):
            if not line: continue
            parts = line.split('|')
            if len(parts) == 4:
                commits.append({'hash': parts[0], 'author': parts[1], 'date': parts[2], 'message': parts[3]})
        with open('/var/www/ai.pqnet.ru/changelog.json', 'w', encoding='utf-8') as f:
            json.dump({'updated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 'commits': commits}, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Error: {e}")

if __name__ == '__main__':
    update()
