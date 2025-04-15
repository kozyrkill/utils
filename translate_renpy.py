import os
import re
import ast
import sqlite3
import shutil
from deep_translator import GoogleTranslator
from tqdm import tqdm

# === Настройки ===
GAME_DIR = "game"
LANG_FROM = "en"
LANG_TO = "ru"
DB_PATH = "translate_cache.sqlite"
DRY_RUN = False
USE_CHATGPT = False  # выключено по умолчанию
CHATGPT_MODEL = "gpt-4o"

# === SQLite Cache ===
class TranslationCache:
    def __init__(self, db_path=DB_PATH):
        self.conn = sqlite3.connect(db_path)
        self._init_db()

    def _init_db(self):
        with self.conn:
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS translations (
                    src TEXT PRIMARY KEY,
                    dest TEXT
                )
            """)

    def get(self, src):
        cur = self.conn.cursor()
        cur.execute("SELECT dest FROM translations WHERE src = ?", (src,))
        row = cur.fetchone()
        return row[0] if row else None

    def set(self, src, dest):
        with self.conn:
            self.conn.execute("INSERT OR REPLACE INTO translations (src, dest) VALUES (?, ?)", (src, dest))

cache = TranslationCache()

# === Фильтр строк ===
RENPLY_RESERVED_WORDS = {
    "subtitle", "main_menu", "navigation", "confirm", "history",
    "skip", "about", "return_button", "nvl_window", "input", "style",
    "slot", "window", "viewport", "frame", "quick", "label", "say",
    "help", "notify", "nvl", "yesno_prompt", "confirm_prompt",
    "save", "load", "preferences", "main_menu_title", "main_menu_version"
}

RENPY_KEYWORDS = [
    "draggable", "mousewheel", "transclude",
    "xsize", "ysize", "xfill", "yfill", "area", "vpgrid", "vbox", "hbox",
    "add", "text", "button", "textbutton", "input", "use", "window",
    "viewport", "frame", "style", "spacing", "align", "anchor", "xalign", "yalign",
    "xanchor", "yanchor", "at", "offset", "minimum", "maximum",
    "scrollbars", "side_yfill", "style_prefix", "color", "font"
]

ALL_RENPY_KEYWORDS = RENPY_KEYWORDS + list(RENPLY_RESERVED_WORDS)

def should_skip_by_full_line(line):
    stripped = line.strip().lower()
    for keyword in ALL_RENPY_KEYWORDS:
        if stripped.startswith(keyword + " ") or stripped == keyword:
            print(f"[≠] Пропуск строки ({keyword}): {stripped}")
            return True
    return False

def is_translatable(s):
    s = s.strip()
    if not s or len(s) <= 2:
        print(f"[≠] Пропуск (пустая/короткая): {s}")
        return False
    if re.fullmatch(r"#?[0-9a-fA-F]{6,8}", s):
        print(f"[≠] Пропуск (hex): {s}")
        return False
    if re.search(r"\.(ttf|otf|woff2?|png|jpg|rpy|mp3|ogg|wav|webp)$", s, re.IGNORECASE):
        print(f"[≠] Пропуск (расширение): {s}")
        return False
    if re.match(r"^[\w\-./]+/\w+\.\w{2,4}$", s):
        print(f"[≠] Пропуск (путь): {s}")
        return False
    if re.fullmatch(r"[A-Za-z0-9+*/.\-_:]+", s) and len(s) <= 6:
        print(f"[≠] Пропуск (техническая): {s}")
        return False
    if s == s.upper():
        print(f"[≠] Пропуск (ALLCAPS): {s}")
        return False
    if re.search(r"[А-Яа-яЁё]", s):
        print(f"[≠] Пропуск (рус): {s}")
        return False

    first_word = s.strip().split()[0].lower()
    if first_word in RENPY_KEYWORDS:
        print(f"[≠] Пропуск (ключевое слово): {s} → {first_word}")
        return False
    if first_word in RENPLY_RESERVED_WORDS:
        print(f"[≠] Пропуск (зарезерв.): {s} → {first_word}")
        return False

    if re.search(r"\[.*?[!|:]t\]", s):
        print(f"[≠] Пропуск (тэг в []): {s}")
        return False

    text_only = re.sub(r"{.*?}", "", s)
    result = any(c.isalpha() for c in text_only)
    print(f"[✓] Проверка: {s} → {result}")
    return result

# === Перевод с кэшем ===
def batch_translate(texts, src=LANG_FROM, dest=LANG_TO):
    print(f"[→] Переводим {len(texts)} строк...")

    def chunk_by_chars(texts, max_chars=4500):
        chunk, total = [], 0
        for t in texts:
            if total + len(t) > max_chars and chunk:
                yield chunk
                chunk, total = [], 0
            chunk.append(t)
            total += len(t)
        if chunk:
            yield chunk

    translated = []
    to_translate = []
    to_translate_map = {}

    for t in texts:
        if not is_translatable(t):
            translated.append(t)
        else:
            cached = cache.get(t)
            if cached:
                print(f"[✓] Кэш: {repr(t)} → {repr(cached)}")
                translated.append(cached)
            else:
                to_translate.append(t)
                to_translate_map[t] = len(translated)
                translated.append(None)

    for chunk in chunk_by_chars(to_translate):
        try:
            output = GoogleTranslator(source=src, target=dest).translate_batch(chunk)
            for original, tr in zip(chunk, output):
                idx = to_translate_map[original]
                translated[idx] = tr
                cache.set(original, tr)
                print(f"[→] {repr(original)} → {repr(tr)}")
        except Exception as e:
            print(f"[!] Ошибка чанка: {e}")
            for original in chunk:
                idx = to_translate_map[original]
                try:
                    tr = GoogleTranslator(source=src, target=dest).translate(original)
                except Exception as e2:
                    print(f"[✗] Fallback не сработал для {repr(original)}: {e2}")
                    tr = original  # Подставляем оригинал
                translated[idx] = tr
                cache.set(original, tr)
                print(f"[→] fallback: {repr(original)} → {repr(tr)}")

    return translated

# === AST ===
class PythonStringCollector(ast.NodeVisitor):
    def __init__(self):
        self.strings = set()

    def visit_Constant(self, node):
        if isinstance(node.value, str):
            self.strings.add(node.value)

    def visit_JoinedStr(self, node):
        for part in node.values:
            if isinstance(part, ast.Constant) and isinstance(part.value, str):
                self.strings.add(part.value)

class PythonStringReplacer(ast.NodeTransformer):
    def __init__(self, translations):
        self.translations = translations

    def visit_Constant(self, node):
        if isinstance(node.value, str) and node.value in self.translations:
            return ast.copy_location(ast.Constant(value=self.translations[node.value]), node)
        return node

    def visit_JoinedStr(self, node):
        new_values = []
        for part in node.values:
            if isinstance(part, ast.Constant) and isinstance(part.value, str):
                val = self.translations.get(part.value, part.value)
                new_values.append(ast.copy_location(ast.Constant(value=val), part))
            else:
                new_values.append(part)
        node.values = new_values
        return node

# === Dialogs ===
dialogue_pattern = re.compile(r'^(\s*)([a-zA-Z0-9_.]+\s+)?(?P<q>("{1,3}.*?"{1,3}|\'{1,3}.*?\'{1,3}))\s*$', re.DOTALL)
menu_item_pattern = re.compile(r'^(\s*)["\'](.*?)["\'](\s*):\s*$')

def extract_dialogue_lines(lines):
    i, texts, indexes = 0, [], []
    while i < len(lines):
        line = lines[i]
        if line.strip().startswith("#") or should_skip_by_full_line(line):
            i += 1
            continue
        match = dialogue_pattern.match(line)
        if match:
            prefix = match.group(1)
            speaker = match.group(2)
            quote = match.group('q')
            quote_type = quote[0]
            text = quote.strip(quote_type)
            texts.append(text)
            indexes.append((i, prefix, speaker or "", quote_type, ""))
        elif menu_item_pattern.match(line):
            prefix, text, suffix = menu_item_pattern.match(line).groups()
            texts.append(text)
            indexes.append((i, prefix, "", '"', suffix + ":"))
        i += 1
    return texts, indexes

def restore_dialogue_lines(lines, translations, indexes):
    for (i, prefix, speaker, quote, suffix), translated in zip(indexes, translations):
        lines[i] = f'{prefix}{speaker}{quote}{translated}{quote}{suffix}\n'

# === Python блоки ===
def extract_python_blocks(lines):
    in_block, blocks, current, start_line = False, [], [], 0
    for i, line in enumerate(lines):
        if re.match(r'^\s*(init\s+)?python\s*:.*$', line):
            in_block = True
            current = []
            start_line = i + 1
        elif in_block and re.match(r'^\s*\S', line):
            blocks.append((start_line, current))
            in_block = False
        elif in_block:
            current.append(line)
    if in_block:
        blocks.append((start_line, current))
    return blocks

def translate_python_block(block_lines):
    code = "".join(block_lines)
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return block_lines
    collector = PythonStringCollector()
    collector.visit(tree)
    strings = sorted(collector.strings)
    if not strings:
        return block_lines
    translated = batch_translate(strings)
    mapping = dict(zip(strings, translated))
    replacer = PythonStringReplacer(mapping)
    new_tree = replacer.visit(tree)
    try:
        new_code = ast.unparse(new_tree)
        return [line + "\n" for line in new_code.splitlines()]
    except Exception as e:
        print(f"[!] Ошибка генерации кода: {e}")
        return block_lines

# === Обработка файла ===
def process_file(filepath):
    with open(filepath, "r", encoding="utf-8-sig") as f:
        lines = f.readlines()
    original = list(lines)

    blocks = extract_python_blocks(lines)
    for start_line, block in reversed(blocks):
        translated_block = translate_python_block(block)
        lines[start_line:start_line+len(block)] = translated_block

    texts, indexes = extract_dialogue_lines(lines)
    if texts:
        translations = batch_translate(texts)
        restore_dialogue_lines(lines, translations, indexes)

    if lines != original and not DRY_RUN:
        shutil.copy(filepath, filepath + ".bak")
        with open(filepath, "w", encoding="utf-8") as f:
            f.writelines(lines)
        print(f"[→] Обновлён: {filepath} (резерв: .bak)")

# === Главный цикл ===
def main():
    all_files = []
    for root, _, files in os.walk(GAME_DIR):
        for file in files:
            if file.endswith(".rpy"):
                all_files.append(os.path.join(root, file))

    for path in tqdm(all_files, desc="Обработка файлов", ncols=80):
        print(f"\n>>> Обработка: {path}")
        process_file(path)

if __name__ == "__main__":
    main()
