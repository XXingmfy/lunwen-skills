"""离线回归测试。全部使用临时工作区和桩，不读取密钥、不登录、不修改真实论文。"""
import argparse
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import refs
import run


class ManualReferencesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / 'lw' / 'bishe010'
        self.work = self.root / '.work'
        self.work.mkdir(parents=True)
        (self.root / '开题材料').mkdir()
        self.student = {'school': '测试大学', 'template': 'A', 'references': ['已有题录'] * 30,
                        'fields': {'题目': '测试题目', '姓名': '测试', '专业': '测试', '学号': '1'}}
        self.ms = self.work / 'manuscript.md'
        self.ms.write_text('原始正文 [7]。\n', encoding='utf-8')
        (self.work / 'student.json').write_text(json.dumps(self.student), encoding='utf-8')
        self.cfg = {'paths': {'runs_root': str(self.base / 'lw'),
                             'materials_dir': '开题材料', 'output_dir': '论文'}}
        self.addCleanup(patch.stopall)
        patch('yx.load_config', return_value=self.cfg).start()
        patch('run._cfg', return_value=self.cfg).start()
        self.network = patch('yx.resolve_repo', side_effect=AssertionError('unexpected Yunxiao access')).start()
        self.before = self.ms.read_bytes()

    def test_large_opening_list_still_waits(self):
        self.assertEqual(refs.request(self.work, 'bishe010', self.student['references']), 9)
        self.assertFalse(refs.check_ready(self.work)[0])
        self.assertEqual(self.ms.read_bytes(), self.before)

    def test_accept_status_idempotency_and_changed_file(self):
        source = self.base / 'provided.md'
        source.write_text('用户提供的文献清单和阅读材料', encoding='utf-8')
        state = refs.accept(self.root, [source, source])
        self.assertEqual(len(state['files']), 1)
        refs.accept(self.root, [source])
        self.assertEqual(len(list((self.root / '论文' / '文献').iterdir())), 1)
        self.assertTrue(refs.check_ready(self.work)[0])
        target = self.root / state['files'][0]['path']
        target.write_text('被改动', encoding='utf-8')
        self.assertFalse(refs.check_ready(self.work)[0])
        self.assertEqual(self.ms.read_bytes(), self.before)

    def test_same_filename_different_content_preserved(self):
        a, b = self.base / 'a', self.base / 'b'
        a.mkdir(); b.mkdir()
        (a / 'refs.md').write_text('第一份文献', encoding='utf-8')
        (b / 'refs.md').write_text('第二份文献', encoding='utf-8')
        refs.accept(self.root, [a / 'refs.md', b / 'refs.md'])
        self.assertEqual(len(list((self.root / '论文' / '文献').iterdir())), 2)
        self.assertTrue(refs.check_ready(self.work)[0])

    def test_invalid_inputs_and_old_automation_state_do_not_satisfy(self):
        (self.work / 'student.json').write_text(json.dumps({'references_resolved': {'status': 'success'}}))
        self.assertFalse(refs.check_ready(self.work)[0])
        with self.assertRaises(refs.yx.YunxiaoError):
            refs.accept(self.root, [self.base])
        empty = self.base / 'empty.pdf'; empty.touch()
        with self.assertRaises(refs.yx.YunxiaoError):
            refs.accept(self.root, [empty])

    def test_old_commands_are_removed(self):
        for cmd in ('keywords', 'collect', 'apply'):
            with self.assertRaises(SystemExit) as e:
                refs.main([cmd, '010'])
            self.assertEqual(e.exception.code, 2)
        self.network.assert_not_called()

    def _make_rec_dir(self, n=22):
        rec = self.root / '论文' / '论文推荐'
        rec.mkdir(parents=True, exist_ok=True)
        for i in range(1, n + 1):
            (rec / f'{i:02d}-测试文献{i:02d}.md').write_text(
                f'# 测试文献{i:02d}\n\n- 类型：期刊　年份：2023\n'
                f'- 知网链接：https://kns.cnki.net/kcms2/article/abstract?v=T{i}\n\n'
                f'## 摘要\n\n测试摘要。\n', encoding='utf-8')
        return rec

    def test_resume_builds_repo_library_and_continues(self):
        self._make_rec_dir()
        (self.work / 'materials-extracted.md').write_text('开题材料', encoding='utf-8')
        with patch('run.complete_init', return_value=0) as prepare:
            self.assertEqual(run.main(['resume', '010']), 0)
            prepare.assert_called_once()
        self.assertTrue((self.work / 'refs' / 'library.json').is_file())
        self.network.assert_not_called()
        self.assertEqual(self.ms.read_bytes(), self.before)

    def test_resume_after_receipt_preserves_existing_manuscript(self):
        source = self.base / 'refs.md'; source.write_text('已提供材料', encoding='utf-8')
        refs.accept(self.root, [source])
        self._make_rec_dir()
        (self.work / 'materials-extracted.md').write_text('开题材料', encoding='utf-8')
        # 已有长正文；通过格式准备的桩确认不会调用骨架重建或拉库。
        self.ms.write_text('已有正文 [7]。' * 200, encoding='utf-8')
        before = self.ms.read_bytes()
        with patch('run.profiles_mod.resolve', return_value={'path': 'p.json', 'source': 'explicit'}), \
             patch('run.profiles_mod.check_school_match', return_value=[]), \
             patch('run.profiles_mod.lint', return_value={'ok': True}), \
             patch('run.prepare_workspace') as prepare, patch('run.fetch_mod.fetch') as fetch:
            self.assertEqual(run.main(['resume', '010']), 0)
            prepare.assert_not_called(); fetch.assert_not_called()
        self.assertEqual(before, self.ms.read_bytes())
        self.network.assert_not_called()

    def test_init_harvests_repo_library_and_continues(self):
        self.ms.unlink()
        self._make_rec_dir()
        self.network.side_effect = None
        self.network.return_value = {'path': 'bishe010'}
        info = {'repo': 'bishe010', 'name': '测试库', 'default_branch': 'main',
                'local_dir': str(self.root), 'work_dir': str(self.work), 'problems': []}
        parsed = dict(self.student, _evidence_text='开题材料证据')
        with patch('run.fetch_mod.fetch', return_value=info), \
             patch('run.parse_mod.parse', return_value=parsed), \
             patch('run.complete_init', return_value=0) as prepare:
            self.assertEqual(run.main(['init', '010']), 0)
            prepare.assert_called_once()
        lib = json.loads((self.work / 'refs' / 'library.json').read_text(encoding='utf-8'))
        self.assertEqual(lib['stats']['zh_total'], 22)

    def test_init_blocks_when_repo_library_too_small(self):
        self.ms.unlink()
        self._make_rec_dir(n=5)
        self.network.side_effect = None
        self.network.return_value = {'path': 'bishe010'}
        info = {'repo': 'bishe010', 'name': '测试库', 'default_branch': 'main',
                'local_dir': str(self.root), 'work_dir': str(self.work), 'problems': []}
        parsed = dict(self.student, _evidence_text='开题材料证据')
        with patch('run.fetch_mod.fetch', return_value=info), \
             patch('run.parse_mod.parse', return_value=parsed), \
             patch('run.complete_init') as prepare:
            self.assertEqual(run.main(['init', '010']), 3)
            prepare.assert_not_called()

    def test_publish_blocks_without_reference_gate(self):
        with patch('run._work_of', return_value=self.work), patch('run.publish_mod.plan') as plan:
            self.assertEqual(run.main(['publish', '010', '--dry-run']), 6)
            plan.assert_not_called()
        self.assertEqual(self.ms.read_bytes(), self.before)

    def test_cli_accept_then_resume_prepares_new_workspace(self):
        self.ms.unlink()
        source = self.base / 'user-refs.md'
        source.write_text('用户文献与题录', encoding='utf-8')
        self.assertEqual(run.main(['refs', 'accept', '010', '--files', str(source)]), 0)
        with patch('run.profiles_mod.resolve', return_value={'path': 'p.json', 'source': 'explicit'}), \
             patch('run.profiles_mod.check_school_match', return_value=[]), \
             patch('run.profiles_mod.lint', return_value={'ok': True}), \
             patch('run.prepare_workspace', return_value=0) as prepare:
            self.assertEqual(run.main(['resume', '010']), 0)
            prepare.assert_called_once()
        self.network.assert_not_called()

    def test_module_has_no_search_download_or_http_implementation(self):
        import ast
        tree = ast.parse(Path(refs.__file__).read_text(encoding='utf-8'))
        names = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
        self.assertFalse({'search_cnki', 'find_item_by_title', 'download_items', 'run_collect', 'run_apply'} & names)
        imports = [ast.unparse(node) for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))]
        self.assertFalse(any('requests' in x or 'urllib' in x or 'subprocess' in x for x in imports))


if __name__ == '__main__':
    unittest.main()
