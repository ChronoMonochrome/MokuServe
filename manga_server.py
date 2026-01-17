import os
import zipfile
import mimetypes
import re
import io
from urllib.parse import quote, unquote
from flask import Flask, send_file, render_template_string, abort

app = Flask(__name__)
BASE_DIR = os.getcwd()

# Regex for CSS background-image and HTML style attributes
STYLE_URL_PATTERN = re.compile(r'url\((["\']?)(.*?)(["\']?)\)')

# --- KODI INSPIRED CSS ---
KODI_STYLE = """
<style>
    :root { --bg: #121212; --card-bg: #1e1e1e; --text: #e0e0e0; --accent: #0084ff; }
    body { background-color: var(--bg); color: var(--text); font-family: 'Segoe UI', Roboto, sans-serif; margin: 0; padding: 20px; }
    h1 { font-weight: 300; border-bottom: 1px solid #333; padding-bottom: 10px; }
    .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 20px; padding: 20px 0; }
    .card { background: var(--card-bg); border-radius: 8px; overflow: hidden; transition: transform 0.2s, box-shadow 0.2s; text-decoration: none; color: inherit; display: flex; flex-direction: column; box-shadow: 0 4px 6px rgba(0,0,0,0.3); }
    .card:hover { transform: scale(1.05); box-shadow: 0 10px 20px rgba(0,0,0,0.5); border: 2px solid var(--accent); }
    .poster { width: 100%; aspect-ratio: 2/3; object-fit: cover; background: #222; }
    .title { padding: 10px; font-size: 0.9em; text-align: center; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .back-btn { display: inline-block; margin-bottom: 20px; color: var(--accent); text-decoration: none; font-weight: bold; }
    .file-list { list-style: none; padding: 0; }
    .file-list li { background: var(--card-bg); margin: 5px 0; border-radius: 4px; }
    .file-list a { display: block; padding: 15px; color: var(--text); text-decoration: none; }
    .file-list a:hover { background: #333; color: var(--accent); }
</style>
"""

# --- HELPER FUNCTIONS ---

def get_first_image(zip_path):
    """Recursively find the first image in a zip file to use as a cover."""
    try:
        with zipfile.ZipFile(zip_path, 'r') as z:
            img_exts = ('.jpg', '.jpeg', '.png', '.webp', '.gif')
            # Sort namelist to get logical "first" file (usually cover or page 001)
            for name in sorted(z.namelist()):
                if name.lower().endswith(img_exts) and not name.startswith('__MACOSX'):
                    return name
    except:
        pass
    return None

def rewrite_css_url(style_text, zip_name, internal_dir):
    def replacer(match):
        q_start, rel_path, q_end = match.groups()
        if rel_path.startswith(('http', 'https', 'data:', '#')): return match.group(0)
        target_path = os.path.normpath(os.path.join(internal_dir, rel_path)).replace("\\", "/")
        return f'url({q_start}/zip_content/{quote(zip_name)}/{quote(target_path)}{q_end})'
    return STYLE_URL_PATTERN.sub(replacer, style_text)

# --- ROUTES ---

@app.route('/')
def index():
    files = sorted([f for f in os.listdir(BASE_DIR) if f.lower().endswith('.zip')])
    html = f"""
    <!DOCTYPE html><html><head><title>Manga Library</title>{KODI_STYLE}</head>
    <body>
        <h1>Manga Library</h1>
        <div class="grid">
            {{% for file in files %}}
            <a href="/list/{{{{ file | urlencode }}}}" class="card">
                <img class="poster" src="/thumbnail/{{{{ file | urlencode }}}}" alt="Cover">
                <div class="title">{{{{ file }}}}</div>
            </a>
            {{% endfor %}}
        </div>
    </body></html>
    """
    return render_template_string(html, files=files)

@app.route('/thumbnail/<path:zip_name>')
def thumbnail(zip_name):
    zip_name = unquote(zip_name)
    zip_path = os.path.join(BASE_DIR, zip_name)
    img_name = get_first_image(zip_path)
    if not img_name: return abort(404)

    with zipfile.ZipFile(zip_path, 'r') as z:
        data = z.read(img_name)
        return send_file(io.BytesIO(data), mimetype=mimetypes.guess_type(img_name)[0])

@app.route('/list/<path:zip_name>')
def list_zip(zip_name):
    zip_name = unquote(zip_name)
    zip_path = os.path.join(BASE_DIR, zip_name)
    if not os.path.exists(zip_path): return abort(404)

    html_files = []
    with zipfile.ZipFile(zip_path, 'r') as z:
        html_files = sorted([n for n in z.namelist() if n.lower().endswith('.html')])

    template = f"""
    <!DOCTYPE html><html><head><title>{{{{ zip_name }}}}</title>{KODI_STYLE}</head>
    <body>
        <a href="/" class="back-btn">← BACK TO LIBRARY</a>
        <h2>{{{{ zip_name }}}}</h2>
        <ul class="file-list">
            {{% for item in html_files %}}
            <li><a href="/view/{{{{ zip_name | urlencode }}}}/{{{{ item | urlencode }}}}">{{{{ item }}}}</a></li>
            {{% endfor %}}
        </ul>
    </body></html>
    """
    return render_template_string(template, zip_name=zip_name, html_files=html_files)

@app.route('/view/<path:zip_name>/<path:internal_path>')
def view_html(zip_name, internal_path):
    zip_name, internal_path = unquote(zip_name), unquote(internal_path)
    zip_path = os.path.join(BASE_DIR, zip_name)
    with zipfile.ZipFile(zip_path, 'r') as z:
        content = z.read(internal_path).decode('utf-8', errors='ignore')
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(content, 'html.parser')
        internal_dir = os.path.dirname(internal_path)

        # Rewrite attributes
        for tag_name, attrs in {'img':['src','data-src'], 'link':['href'], 'script':['src'], 'a':['href']}.items():
            for tag in soup.find_all(tag_name):
                for attr in attrs:
                    if tag.has_attr(attr):
                        val = tag[attr]
                        if val.startswith(('http', 'data:', '#')): continue
                        target = os.path.normpath(os.path.join(internal_dir, val)).replace("\\", "/")
                        tag[attr] = f"/zip_content/{quote(zip_name)}/{quote(target)}"

        # Rewrite inline styles
        for tag in soup.find_all(style=True):
            tag['style'] = rewrite_css_url(tag['style'], zip_name, internal_dir)

        return str(soup)

@app.route('/zip_content/<path:zip_name>/<path:internal_path>')
def serve_zip_item(zip_name, internal_path):
    zip_name, internal_path = unquote(zip_name), unquote(internal_path)
    zip_path = os.path.join(BASE_DIR, zip_name)
    with zipfile.ZipFile(zip_path, 'r') as z:
        try:
            data = z.read(internal_path)
            return send_file(io.BytesIO(data), mimetype=mimetypes.guess_type(internal_path)[0])
        except KeyError: return abort(404)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=80)
