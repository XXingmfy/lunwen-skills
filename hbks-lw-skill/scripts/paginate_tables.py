"""先保持整表同页，只有 Word 实测仍超页的表才拆为同号续表。"""
import argparse
from copy import deepcopy
from pathlib import Path
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph
from office_prepare import prepare_office
from word_layout import CAPTION, inspect_document, write_report

def caption_of(table):
    el=table._tbl.getprevious()
    if el is None or el.tag!=qn('w:p'):
        raise ValueError('表格前缺少紧邻题注，先修稿件再分页')
    p=Paragraph(el,table._parent)
    if not CAPTION.match(p.text.strip()):
        raise ValueError('表格前不是有效题注：'+p.text[:70])
    return p

def protect(table):
    for ri,row in enumerate(table.rows):
        trpr=row._tr.get_or_add_trPr()
        flag=trpr.find(qn('w:cantSplit'))
        if flag is None:
            flag=OxmlElement('w:cantSplit'); trpr.append(flag)
        flag.set(qn('w:val'),'1')
        if ri==0:
            header=trpr.find(qn('w:tblHeader'))
            if header is None:
                header=OxmlElement('w:tblHeader'); trpr.append(header)
            header.set(qn('w:val'),'1')
        for cell in row.cells:
            for p in cell.paragraphs:
                p.paragraph_format.keep_together=True
                p.paragraph_format.keep_with_next=ri<len(table.rows)-1
    caption=caption_of(table)
    caption.paragraph_format.keep_with_next=True
    caption.paragraph_format.keep_together=True
    if caption.text.startswith('续表'):
        caption.paragraph_format.page_break_before=True

def fingerprint(doc):
    groups=[]
    for t in doc.tables:
        match=CAPTION.match(caption_of(t).text.strip()); key=match.group(2)
        rows=[[c.text for c in r.cells] for r in t.rows]
        if match.group(1)=='续表':
            if not groups or groups[-1][0]!=key or groups[-1][1][0]!=rows[0]:
                raise ValueError('续表编号/表头不对应：'+key)
            groups[-1][1].extend(rows[1:])
        else:
            groups.append([key,rows])
    return groups

def split_table(table, boundary):
    if table._tbl.xpath('.//w:vMerge'):
        raise ValueError('超页表含纵向合并，不能安全自动拆分；请先调整合并设计')
    rows=list(table._tbl.tr_lst)
    if not 2<=boundary<len(rows):
        raise ValueError('表头与单条数据已超一页，需拆解内容；不得缩小字号强塞')
    cap=caption_of(table)
    match=CAPTION.match(cap.text.strip())
    new_el=deepcopy(table._tbl)
    for r in list(new_el.tr_lst): new_el.remove(r)
    new_el.append(deepcopy(rows[0]))
    for row in rows[boundary:]:
        table._tbl.remove(row); new_el.append(row)
    new_cap=deepcopy(cap._p)
    for marker in new_cap.xpath('.//w:bookmarkStart | .//w:bookmarkEnd'):
        marker.getparent().remove(marker)
    p=Paragraph(new_cap,table._parent)
    rpr=deepcopy(p.runs[0]._r.rPr) if p.runs and p.runs[0]._r.rPr is not None else None
    p.clear()
    run=p.add_run('续表'+match.group(2)+match.group(3))
    if rpr is not None: run._r.insert(0,rpr)
    table._tbl.addnext(new_cap); new_cap.addnext(new_el)
    protect(table); protect(Table(new_el,table._parent))

def make_caption_room(table):
    """表体刚好占满一页时，为题注腾出一行；优先并入已有下一续表。"""
    if len(table.rows)<=2:
        raise ValueError('题注、表头和单条数据无法同页，需重组内容')
    if table._tbl.xpath('.//w:vMerge'):
        raise ValueError('含纵向合并的超高表需要人工调整')
    key=CAPTION.match(caption_of(table).text.strip()).group(2)
    next_cap=table._tbl.getnext()
    next_table=next_cap.getnext() if next_cap is not None else None
    match=CAPTION.match(Paragraph(next_cap,table._parent).text.strip()) if next_cap is not None and next_cap.tag==qn('w:p') else None
    if match and match.group(1)=='续表' and match.group(2)==key and next_table is not None and next_table.tag==qn('w:tbl'):
        tail=table._tbl.tr_lst[-1]; table._tbl.remove(tail)
        next_table.tr_lst[0].addnext(tail)
        protect(table); protect(Table(next_table,table._parent))
        return 0
    split_table(table,len(table.rows)-1)
    return 1

def paginate(source, output, require_front=True, max_passes=20):
    import win32com.client
    source,output=Path(source).resolve(),Path(output).resolve()
    if source==output:
        raise ValueError('--out 必须是另一文件；验证成功后由调用者替换，失败不改原稿')
    output.parent.mkdir(parents=True,exist_ok=True)
    doc=Document(source); original=fingerprint(doc)
    for table in doc.tables: protect(table)
    doc.save(output)
    splits=0
    with prepare_office():
        word=win32com.client.DispatchEx('Word.Application')
        word.Visible=False; word.DisplayAlerts=0
        try:
            for attempt in range(max_passes):
                print(f'[paginate_tables] Word 实测第 {attempt+1} 轮',flush=True)
                live=word.Documents.Open(str(output),ReadOnly=True,AddToRecentFiles=False)
                try: report=inspect_document(live,require_front=require_front)
                finally: live.Close(False)
                over=[t for t in report['tables'] if t['pages'][0]!=t['pages'][1]]
                orphan=[t for t in report['tables'] if t['caption_pages']!=[t['pages'][0]]*2 and t not in over]
                if orphan:
                    doc=Document(output)
                    for item in reversed(orphan):
                        splits+=make_caption_room(doc.tables[item['index']-1])
                    if fingerprint(doc)!=original: raise RuntimeError('题注调整改变了数据内容')
                    doc.save(output)
                    continue
                if not over:
                    if fingerprint(Document(output))!=original:
                        raise RuntimeError('分页前后数据不一致，拒绝交付')
                    report['splits']=splits
                    report['data_preserved']=True
                    write_report(report,output)
                    if not report['ok']: raise RuntimeError('；'.join(report['errors']))
                    print(f'[paginate_tables] 通过：{len(report["tables"])} 段表，新增 {splits} 个续表，数据逐行核对一致')
                    return report
                doc=Document(output)
                for item in reversed(over):
                    if not item['rows']: raise ValueError('无法读取超页表行')
                    start=item['pages'][0]
                    boundary=next((i for i,(a,b) in enumerate(item['rows']) if a!=start or b!=start),None)
                    if boundary is None: raise ValueError('Word 页码与表行页码不一致，需人工复核')
                    split_table(doc.tables[item['index']-1],boundary); splits+=1
                if fingerprint(doc)!=original: raise RuntimeError('拆表改变了数据顺序或内容')
                doc.save(output)
            raise RuntimeError(f'经过 {max_passes} 次分页仍未收敛，停止并保留中间文件供检查')
        finally: word.Quit()

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('docx'); ap.add_argument('--out',required=True)
    ap.add_argument('--tables-only',action='store_true',help='仅用于表格回归样例；论文提交禁止跳过前置页核验')
    args=ap.parse_args()
    paginate(args.docx,args.out,require_front=not args.tables_only)

if __name__=='__main__': main()
