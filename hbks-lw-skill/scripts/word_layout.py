"""Word 实际物理页码审计；不以 lastRenderedPageBreak 或行数估算分页。"""
import hashlib
import json
import re
from pathlib import Path

CAPTION = re.compile(r'^(续表|表)\s*(\d+[.．-]\d+)(.*)$')

def page_span(rng):
    first = rng.Duplicate
    first.Collapse(1)
    last = rng.Duplicate
    if last.End > last.Start:
        last.End -= 1
    last.Collapse(0)
    return [int(first.Information(3)), int(last.Information(3))]

def inspect_document(doc, require_front=True):
    doc.Repaginate()
    report = {'ok': True, 'errors': [], 'tables': [], 'front': {},
              'pages': int(doc.ComputeStatistics(2)), 'engine': 'Microsoft Word',
              'policy': 'whole-table-or-explicit-continuation'}
    previous = None
    if doc.Sections.Count>=6:
        body=doc.Sections(6).Range.Duplicate; body.Collapse(1)
        report['body_start_page']=int(body.Information(3))
    for i in range(1, doc.Tables.Count + 1):
        table = doc.Tables(i)
        before = doc.Range(max(0, table.Range.Start-1), max(0, table.Range.Start-1))
        before.MoveStart(4, -1)
        caption = before.Text.strip('\r\n\x07\x0c ')
        match = CAPTION.match(caption)
        item = {'index': i, 'caption': caption, 'pages': page_span(table.Range),
                'caption_pages': page_span(before), 'rows': [], 'header': ''}
        try:
            item['header'] = table.Rows(1).Range.Text
            item['rows'] = [page_span(table.Rows(j).Range) for j in range(1,table.Rows.Count+1)]
        except Exception as exc:
            report['errors'].append(f'表 {i} 含无法读取的合并行，需人工拆分并复核：{exc}')
        if not match:
            report['errors'].append(f'表 {i} 缺少紧邻的表X.Y或续表X.Y题注')
        if item['pages'][0] != item['pages'][1]:
            report['errors'].append(f'表 {i}（{caption}）跨物理页 {item["pages"]}，必须整表移页或拆成显式续表')
        if item['caption_pages'] != [item['pages'][0]]*2:
            report['errors'].append(f'表 {i} 题注与表格不在同一页')
        if any(a!=b for a,b in item['rows']):
            report['errors'].append(f'表 {i} 存在被跨页截断的行')
        if match:
            key=match.group(2)
            if match.group(1)=='续表':
                if previous is None or previous['key']!=key:
                    report['errors'].append(f'续表 {key} 没有相邻的同号原表/续表')
                elif item['header'] != previous['header']:
                    report['errors'].append(f'续表 {key} 的表头与前段不一致')
                elif item['pages'][0] <= previous['end']:
                    report['errors'].append(f'续表 {key} 没有在后续页起排')
            elif previous and key==previous['key']:
                report['errors'].append(f'表 {key} 重复编号，后段应标续表')
            previous={'key':key,'header':item['header'],'end':item['pages'][1]}
        report['tables'].append(item)
    if require_front:
        for name in ('学位论文原创性声明','学位论文版权使用授权书'):
            r=doc.Content.Duplicate
            if r.Find.Execute(FindText=name,MatchCase=True,MatchWholeWord=False,Wrap=0):
                report['front'][name]=page_span(r)
            else:
                report['errors'].append('缺少前置页标题：'+name)
        if any(v != [2,2] for v in report['front'].values()):
            report['errors'].append('当前前置页模板要求封面第1页、声明与授权同在第2页')
        for i in range(1,min(3,doc.Sections.Count)+1):
            report['front'][f'section_{i}']=page_span(doc.Sections(i).Range)
        if doc.Sections.Count >= 3:
            sec3=doc.Sections(3).Range.Duplicate; sec3.Collapse(1)
            if sec3.Information(3)!=3:
                report['errors'].append('前置页发生溢出：中文摘要未从物理第3页开始')
    report['ok']=not report['errors']
    return report

def write_report(report, docx, output=None):
    path=Path(docx)
    report['docx_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
    report['docx']=str(path.resolve())
    target=Path(output) if output else path.with_suffix('.layout.json')
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return target
