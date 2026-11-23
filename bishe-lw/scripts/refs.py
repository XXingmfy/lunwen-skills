#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用户文献交接（离线）。不检索、不下载、不修改正文或引用编号。

run.py refs request <代码库号>       登记待提供并显示索要提示
run.py refs accept <代码库号> --files <文件...>   接收用户选定文件
run.py refs status <代码库号>        核验交接文件是否仍存在且未变
收到文献仅表示材料已交接，不代表已阅读、题录已核实或可支撑论文论断。
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
from datetime import datetime

import yx

WAITING = 9
ACCEPTED_SUFFIXES = {'.pdf', '.docx', '.txt', '.md', '.ris', '.bib', '.caj'}


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def state_path(work: Path) -> Path:
    return work / 'paper-context' / 'reference-intake.json'


def load_state(work: Path) -> dict:
    p = state_path(work)
    if not p.exists():
        return {'status': 'waiting_for_user', 'files': []}
    try:
        data = json.loads(p.read_text(encoding='utf-8-sig'))
        if not isinstance(data, dict):
            raise ValueError('交接记录应为对象')
        return data
    except (OSError, ValueError) as e:
        raise yx.YunxiaoError(f'文献交接记录不可读：{e}') from e


def save_state(work: Path, state: dict) -> None:
    p = state_path(work)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(p)


def check_ready(work: Path) -> tuple[bool, str]:
    try:
        state = load_state(work)
        if state.get('status') != 'received' or not state.get('files'):
            return False, '请先向用户索要文献并接收，不能以开题题录或旧下载记录替代本次交接。'
        root = work.parent.resolve()
        for item in state['files']:
            p = (root / item['path']).resolve()
            if not p.is_relative_to(root) or not p.is_file() or digest(p) != item['sha256']:
                return False, f"文献文件缺失或已变更，请重新接收：{item.get('path')}"
        return True, f"已收到用户文献 {len(state['files'])} 个文件；写作前仍需逐篇阅读、核对题录及引用。"
    except (OSError, ValueError, TypeError, KeyError, yx.YunxiaoError) as e:
        return False, f'文献交接校验失败：{e}'


def request(work: Path, repo: str, opening_refs: list | None = None) -> int:
    ok, note = check_ready(work)
    if not ok:
        previous = load_state(work)
        save_state(work, {
            'status': 'waiting_for_user', 'requested_at': datetime.now().isoformat(timespec='seconds'),
            'opening_references_count': len(opening_refs or []),
            'files': previous.get('files') or [],
        })
    print(f'开题材料已拉取、解析；识别到已有参考文献题录 {len(opening_refs or [])} 条。')
    print('请提供本次论文要使用的文献（优先 PDF 全文，可附题录清单、DOI/链接、RIS/BibTeX）。')
    print('也可提供本机文件路径，或明确确认使用已有文献并指出具体文件。')
    print('仅有题录或链接不能作为全文证据；缺少正文时会列出缺口向你询问，不自动联网补齐。')
    print('请提供文献；收到并核对后再继续写作。')
    if ok:
        print(note)
        print(f'如仍使用这批材料，可执行：python run.py resume {repo}')
        return 0
    print(f'接收命令：python run.py refs accept {repo} --files <文件1> <文件2>')
    return WAITING


def local_root(repo: str) -> Path:
    """已拉取仓库的本地定位；文献交接不需要再次登录云效。"""
    name = repo.strip().replace('\\', '/').split('/')[-1]
    if name.isdigit() and len(name) <= 3:
        name = f'bishe{int(name):03d}'
    base = Path(yx.load_config()['paths']['runs_root']).resolve()
    root = (base / name).resolve()
    if root == base or not root.is_relative_to(base) or not (root / '.work' / 'student.json').is_file():
        raise yx.YunxiaoError('请指定已初始化的本地代码库号（例如 010 / bishe010），先运行 init。')
    return root


def accept(root: Path, files: list[Path]) -> dict:
    """仅复制明确提供的文件。不遍历目录、不执行附件、不碰论文正文。"""
    sources = []
    for source in files:
        source = source.resolve()
        if not source.is_file() or source.suffix.lower() not in ACCEPTED_SUFFIXES:
            raise yx.YunxiaoError(f'请指定文献文件而非目录，支持 PDF/DOCX/TXT/MD/RIS/BIB/CAJ：{source}')
        if not source.stat().st_size:
            raise yx.YunxiaoError(f'文献文件为空：{source.name}')
        sources.append((source, digest(source)))
    if not sources:
        raise yx.YunxiaoError('尚未提供文献文件。')
    dest_dir = root / yx.load_config()['paths']['output_dir'] / '文献'
    # 防止目标目录 junction/symlink 让材料落到任务目录之外。
    if not dest_dir.resolve().is_relative_to(root.resolve()):
        raise yx.YunxiaoError('文献目标目录位于本次代码库目录外，已停止。')
    dest_dir.mkdir(parents=True, exist_ok=True)
    received = []
    seen = set()
    for source, sha in sources:
        if sha in seen:
            continue
        seen.add(sha)
        target = dest_dir / source.name
        if target.exists() and digest(target) != sha:
            target = dest_dir / f'{source.stem}-{sha}{source.suffix}'
        if target.exists():
            if digest(target) != sha:
                raise yx.YunxiaoError(f'目标文件冲突，未覆盖：{target.name}')
        else:
            shutil.copy2(source, target)
        if digest(target) != sha:
            raise yx.YunxiaoError(f'文献复制校验失败：{target.name}')
        received.append({'path': target.relative_to(root).as_posix(), 'sha256': sha,
                         'size': target.stat().st_size, 'source': 'user_provided'})
    state = {'status': 'received', 'received_at': datetime.now().isoformat(timespec='seconds'),
             'files': received, 'content_review': 'pending',
             'note': '用户文献已交接；尚未证明内容、题录或论断引用正确。'}
    save_state(root / '.work', state)
    print(f'已接收 {len(received)} 个用户文献文件，原稿与原引用未修改。')
    print(f'保存目录：{dest_dir}')
    print(f'下一步：python run.py resume {root.name}')
    return state


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description='用户提供文献（离线交接，无检索下载及自动插引用）')
    sub = ap.add_subparsers(dest='cmd', required=True)
    for command in ('request', 'status'):
        sub.add_parser(command).add_argument('repo')
    acc = sub.add_parser('accept')
    acc.add_argument('repo')
    acc.add_argument('--files', nargs='+', required=True, help='用户明确提供/确认的文献文件路径')
    args = ap.parse_args(argv)
    try:
        root = local_root(args.repo)
        work = root / '.work'
        if args.cmd == 'request':
            student = json.loads((work / 'student.json').read_text(encoding='utf-8-sig'))
            return request(work, root.name, student.get('references') or [])
        if args.cmd == 'accept':
            accept(root, [Path(p) for p in args.files])
            return 0
        ok, note = check_ready(work)
        print(note)
        return 0 if ok else WAITING
    except (yx.YunxiaoError, OSError, ValueError) as e:
        print(f'[错误] {e}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
