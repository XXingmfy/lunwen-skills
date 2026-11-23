"""经用户标准样例校准的前置页；模板槽位只存在于资产，不进入成品。"""
from pathlib import Path
import re
from docx import Document
from docx.oxml.ns import qn

DEFAULT_TEMPLATE = Path(__file__).resolve().parents[1] / 'assets' / 'hbks-frontmatter.docx'
REQUIRED = ('title', 'name', 'student_id', 'college', 'major', 'advisor', 'date')
UNFINISHED = re.compile(r'待补充|待填写|待定|TBD|TODO|占位|\{\{|\[填写', re.I)

def replace_token(paragraph, token, value):
    """允许 Word 把占位符拆成多个 run；不破坏其余字体与下划线。"""
    while token in paragraph.text:
        runs = paragraph.runs
        text = ''.join(r.text for r in runs)
        start, end = text.index(token), text.index(token) + len(token)
        pos = 0
        inserted = False
        for run in runs:
            old = run.text
            a, b = pos, pos + len(old)
            pos = b
            if b <= start or a >= end:
                continue
            left = old[:max(0, start-a)]
            right = old[max(0, end-a):]
            run.text = left + (str(value) if not inserted else '') + right
            inserted = True

def front_document(meta, base_dir):
    missing = [k for k in REQUIRED if not str(meta.get(k, '')).strip() or UNFINISHED.search(str(meta[k]))]
    if missing:
        raise ValueError('前置页必填信息缺失或含占位词：' + ', '.join(missing) + '；请写入缺证清单，不生成空白成品。')
    path = meta.get('front_template')
    if path:
        path = Path(path)
        if not path.is_absolute():
            path = Path(base_dir) / path
    else:
        if meta.get('school', '河北科技师范学院') != '河北科技师范学院':
            raise ValueError('其他学校必须提供经过核验的 front_template，不能套用河北科技师范学院校徽与声明。')
        path = DEFAULT_TEMPLATE
    doc = Document(str(path))
    fields = dict(meta)
    fields.setdefault('school', '河北科技师范学院')
    fields.setdefault('doc_type', '学士学位论文')
    # 封面日期不是签署日期。未明确提供签署日期，保留模板的手写日期栏。
    fields.setdefault('signature_date', '年    月    日')
    if not str(fields.get('signature_date','')).strip():
        fields['signature_date']='年    月    日'
    elif UNFINISHED.search(str(fields['signature_date'])):
        raise ValueError('signature_date 不能使用占位词；未知时省略该字段并保留手写栏。')
    if path == DEFAULT_TEMPLATE:
        for key in ('name', 'student_id', 'college', 'major', 'advisor'):
            value = str(fields[key])
            units = sum(1 if ord(c) < 128 else 2 for c in value)
            if units > 24:
                raise ValueError(f'封面 {key} 超出模板字段宽度，需调整模板并重新渲染，不得静默缩小字体。')
            pad = 24 - units
            fields[key] = ' ' * (pad // 2) + value + ' ' * (pad - pad // 2)
    for p in doc.paragraphs:
        for key, value in fields.items():
            replace_token(p, '{{' + key + '}}', value)
    leftovers = re.findall(r'\{\{[^}]+\}\}', '\n'.join(p.text for p in doc.paragraphs))
    if leftovers:
        raise ValueError('前置页模板有未绑定字段：' + ', '.join(sorted(set(leftovers))))
    if len(doc.sections) != 2:
        raise ValueError('前置页模板应为两节：封面一节、声明与授权同页一节。自定义模板需先适配节映射。')
    doc.core_properties.title = str(meta['title'])
    doc.core_properties.author = str(meta['name'])
    return doc
