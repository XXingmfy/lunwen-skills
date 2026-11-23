"""参考文献库回归测试。全部在临时目录里跑，不联网、不登录、不碰真实论文。"""
import json
from pathlib import Path
import sys
import tempfile
import unittest
import unittest.mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import reflib

CFG = {'refs': {'zh_source_dir': '论文/论文推荐', 'min_total': 20, 'require_english': True}}

MD_TMPL = """# {title}

- 类型：期刊　年份：2023　被引：12
- 关键词：测试;关键词;
- 知网链接：https://kns.cnki.net/kcms2/article/abstract?v=TEST{seq}
- 类别：测试类

## 为什么推荐

测试用。

## 具体推荐句（原文摘录）

> 这是一句测试用的原文摘录。

（出处：知网摘要）

## 建议引用位置

第2章

## 摘要

测试摘要。
"""


def make_repo(base: Path, n: int = 22, opening=None, school: str = '测试大学') -> Path:
    root = base / 'bishe099'
    rec = root / '论文' / '论文推荐'
    rec.mkdir(parents=True)
    (root / '开题材料').mkdir()
    for i in range(1, n + 1):
        (rec / f'{i:02d}-测试文献{i:02d}.md').write_text(
            MD_TMPL.format(title=f'测试文献{i:02d}', seq=i), encoding='utf-8')
    (root / '.work').mkdir()
    (root / '.work' / 'student.json').write_text(
        json.dumps({'school': school, 'references': opening or []}, ensure_ascii=False),
        encoding='utf-8')
    return root


def complete_library(root: Path, n: int = 20, with_en: bool = True) -> dict:
    """直接造一份题录齐全的文献库，跳过 PDF/联网。"""
    lib = json.loads((root / '.work' / 'refs' / 'library.json').read_text(encoding='utf-8'))
    for e in lib['zh']:
        e['authors'] = ['张三']
        e['source'] = '计算机工程'
        e['status'] = 'complete'
    lib['en'] = ([{'id': 'E1', 'origin': 'en_source',
                      'title': 'Exploring the potential of an AI language model',
                   'authors': ['Atsushi Mizumoto'], 'source': 'Research Methods',
                   'year': '2023', 'volume': '2', 'pages': '100050', 'needs_review': False}]
                 if with_en else [])
    lib['stats'] = reflib._stats(lib)
    (root / '.work' / 'refs' / 'library.json').write_text(
        json.dumps(lib, ensure_ascii=False), encoding='utf-8')
    return lib


def write_manuscript(root: Path, titles, extra_en: str | None = None) -> None:
    lines = ['# 第1章 绪论', '', '正文引用 [1]、[2]。', '', '# 参考文献', '']
    for i, t in enumerate(titles, 1):
        lines.append(f'[{i}] 张三. {t}[J]. 计算机工程, 2023.')
    if extra_en:
        lines.append(f'[{len(titles) + 1}] {extra_en}')
    (root / '.work' / 'manuscript.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')


class RefLibTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)

    def test_parse_md_fields(self):
        root = make_repo(self.base, n=1)
        path = next((root / '论文' / '论文推荐').glob('*.md'))
        entry = reflib.parse_rec_md(path)
        self.assertEqual(entry['title'], '测试文献01')
        self.assertEqual(entry['kind'], '期刊')
        self.assertEqual(entry['year'], '2023')
        self.assertIn('kns.cnki.net', entry['cnki'])
        self.assertEqual(entry['quote'], '这是一句测试用的原文摘录。')
        self.assertEqual(entry['chapter'], '第2章')

    def test_harvest_counts_and_template(self):
        root = make_repo(self.base)
        lib = reflib.harvest(root, CFG)
        self.assertEqual(lib['zh'][0]['id'], 1)
        self.assertEqual(lib['stats']['zh_total'], 22)
        self.assertEqual(lib['stats']['zh_missing_author'], 22)
        refs = root / '.work' / 'refs'
        for name in ('library.json', 'library.md', 'missing-meta.md', 'meta-results.json'):
            self.assertTrue((refs / name).is_file(), name)
        tmpl = json.loads((refs / 'meta-results.json').read_text(encoding='utf-8'))
        self.assertEqual(len(tmpl), 22)
        self.assertEqual(tmpl[0]['id'], 1)

    def test_harvest_fails_when_too_few(self):
        root = make_repo(self.base, n=5)
        lib = reflib.harvest(root, CFG)
        self.assertEqual(lib['stats']['zh_total'], 5)
        with unittest.mock.patch('yx.load_config',
                                 return_value={'paths': {'runs_root': str(self.base)}}):
            self.assertEqual(reflib.main(['harvest', str(root)]), reflib.EXIT_MATERIAL)

    def test_merge_applies_exact_and_rejects_mismatch(self):
        root = make_repo(self.base)
        reflib.harvest(root, CFG)
        meta = root / '.work' / 'refs' / 'meta-results.json'
        rows = json.loads(meta.read_text(encoding='utf-8'))
        rows[0].update({'authors': '张三, 李四', 'source': '计算机工程', 'year': '2023',
                        'confidence': 'exact', 'url': 'https://xueshu.baidu.com/s?wd=x'})
        rows[1].update({'authors': '王五', 'source': '软件学报',
                        'title': '题名对不上的另一篇', 'confidence': 'exact'})
        rows[2].update({'authors': '赵六', 'source': '软件学报', 'confidence': 'guess'})
        rows[3].update({'authors': '钱七', 'source': '软件学报', 'confidence': 'exact'})
        meta.write_text(json.dumps(rows, ensure_ascii=False), encoding='utf-8')

        self.assertEqual(reflib.merge(root), 0)
        lib = json.loads((root / '.work' / 'refs' / 'library.json').read_text(encoding='utf-8'))
        by_id = {e['id']: e for e in lib['zh']}
        self.assertEqual(by_id[1]['authors'], ['张三', '李四'])
        self.assertEqual(by_id[1]['status'], 'complete')
        self.assertEqual(by_id[2]['authors'], [])          # 题名不符，拒收
        self.assertEqual(by_id[3]['authors'], [])          # confidence 非 exact，拒收
        self.assertEqual(by_id[4]['authors'], ['钱七'])     # id 命中，正常采用

    def test_verify_blocks_under_min_total(self):
        root = make_repo(self.base)
        reflib.harvest(root, CFG)
        complete_library(root)
        write_manuscript(root, [f'测试文献{i:02d}' for i in range(1, 12)])  # 只 11 条
        ok, report = reflib.verify(root, CFG)
        self.assertFalse(ok)
        self.assertTrue(any('少于要求的 20 条' in p for p in report['problems']))

    def test_verify_blocks_reference_outside_library(self):
        root = make_repo(self.base)
        reflib.harvest(root, CFG)
        complete_library(root)
        titles = [f'测试文献{i:02d}' for i in range(1, 21)] + ['库外某篇来路不明的论文']
        write_manuscript(root, titles)
        ok, report = reflib.verify(root, CFG)
        self.assertFalse(ok)
        self.assertTrue(any('不在仓库文献库' in p for p in report['problems']))

    def test_verify_blocks_missing_english(self):
        root = make_repo(self.base)
        reflib.harvest(root, CFG)
        complete_library(root)
        write_manuscript(root, [f'测试文献{i:02d}' for i in range(1, 21)])
        ok, report = reflib.verify(root, CFG)
        self.assertFalse(ok)
        self.assertTrue(any('外文原文' in p for p in report['problems']))

    def test_verify_passes_with_complete_library_and_english(self):
        root = make_repo(self.base)
        reflib.harvest(root, CFG)
        complete_library(root)
        write_manuscript(
            root, [f'测试文献{i:02d}' for i in range(1, 21)],
            extra_en='MIZUMOTO A. Exploring the potential of an AI language model[J]. '
                     'Research Methods, 2023, 2: 100050.')
        ok, report = reflib.verify(root, CFG)
        self.assertTrue(ok, report['problems'])
        self.assertEqual(report['total'], 21)
        self.assertEqual(report['en_cited'], 1)
        self.assertTrue((root / '.work' / 'refs' / 'verify.json').is_file())

    def _library_without_authors(self, root):
        """中文条目保留 md 题录（无作者），英文条目补一条外文原文。"""
        reflib.harvest(root, CFG)
        lib = json.loads((root / '.work' / 'refs' / 'library.json').read_text(encoding='utf-8'))
        lib['en'] = [{'id': 'E1', 'origin': 'en_source',
                      'title': 'Exploring the potential of an AI language model',
                      'authors': ['Atsushi Mizumoto'], 'source': 'Research Methods',
                      'year': '2023', 'needs_review': False}]
        lib['stats'] = reflib._stats(lib)
        (root / '.work' / 'refs' / 'library.json').write_text(
            json.dumps(lib, ensure_ascii=False), encoding='utf-8')

    def test_verify_warns_authorless_by_default(self):
        root = make_repo(self.base)
        self._library_without_authors(root)   # 库里没有作者（只有 md 题录）
        write_manuscript(root, [f'测试文献{i:02d}' for i in range(1, 21)],
                         extra_en='MIZUMOTO A. Exploring the potential of an AI language model[J]. '
                                  'Research Methods, 2023, 2: 100050.')
        ok, report = reflib.verify(root, CFG)
        self.assertTrue(ok, report['problems'])
        self.assertTrue(any('缺作者' in w for w in report['warnings']))

    def test_verify_blocks_authorless_when_required(self):
        root = make_repo(self.base)
        self._library_without_authors(root)
        strict = {'refs': dict(CFG['refs'], require_authors=True)}
        write_manuscript(root, [f'测试文献{i:02d}' for i in range(1, 21)],
                         extra_en='MIZUMOTO A. Exploring the potential of an AI language model[J]. '
                                  'Research Methods, 2023, 2: 100050.')
        ok, report = reflib.verify(root, strict)
        self.assertFalse(ok)
        self.assertTrue(any('缺作者' in p for p in report['problems']))

    def test_render_gbt(self):
        zh_j = {'authors': ['李玥', '房科言', '李茜'], 'title': '试题库系统',
                'kind': '期刊', 'source': '电脑知识与技术', 'year': '2025',
                'volume': '21', 'issue': '36', 'pages': '4-8'}
        self.assertEqual(reflib.render_zh(zh_j),
                         '李玥, 房科言, 李茜. 试题库系统[J]. 电脑知识与技术, 2025, 21(36): 4-8.')
        zh_d = {'authors': ['李靖'], 'title': '智能组卷', 'kind': '硕士',
                'source': '中南大学', 'year': '2024'}
        self.assertEqual(reflib.render_zh(zh_d), '李靖. 智能组卷[D]. 中南大学, 2024.')
        many = dict(zh_d, authors=['甲', '乙', '丙', '丁'])
        self.assertIn(', 等', reflib.render_zh(many))
        en = {'authors': ['Atsushi Mizumoto', 'Masaki Eguchi'],
              'title': 'Exploring the potential', 'source': 'Research Methods in Applied Linguistics',
              'year': '2023', 'volume': '2', 'pages': '100050'}
        self.assertEqual(reflib.render_en(en),
                         'MIZUMOTO A, EGUCHI M. Exploring the potential[J]. '
                         'Research Methods in Applied Linguistics, 2023, 2: 100050.')

    def test_journal_without_source_falls_back_to_link(self):
        root = make_repo(self.base)
        reflib.harvest(root, CFG)
        lib = json.loads((root / '.work' / 'refs' / 'library.json').read_text(encoding='utf-8'))
        for e in lib['zh']:
            e['authors'] = ['张三']
            e['status'] = reflib._complete(e)          # 期刊有知网链接、无刊名
        self.assertTrue(all(e['status'] == 'complete_link' for e in lib['zh']))
        rendered = reflib.render_zh(lib['zh'][0])
        self.assertIn('[J/OL]. 中国知网', rendered)
        self.assertIn('kns.cnki.net', rendered)
        lib['en'] = [{'id': 'E1', 'origin': 'en_source',
                      'title': 'Exploring the potential of an AI language model',
                      'authors': ['Atsushi Mizumoto'], 'source': 'Research Methods',
                      'year': '2023', 'needs_review': False}]
        lib['stats'] = reflib._stats(lib)
        (root / '.work' / 'refs' / 'library.json').write_text(
            json.dumps(lib, ensure_ascii=False), encoding='utf-8')
        write_manuscript(root, [f'测试文献{i:02d}' for i in range(1, 21)],
                         extra_en='MIZUMOTO A. Exploring the potential of an AI language model[J]. '
                                  'Research Methods, 2023.')
        ok, report = reflib.verify(root, CFG)
        self.assertTrue(ok, report['problems'])

    def test_verify_allows_two_extra_english_but_blocks_exceeding_cap(self):
        root = make_repo(self.base)
        reflib.harvest(root, CFG)
        complete_library(root)
        titles = [f'测试文献{i:02d}' for i in range(1, 21)]
        extra = ['MIZUMOTO A. Exploring the potential of an AI language model[J]. Research Methods, 2023.',
                 'BURKE R. Hybrid recommender systems: survey and experiments[J]. User Modeling, 2002.',
                 'KOREN Y. Matrix factorization techniques for recommender systems[J]. Computer, 2009.']
        # 外文原文 + 2 篇额外英文 = 3 条，刚好在上限内
        write_manuscript(root, titles, extra_en='\n'.join(
            [f'[21] {extra[0]}', f'[22] {extra[1]}', f'[23] {extra[2]}']))
        ok, report = reflib.verify(root, CFG)
        self.assertTrue(ok, report['problems'])
        self.assertEqual(report['en_cited'], 3)
        self.assertEqual(report['en_from_source'], 1)
        self.assertEqual(report['en_extra'], 2)

        # 再加一篇 → 超过上限 3
        write_manuscript(root, titles, extra_en='\n'.join([
            f'[21] {extra[0]}', f'[22] {extra[1]}', f'[23] {extra[2]}',
            '[24] SARWAR B. Item-based collaborative filtering[J]. WWW, 2001.']))
        ok, report = reflib.verify(root, CFG)
        self.assertFalse(ok)
        self.assertTrue(any('超过上限 3 条' in p for p in report['problems']))

    def test_opening_refs_must_be_cited(self):
        opening = ['张三. 开题报告引用的第一篇文献研究[J]. 计算机工程, 2020, 1(1): 1-2.',
                   '李四. 开题报告引用的第二篇文献研究[D]. 中南大学, 2019.']
        root = make_repo(self.base, opening=opening)
        reflib.harvest(root, CFG)
        complete_library(root)
        write_manuscript(root, [f'测试文献{i:02d}' for i in range(1, 21)],
                         extra_en='MIZUMOTO A. Exploring the potential of an AI language model[J]. '
                                  'Research Methods, 2023.')
        ok, report = reflib.verify(root, CFG)
        self.assertFalse(ok)
        self.assertTrue(any('开题报告里列的' in p for p in report['problems']))
        self.assertEqual(report['opening_zh'], 2)
        self.assertEqual(report['opening_cited'], 0)

        # 把两条开题题录加进正文后通过
        write_manuscript(root, ['开题报告引用的第一篇文献研究', '开题报告引用的第二篇文献研究']
                         + [f'测试文献{i:02d}' for i in range(1, 19)],
                         extra_en='MIZUMOTO A. Exploring the potential of an AI language model[J]. '
                                  'Research Methods, 2023.')
        ok, report = reflib.verify(root, CFG)
        self.assertTrue(ok, report['problems'])
        self.assertEqual(report['opening_cited'], 2)

    def test_verify_blocks_over_max_total(self):
        root = make_repo(self.base, n=36)
        reflib.harvest(root, CFG)
        complete_library(root)
        write_manuscript(root, [f'测试文献{i:02d}' for i in range(1, 37)],
                         extra_en='MIZUMOTO A. Exploring the potential of an AI language model[J]. '
                                  'Research Methods, 2023.')
        ok, report = reflib.verify(root, CFG)
        self.assertFalse(ok)
        self.assertTrue(any('超过上限 35 条' in p for p in report['problems']))

    def test_english_quota_follows_school(self):
        cfg = {'refs': dict(CFG['refs'], english_by_school={'河北科技师范学院': 1})}
        self.assertEqual(reflib._max_english_for(cfg['refs'], '河北科技师范学院'), 1)
        self.assertEqual(reflib._max_english_for(cfg['refs'], '别的大学'), 3)
        root = make_repo(self.base, school='河北科技师范学院')
        lib = reflib.harvest(root, cfg)
        self.assertEqual(lib['rules']['max_english'], 1)


    def test_module_stays_offline(self):
        """脚本自身不发起网络请求：联网补录由 Agent 在会话里做，脚本只合并与校验。"""
        import ast
        tree = ast.parse(Path(reflib.__file__).read_text(encoding='utf-8'))
        imports = [ast.unparse(n) for n in ast.walk(tree)
                   if isinstance(n, (ast.Import, ast.ImportFrom))]
        banned = ('requests', 'urllib', 'subprocess', 'socket', 'httpx', 'aiohttp', 'http.client')
        self.assertFalse([x for x in imports if any(b in x for b in banned)], imports)


if __name__ == '__main__':
    unittest.main()
