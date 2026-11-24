#!/usr/bin/env python3
import argparse
from pathlib import Path
from slide_pattern_index import default_source, Library, build, dump, distinct_paths, index_path
p=argparse.ArgumentParser(description='Build derived index and family navigation from canonical JSONL')
p.add_argument('--file',type=Path)
p.add_argument('--index',type=Path)
p.add_argument('--catalog',type=Path)
a=p.parse_args()
try:
    a.file = a.file or default_source()
    target = a.index or index_path(a.file)
    cat = a.catalog or target.with_name('slide-pattern-families.md')
    distinct_paths(a.file, target, cat)
    build(a.file, target)
except (ValueError, KeyError, OSError) as error:
    p.error(str(error))
lib = Library(a.file, target)
lines=['# Семейства приёмов\n','Автоматические поисковые группы по текстам описаний. Это гипотезы для отбора; применимость проверяется по полному рецепту. Один пример может входить в несколько групп. Числа и ограничения не додуманы.\n']
for f in lib.catalog():
 lines.extend([f"## {f['title']} (`{f['id']}`, {f['count']})",f['principle']])
 for r in f['examples']:lines.append(f"- {r['id']} · строка {r['line']}: {r['principle']}")
 lines.append('')
cat.write_text('\n'.join(lines),encoding='utf-8')
print(dump({'index':str(target),'catalog':str(cat),'records':lib.db.execute('SELECT count(*) FROM cards').fetchone()[0],'sha256':lib.meta['sha256']}))
lib.close()
