import re
path = "app/tracker_app.py"
with open(path, encoding="utf-8") as f:
    lines = f.readlines()
for i, line in enumerate(lines):
    if "To edit or filter the actual data" in line and "sidebar" in line and '"""' in line:
        # Replace this line: remove any char(s) between "sidebar." and """)
        lines[i] = re.sub(r'(in the sidebar\.).*?("""\))', r'\1\n            \2', line)
        break
with open(path, "w", encoding="utf-8") as f:
    f.writelines(lines)
print("Done")
