# 学习小岛 · 后端（M1 + M2）

按《学习小岛：后端开发需求说明》实现。**M1**：上传解析（文字版 PDF / PPTX / DOCX / MD / TXT）→ 章 → 节骨架 → 大纲与状态接口。**M2**：节 → 知识点抽取 → 前置关系 → 讲解/闯关/题目生成 → schema 与出处校验 → 缓存，并开放知识点接口。

> 当前 AI 用 **mock 提供方**（`AI_PROVIDER=mock`）：离线、确定性、零成本，内容是按规则拼的假数据，只用来跑通链路，不能当成品内容看。接真模型见下文“换成真模型”。

## 跑起来

```powershell
python -m pip install -r requirements.txt
copy .env.example .env          # 改 TOKEN_SECRET
python -m uvicorn app.main:app --reload --port 8010
```

打开 http://127.0.0.1:8010/docs 看接口文档。默认 `AUTO_WORKER=true`，进程内自带任务轮询；生产建议设 `AUTO_WORKER=false`，单独跑 `python worker.py`。

```powershell
python -m pytest                # 24 个用例
python scripts/demo.py       # 对运行中的服务跑一遍上传 → 生成 → 删除
python scripts/diag_nodes.py    # 打印未通过校验的节点及原因
python tests/fixtures/make_fixtures.py   # 重新生成样本文件
```

## 换成真模型

`.env` 里改三行，代码不用动：

```
AI_PROVIDER=api
AI_BASE_URL=https://你的厂商/v1
AI_API_KEY=sk-...
AI_MODEL=你的模型名
AI_MODEL_CHEAP=评分用的小模型
```

接口按 OpenAI 兼容的 `/chat/completions` 写；换成别的协议只要改 `app/ai/provider.py` 里的 `ApiProvider._ask`。提示词在 `app/ai/prompts/v1/`，输出 schema 在 `app/ai/schemas/v1/`，都带版本号；改提示词要同时升版本，缓存键会跟着变。

## 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/documents` | 上传，返回 doc_id。不带令牌会自动发一个（响应头 `X-Visitor-Token`） |
| GET | `/api/documents/{id}/status` | 阶段、进度、页数、页码偏移、失败原因、任务重试记录 |
| GET | `/api/documents/{id}/outline` | 章 → 节 → 知识点树（含状态、前置、出处；章带 `no/icon/name/sectionCount/page`，节带 `no/name/page`） |
| GET | `/api/documents/{id}/play-data` | **前端原型直接可用**：一次返回 `CH / SC / N / AM / CM`，字段与《药用植物岛 · 教材试玩》常量一致 |
| GET | `/api/nodes/{id}` | 知识点完整内容（讲解、闯关、题目、出处、校验记录；另带 `num/pg/o/p/a/svg/g/pre` 原型别名） |
| POST | `/api/nodes/{id}/regenerate` | 重新生成该知识点（绕缓存；locked 节点拒绝覆盖） |
| DELETE | `/api/documents/{id}` | 删库 + 删文件 |
| POST | `/api/visitors` | 显式领匿名令牌 |
| GET | `/api/health` | 健康检查 |

`PATCH /api/nodes/{id}`（改名/合并/拆分/改前置）与 `/api/marks`、`/api/answers/grade`、`/api/feedback`、`/api/progress` 已占位，调用返回 501 —— 属于 M4。

### 前端字段对齐（`play-data`）

- `CH`：`[[章号, emoji, 短标题, 节数, 起始印刷页], …]`，章号连续按大纲顺序重排，emoji 先用占位色板（后续可让 AI 生成或前端覆盖）。
- `SC`：`{章号: [[节短标题, 起始印刷页], …]}`，标题已去掉 `1.1` 这类编号。
- `N`：`{全书连续序号: {e,t,pos,pre,pg,o,p,a,svg,g,id,status}}`；`pre` 是序号数组，`pos` 是按节内顺序算的百分比坐标，`o/p/a` 取自 `content.original/plain/analogy`，`g` 把后端 `{template,payload}` 翻成原型的 `match/order/choice`。
- `AM / CM`：重点理由，当前 mock 阶段 `AM` 只有 `hint=high` 的知识点占位理由、`CM` 多数为空，M4 接评分/考频后再填。
- `meta`：`docId / chapters / sections / knowledge / pending / status / filename / pageOffset`。
- 没有骨架时返回 409；`outline` 里的 `title` 仍是带编号的全名，`name` 才是纯标题。

原型接后端只要三步：把 `const CH / SC / N / AM / CM` 改成 `let`（`AM`、`CM` 在 176 行附近是 `const`），在 `map()` 前拉一次数据：

```js
const r = await fetch(`${BASE}/api/documents/${docId}/play-data`, {headers: {'X-Visitor-Token': token}});
const d = await r.json();
CH = d.CH; SC = d.SC; N = d.N; AM = d.AM; CM = d.CM;
```

`N` 的键是字符串数字，`S.st` 之类按整数索引的地方用 `+k` 或 `String(i)` 对齐即可；`pre` 已经是序号，可以直接沿用 `N[i].pre.every(done)` 的逻辑。

## M2 做了什么

1. **知识点抽取**：以“节”为单位，输出带页码与原文摘录的知识点，过 `knowledge_points` schema；节点 id 形如 `n_{doc8}_1_2_1`。
2. **前置关系**：同节按顺序串成链，跨节接上一节最后一个知识点；写库同时落 `node_prereqs` 边表，并做环检测（发现环拆掉后加的边）。
3. **讲解 / 闯关 / 题目**：每条知识点生成原文要点 + 三档大白话 + 类比 + 三选一模板闯关（match/order/scenario）+ 至少 3 道题（单选/判断/简答，难度 1–3，稳定 id `q_{node_id}_{序号}`）。
4. **校验**：schema 全过；`sourceRef.excerpt` 必须能在对应印刷页原文中回查到（OCR 文本用空白归一化比较）；题干/选项去重；不足 3 题的节点降级为 `partial`，不冒充完成。
5. **分阶段可见**：骨架落库后立刻可见，知识点与内容依次填充，节点状态 `skeleton → generating → ready/partial/failed`，章节状态随子节点汇总。
6. **缓存**：键 = 内容哈希 + 提示词版本 + schema 版本 + 提供方实现版本，重复跑不再调模型。

## M3 做了什么（扫描版 OCR）

1. **引擎**：`rapidocr-onnxruntime` 本地跑（`app/pipeline/extract/ocr.py`），无需密钥；页面图按 `data/pages/{doc_id}/p{页号}_{dpi}.png` 缓存，第二次同页不再渲染。
2. **目录页定位**：低 dpi（110）探 3–16 页，找“目录”标题或 ≥3 行带页码的章节条目，再向两侧延展；只认带印刷页码的行，正文页不会被误吞。
3. **目录解析**（`app/pipeline/outline/toc_ocr.py`）：按框高中位数自适应聚行；流式判定 `1.1.1`（跳过）→ `1.1`→ `1`；处理 OCR 常见毛病：编号被拆成两格（`"1." + "1"`）、编号与标题粘连（`3.1炮制`）、章号单独成格（`"10" + 富色素…`）、章号整块丢失（第 5、10 章，靠“后面紧跟第 1 节”反推章号）。
4. **页码偏移**：offset = 目录最后一页；再用正文首页页脚印刷页码回验。
5. **正文按需 OCR**：生成哪几节，就只 OCR 那几节覆盖的页，回填 `Page.text / ocr_confidence / image_key`，不整本 298 页硬跑；单次生成上限 `MAX_SECTIONS_GENERATE=6`。
6. **节点 id 带文档前缀**（`ch_{doc8}_1`、`n_{doc8}_1_2_1`）：`nodes.id` 是全局主键，不带前缀第二个文档会撞车。

## PPT 富内容解析（2026-11-24）

`extract_pptx` 不再只读标题占位符和文本框，改为递归遍历 `slide.shapes`，把每页内容按块写进 `Page.text`：

- **文本框**：保留段落层级，表格和图表不再漏。
- **表格**：转成 Markdown 表格，保留表头与单元格；`|` 和换行会做转义。
- **原生图表**：直接读 `chart.plots[*].categories` 与 `series.values`，生成“类别 + 系列”的数据表；没有缓存数值时在文本里标注需要视觉模型辅助。
- **图片**：`PICTURE` 和图片占位符会落内存后用 `rapidocr` OCR，输出 `[图片OCR 置信度 0.xx]` 块；小于 0.5 英寸的装饰图标跳过，WMF/EMF/SVG 暂不 OCR，单页最多 12 张。
- **组合形状**：递归遍历 `GROUP` 内的子形状，不会只读外层空壳。
- **SmartArt / 图示**：没有 `text_frame` 的图形，用 DrawingML 的 `a:t` 兜底抽文字。
- **演讲者备注**：`notes_slide` 写入 `[备注]` 块，老师常考的提示不再丢。

解析统计写到 `quality_json.ocr`：`slides / textBlocks / tables / charts / pictures / picturesOcr / picturesEmpty / notes / ocrLines / ocrPages / ocrMeanConfidence / lowConfidenceOcr`，方便上传后抽查。PPT 图片在解析阶段已 OCR，因此始终标记 `has_text_layer=True`，不会再被 PDF 扫描页 OCR 流程误处理。

单测 `tests/unit/test_extract.py::test_pptx_tables_charts_images_notes` 覆盖表格、图表、图片 OCR、组合形状和备注；Windows 本机完整回归 31 passed。

## 已做的判断

- **页码**：节点与出处统一暴露**印刷页**（PDF 页序减去自动探测的偏移），前端看到的页码和书一致。
- **页码偏移**：文字层页脚/页眉的印刷页码投票（≥2 票取最多）；扫描书的目录页 OCR 反推留给 M3（`app/pipeline/outline/page_offset.py::offset_from_toc_pairs`）。
- **骨架来源**：PDF 书签 → 正文“第X章 / 1.2 标题”正则 → DOCX Heading 样式 / PPT 标题占位符 → 都没有按篇幅切块并标注“待 AI 归纳”。
- **任务队列**：`doc_tasks` 表当队列，心跳超 10 分钟自动重排队，已存页文本 + 已存 teeth + 阶段游标支持断点续跑。
- **隔离与隐私**：所有接口按 visitor 校验；令牌只存 sha256；存储路径不含用户文件名；日志不打印正文。

## 尚未覆盖 / 已知短板

- mock 内容只有链路价值：大白话是模板拼接、类比是通用句，**不能作为交付内容**。
- 答案一致性（第二次独立作答校验）只在真模型下有意义，mock 阶段记为 `verified:false`，未执行。
- token / 费用记账表已建，但 `ApiProvider` 还没解析各家返回的 usage，成本目前记 0。
- mock 内容在真实教材上明显跑偏（OCR 文本长句被切成碎词当知识点），**只适合验链路，不能当内容**。
- 目录 OCR 有个别标题掉字（如 `7.1 组织药用植物资源成分`、`5.2 富含淀粉药物资源、种类`），落在 95% 容错内；低置信行会在 `stats.lowConfidenceRows` 里报出来，供人工抽查。
- EPUB、重点预标注 / 评分 / 反馈 / 导图编辑（M4）、限额 / Docker / 前端联调（M5）。

## 样例验收（本地实跑）

12 页带书签样本 PDF → `ready`，2 章 4 节 4 知识点，全部 `ready`，每个知识点 3 题、出处回查通过；`.exe` 上传 415；删除后目录与数据库无残留。

真实扫描教材（298 页、无文字层）→ `ready`：10 章 / 49 节，各章节数 3、2、6、5、6、6、5、5、6、5，章标题 10/10 命中、起始印刷页 10/10 命中（验收脚本 `scripts/_m3_probe.py`，约 90 秒）；端到端 `scripts/_m3_demo.py` 约 8 分钟（含 50 页正文 OCR），36 个知识点全 `ready`。

## 2026-11-23 极简清爽改版（最新）

前端单文件 `药用植物岛 · 教材试玩（接后端）.html` 已改成“极简清爽 + 高级感动森风”，并保持群岛、小岛商店、快进 7 天、错题本、总习题、重点模式、设置和所有节点解锁/点击交互不变。

- 页面底色改为暖奶油白 `#FAF7F0`；删除外围粉色船锚/小鱼平铺纹、岛内浅灰绿格子、弹窗纸纹，地图只保留很淡的天空/海面渐变。
- 小岛改成草绿/薄荷绿微立体岛：10px 浅沙色描边、深一档绿色侧壁、柔和外阴影和顶部高光，不做复杂 3D。
- 顶部标题改深橄榄棕 `#49483B`；胶囊按钮统一奶油白底 + 1.5px 细描边 + 3–4px 底部厚度 + 按下回弹。
- 节点统一成圆形立体徽章/石板：未解锁浅米灰 + 小锁，可挑战薄荷绿，已点亮暖杏，精通金色；连线改浅木色圆点虚线，完成路径薄荷绿。
- 9 套皮肤保留，只改海面渐变、草色、沙边、路径的低饱和配色；商店预览卡简化为“小岛色块 + 沙边”。
- 新增「补充资料」按钮（群岛页与节内页）与知识点面板「我的补充重点」，后者可按节点补一条自己的重点并持久化。

浏览器实测：首页、群岛、章节面板、3.5 节点地图、知识点面板、皮肤商店、补充资料面板均正常；`node --check` 通过；控制台无 error。

## 多资料合集（Course，2026-11-24）

后端已经能把 1–12 份 PPT/PDF 合成一份统一合集，不再是“每份文件各自一座独立资料岛”。

- `POST /api/courses`：multipart，字段 `files`（可多份）+ `title`；返回 `crs_...`、来源列表和状态。
- `GET /api/courses/{id}/status`：合集状态、全局页数、来源文件各自状态。
- `GET /api/courses/{id}/outline`：统一章 → 节 → 知识点树；节节点 `sources` 会列出来自哪几份资料、原始页码。
- `GET /api/courses/{id}/play-data`：与单文档相同的 `CH / SC / N / AM / CM`，`meta.courseId`、`meta.sources` 额外给出来源映射。
- `POST /api/courses/{id}/sources`：合集 ready 后追加资料；会重建统一大纲和内容，已生成节点会被重建。
- `DELETE /api/courses/{id}`：删合集、所有来源文件和汇总文档。

实现要点：

1. **不修改现有表**：新增 `courses` 和 `course_sources`，`Document / Page / Node` 结构不动。
2. **来源不重复生成**：每个来源 `process_document(..., stop_after="outline")`，只解析页和骨架；知识点/题目只对汇总文档生成一次。
3. **全局页映射**：汇总 `Page.page_no` 从 1 连续编号，`quality_json.sources` 记录 `{sourceId, globalStart, sourcePageStart, pageCount}`；节节点的 `sources` 存全局页段，`_section_text` 会按多个页段取原文。
4. **大纲合并**：新增 `merge_outline` 提示词/schema；配真模型时做语义合并，未配 Key 或输出不合法时回退到 `app/ai/outline_merge.py` 的标题归一化 + 相似度聚类。当前 mock 下两份同名 PPT 会合成 1 章 / 6 节，每节带 2 条来源引用。
5. **扫描版来源**：来源 PDF 无文字层时，合并前会把正文页 OCR 回填到来源 `Page`，再做全局页拼接。
6. **题目出处**：知识点 `sources` 和题目 `sourceRef` 会补 `sourceId / sourceName / sourcePage / globalPage`，保留原有 `page / excerpt` 兼容前端。

已知限制：语义合并目前是标题相似度兜底；不同标题但同一主题（如“总论”和“绪论”）还合不到一起，需要接真模型。合集重建会重置已生成节点，锁定/增量合并留给下一轮。

测试：`tests/integration/test_course.py` 覆盖两份 PPT 合并、补充第三份资料；Windows 完整回归 **33 passed**。

前端说明：「补充资料」面板已加「合成一个合集」入口：选 2–12 份资料、填可选标题，直接 `POST /api/courses`，完成后按 `crs_...` 打开。合集在页面上和普通资料岛共用一套地图/章节/闯关，知识点面板会显示「A.pptx p.1 · 合集」这样的来源，顶部显示「合集 · N 份资料」。原来的「补充单份资料」仍保留，单份仍各自成岛。

## 合集合并质量验证

`scripts/validate_merge.py` 会临时生成三份有交叉标题的 PPT（总论/资源/提取/分离），只跑到来源骨架和合并大纲，不生成知识点，避免验证阶段烧掉大量模型调用。直接对比：

```bash
python scripts/validate_merge.py --provider mock --out data/merge_eval_mock.json
python scripts/validate_merge.py --provider api  --out data/merge_eval_api.json
```

输出里看：`returnedChapters`、`returnedSections`、`duplicateTitlePairs`（近义标题仍被拆成两节）、`badRefs`（编造来源或页码）、`sourcesMissing`（漏掉的资料）、以及最终章/节标题。

当前 mock 基线：3 份资料共 16 个输入节 → 1 章 13 节；重复标题 0、坏引用 0、3 份资料全部覆盖。mock 靠标题相似度，能把「绪论/提取技术绪论」并到一起，但把整门课压成单章「综合资料」，章节层级不够。真模型需要 `.env` 里配好 `AI_BASE_URL / AI_API_KEY / AI_MODEL` 后再跑 `--provider api`；当前项目还没有 `.env`，所以真实合并结果尚未产出。

## 2026-11-24 交互流畅度与视觉细节优化

这一轮只改交互和细节，不换视觉语言：暖奶油白 `#FAF7F0`、草绿/薄荷绿小岛、浅沙描边、奶油白胶囊按钮和动森徽章都保留。

### 知识点路径与状态

- 节点明确分成 `locked`（迷雾/灰虚线/锁）、`avail`（当前可挑战/绿色描边 + 呼吸圆环）、`lit`（已点亮/暖杏底 + 对勾）、`master`（精通/金边 + 星标），已学但需要复习的节点用灰绿底 +「复」徽章。
- 连线分三段：已完成实线绿、从已完成点到当前可挑战点的绿色流动虚线、未开放灰点线。
- 地图左上增加「已学 x/y · 精通 x · 可挑战 x · 待复习 x」统计；章节面板也会显示「已点亮 4/5 据点」。
- 点击锁定节点不再把地图放大，直接提示「「X」还在迷雾里：先点亮「前置节点」，路就会开放」；多个前置未完成时提示数量。
- 进入某一节时节点逐个错峰入场；答题后重绘地图不会重复播入场动画。

### 统一弹窗

- `show()` / `cl()` 统一管理遮罩、`modal-open` 背景锁定、焦点记录和 220ms 退场动画；`#ov` 提升到 `z-index:80`，toast 为 `120`。
- 知识点详情、闯关、错题本、设置、存档备份、小岛商店、补充资料都在 `#sheet` 顶部注入同一枚 `.shbar/.shx` 关闭按钮；按钮固定在右上角，标题自动留出右侧空间。
- 打开时关闭按钮获得焦点，关闭后焦点回到打开前的元素；点击遮罩和 Escape 走同一套 `cl()`。

### 闯关手感

- 单选/总习题顶部有题型、进度、答错次数；选项带 A/B/C/D 键帽，答对给绿色反馈条，答错只抖动当前项并在 420ms 后重洗。
- 配对题显示「已配对 x/y」，排序题把已选项变成带编号的步骤卡；结算改成星级 + 贝壳 + 答错次数的紧凑 `resultbox`。
- 皮肤切换不再整块重绘商店，只原地更新当前卡片、价格和「使用中」标签，并刷新地图/群岛背景。
- 修了总习题错题 key 为空的旧 bug：现在空 key 会退回 `q:题干`，不同题不会互相覆盖。

### 模块化数据

- 新增 `data/course-data.js`，用普通 `<script src>` 在应用脚本之前加载，定义 `window.ISLAND_COURSE`；不使用 `fetch`/ES module，所以 `file://` 直接打开也能读。
- 顶层结构：`meta / chapters / chapterPath / sections / nodes / questions / highlights / chapterHighlights / skins / steps`。章节、节、知识点、题目分开维护；题目支持 `choice`、`match`、`order`。
- 当前数据包：10 章、49 节、5 个知识点、5 道题、9 套皮肤、6 个处理阶段；数据文件头部有新增章节/知识点/题目的字段说明。
- 前端依赖同目录 `data/course-data.js`；如果只把 HTML 复制到别处，示例教材会提示课程数据没加载。后端上传资料仍走 `play-data`，不受影响。

### 验收

`file://` 打开 HTML 可加载示例教材，无控制台 error；已走通群岛 → 章节 → 3.5 知识点、节点状态、锁定提示、单选/配对/排序闯关、结算、皮肤切换、设置和存档备份。`node --check` 对 inline 脚本和 `data/course-data.js` 均通过。最后一轮锁定节点不缩放和 A/B/C/D 键帽修正已重新加载检查。




