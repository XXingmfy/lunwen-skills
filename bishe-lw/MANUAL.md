# bishe-lw 使用手册

## 当前流程（2026-11-16）

代码库号 → 登录云效拉取开题材料和源码 → 解析作者信息 → **按仓库材料建参考文献库**
（开题题录优先并联网核对知网原文、其余中文取 `论文/论文推荐`、英文取 `开题材料/外文原文`，总数 15–35 篇）→
匹配学校档案 + ty-lw-skill 写作 → 验收 → 上传云效。

不再向用户索要文献，也不再自动检索、反查、下载、凑篇数或按关键词插引用。
不再依赖川图/知网引擎或它们的账号。独立工具、历史下载文献及原稿不删除。

## 命令

```powershell
# 脚本目录：C:\Users\<user>\.dsh\skills\bishe-lw\scripts
python run.py init 010
# 一次跑完：拉库 → 解析材料 → 建文献库 → 匹配档案 → 建工作区。
# 返回 3 = 开题题录 + 论文推荐凑不够 15 条，先让用户补文献。

python run.py refs lib 010        # 看库内齐全数
python run.py refs harvest 010    # 重新扫描仓库材料
python run.py refs merge 010      # 合并补录结果（题名精确匹配才采用）
python run.py refs verify 010     # 校验稿件参考文献（发布闸门会再跑一遍）

# 缺字段/模板在 resume 阶段补，不用重新拉库。
python run.py resume 010 --set 学号=实际学号 --set 专业=实际专业
python run.py profile list
python run.py profile extract --school "XX大学" --template "学校模板.docx"

# 完成实际写作及内容、图表、DOCX/PDF 检查后：
python run.py detect 010
python run.py quality 010
python run.py publish 010 --dry-run
python run.py publish 010
```

## 参考文献口径

| 优先级 | 来源 | 类型标记 |
|---|---|---|
| 一、开题题录 | 任务书/开题报告里列的 `references`（**必须全部引用**） | 按原题录，原样保留 |
| 二、仓库推荐 | `论文/论文推荐/NN-题名.md`（可附 `pdf/`） | 学位论文 `[D]`、期刊 `[J]` |
| 三、英文 | `开题材料/外文原文*.pdf`，河北科技师范学院只此 1 篇 | `[J]` |

- 每篇论文参考文献**总数 15–35 篇**（`refs.min_total` / `refs.max_total`）。
- **任务书/开题报告里列的参考文献必须全部用上**，并联网在知网检索原文核对（`refs.require_opening`）；
  取不到原文的在交付报告里点名，不许拿相近的另一篇顶替。
- 中文条目**只能**来自库内清单（开题题录 + 论文推荐）；引用了库外中文文献会被发布闸门拦下。
- 英文条目必须含外文原文那篇、放绪论讲国外研究现状；**河北科技师范学院英文就这 1 篇**，
  其他学校最多 3 篇（`refs.max_english` / `refs.english_by_school`）。
- 写作证据看 `.work\refs\notes.md`（开题题录 + 每篇的推荐原句与摘要）。
- 推荐文献题录补录顺序：**先读仓库里的该项 pdf/caj/md**；读不出来再联网按题名检索核对
  （知网、百度学术，只用来核对元数据），题名必须与库内一致，URL 记进 `url` 字段。
  结果填进 `.work\refs\meta-results.json`，跑 `refs merge`。
  **题名对不上或 `confidence` 不是 `exact` 的一律丢弃**；读不出的字段留空，
  期刊按 `[J/OL]`、学位论文按 `[D/OL]` 加知网链接著录，**绝不编造作者/刊名**。
- 外文原文的题录由脚本从 PDF 首页识别，识别不准时人工改 `.work\refs\en-source.json` 后重跑 harvest。

`refs verify` 会拦：条数不在 15–35、编号不连续、开题题录漏引、引用了库外中文文献、没引外文原文、
英文超过学校配额、库内对应条目题录不全、正文引用超出编号范围；缺作者默认只告警并计入交付报告
（`refs.require_authors: true` 时改为阻断）。

## 用户额外提供文献（可选）

```powershell
python run.py refs accept 010 --files "D:\用户提供\文献1.pdf" "D:\用户提供\文献清单.md"
python run.py refs status 010
```

接收文件复制到 `D:\Tools_Home\DeepseekHarness_Load\lw\<代码库号>\论文\文献\`，
状态和哈希保存在 `.work\paper-context\reference-intake.json`；
不执行附件、不改正文、不改引用、不删除原件，同名不同内容不覆盖。
这只是备查通道：**不会**自动进文献库，要引用仍需人工确认后写进正文。不再作为发布前置条件。

## 保留能力与边界

- 论文生产统一使用 ty-lw-skill；河北科技师范学院使用相应格式档案。
- 云效认证、分支探测、原有稿件保护、朱雀主备 Key、内容/格式检查要求、安全上传保留。
- 网络逐句溯源仍是可选查重辅助（`plagiarize` / `plagiarize-report`），不是文献采集、不是商业全文查重。
- `refs keywords/collect/apply` 不再提供；不能用旧指令触发外部引擎。
- 文献和中间产物留在本地，发布仍只提交论文四件套。
- 本次改动不表示先前审核报告的所有遗留风险已全部消除。

## 密钥与配置

`config.yaml` 保存云效、路径、引擎、质量阈值；`refs` 段定义文献来源目录、`min_total`（默认 20）与
`require_english`。本机 `secrets.env`（技能根目录，与 scripts 目录并列，不入库）继续保存：

```ini
YUNXIAO_PAT=pt-xxxx
MAKERS_MODELS_KEY=sk-xxxx
MAKERS_MODELS_KEY_BACKUP1=sk-xxxx
MAKERS_MODELS_KEY_BACKUP2=sk-xxxx
```

无需川图凭据。已有凭据不删除，但本技能不再读取。不要把密钥提交到仓库。
