"""独立合成文档回归，绝不修改用户提供的论文。--word 执行真实 Word 分页。"""
import argparse
import json
from pathlib import Path
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from build_docx import build_docx, iter_blocks
from frontmatter import front_document, DEFAULT_TEMPLATE
from paginate_tables import paginate, fingerprint
from update_fields import update_docx
from check_docx import check

META={'school':'河北科技师范学院','title':'基于多维数据的知识关系管理与时空可视化系统的设计与实现',
      'name':'测试作者','student_id':'0000000000','college':'数学与信息科技学院',
      'major':'数据科学与大数据技术','advisor':'测试导师','date':'二〇二六年五月'}

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out',required=True); ap.add_argument('--word',action='store_true')
    args=ap.parse_args(); out=Path(args.out).resolve(); out.mkdir(parents=True,exist_ok=True)
    outcomes=[]
    try: front_document(dict(META,advisor=''),out)
    except ValueError: outcomes.append('missing_metadata_rejected')
    else: raise AssertionError('缺失导师未被阻断')
    paragraphs=front_document(META,out).paragraphs
    assert not any('{{' in p.text for p in paragraphs)
    assert not any('孟凡宇' in p.text or '蔡黔鹰' in p.text or '2026年   5月' in p.text for p in paragraphs)
    outcomes.append('template_bound_without_sample_identity')
    md=['---']+[f'{k}: {v}' for k,v in META.items()]+['---','# 摘　　要','本文是分页回归样例。',
        '# ABSTRACT','This document is a pagination regression fixture.','# 目　　录','<!--TOC-->','# 第1章　分页回归']
    md+=['这是用于占据页面空间的合成段落，不属于任何真实论文。']*28
    md+=['表1.1　短表整表移页检查','| 编号 | 名称 | 说明 |','| --- | --- | --- |']
    md += [f'| {i} | 短表记录{i} | 整表应在同一页 |' for i in range(1,9)]
    md += ['# 第2章　长表回归','表2.1　多页数据完整性检查','| 编号 | 名称 | 说明 |','| --- | --- | --- |']
    md += [f'| {i} | 长表记录{i} | 用于检验续表与逐行数据保留 |' for i in range(1,131)]
    for n in range(3,7): md += [f'# 第{n}章　回归检查','正文测试段落。']
    md += ['# 结论','独立测试完成。','# 参考文献','[1] 测试用参考条目。','# 致　　谢','本文件仅用于技能回归测试。','# 附　　录','测试说明。']
    manuscript=out/'regression.md'; manuscript.write_text('\n'.join(md),encoding='utf-8')
    raw=out/'regression-raw.docx'; final=out/'regression.docx'
    build_docx(str(manuscript),str(raw),15)
    assert len(Document(raw).sections)==6
    assert any(b[0]=='p' and b[1].startswith('续表') for b in iter_blocks(['续表2.1　测试']))
    outcomes.append('six_sections_and_continuation_parser')
    if args.word:
        report=paginate(raw,final)
        assert report['splits']>=2
        assert report['tables'][0]['pages'][0]==report['tables'][0]['pages'][1]
        assert report['tables'][0]['pages'][0]>report['body_start_page']
        assert fingerprint(Document(raw))==fingerprint(Document(final))
        update_docx(str(final),str(out/'regression.pdf'))
        result=check(str(final))
        (out/'structure.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        assert result['ok'],result['errors']
        outcomes.extend(['short_table_whole_page','long_table_explicit_continuations','all_rows_preserved','final_word_layout_and_structure_pass'])
        bad=Document(final)
        border=OxmlElement('w:tcBorders'); edge=OxmlElement('w:left'); edge.set(qn('w:val'),'single'); border.append(edge)
        bad.tables[0].cell(1,0)._tc.get_or_add_tcPr().append(border)
        badpath=out/'negative-cell-border.docx'; bad.save(badpath)
        assert any('三线表' in e for e in check(str(badpath))['errors'])
        outcomes.append('cell_border_override_rejected')
        again=out/'regression-again.docx'
        second=paginate(final,again)
        assert second['splits']==0
        assert fingerprint(Document(again))==fingerprint(Document(final))
        outcomes.append('pagination_idempotent')
        stale=Document(again); stale.add_paragraph('追加的回归文本'); stale.save(again)
        assert any('过期' in e for e in check(str(again))['errors'])
        outcomes.append('stale_layout_report_rejected')
        import fitz
        with fitz.open(out/'regression.pdf') as pdf:
            for i in (0,1,6,7,8):
                if i<len(pdf): pdf[i].get_pixmap(matrix=fitz.Matrix(1.2,1.2)).save(str(out/f'page-{i+1}.png'))
    (out/'test-results.json').write_text(json.dumps({'passed':outcomes},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'passed':outcomes},ensure_ascii=False))

if __name__=='__main__': main()
