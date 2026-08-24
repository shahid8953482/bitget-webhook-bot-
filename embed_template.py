import os
import re

with open('templates/dashboard.html', 'r', encoding='utf-8') as f:
    html_content = f.read()

with open('main.py', 'r', encoding='utf-8') as f:
    main_content = f.read()

# Pattern to replace DEFAULT_DASHBOARD_HTML = """..."""
pattern = r'DEFAULT_DASHBOARD_HTML = """[\s\S]*?"""'
new_string = f'DEFAULT_DASHBOARD_HTML = """{html_content}"""'

if re.search(pattern, main_content):
    new_main = re.sub(pattern, new_string, main_content)
    with open('main.py', 'w', encoding='utf-8') as f:
        f.write(new_main)
    print("SUCCESSFULLY RE-EMBEDDED DASHBOARD HTML WITH ACTIVE OPEN POSITIONS TABLE")
else:
    print("PATTERN NOT FOUND")
