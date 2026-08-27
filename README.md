# Video Learning Agent

Video Learning Agent 把“看视频学习”自动化成一条工程流水线。

你给它一个 B站/YouTube 视频链接、合集链接，或者一个视频列表文件。它会先尝试拿字幕；如果没有字幕，就把任务发到你租好的 GPU 云主机上跑 ASR；转写完成后拉回本地，生成 Markdown 学习文档，并建立本地搜索索引。

```text
B站 / YouTube 链接或列表
-> 优先获取字幕
-> 无字幕时上传任务到 GPU 云主机
-> GPU 下载音频并跑 faster-whisper ASR
-> 拉回 transcript.md / segments.jsonl
-> 生成可学习、可操作的 Markdown 总结
-> 建 SQLite / Chroma 搜索索引
```

## 适合谁

- 想批量消化课程视频的人
- 想把公开视频变成学习文档的人
- 想自动生成“知识点 + 例子 + 工具命令 + GitHub 项目 + AI 实践项目”的人
- 想让 Claude、Codex、WorkBuddy 通过 MCP 调用这套流程的人

## 功能

- 支持 B站和 YouTube
- 支持单视频、合集、playlist、TSV/CSV 视频列表
- 优先拉字幕，字幕不可用时才跑 ASR
- 支持你手动租 GPU 云主机，然后把 SSH 信息交给 Agent 自动处理
- 远程 ASR 使用 `faster-whisper`
- 默认模型 `medium`
- 默认 GPU 模式 `cuda + float16`
- 默认每批 20 个视频
- 默认 4090 可尝试 3 个 ASR worker 并发
- 实时查看下载/ASR 进度
- 结果拉回本地后生成 Markdown 学习文档
- 本地 SQLite 搜索，Chroma 语义搜索可选
- 提供 MCP server

## 安装

```bash
git clone https://github.com/hahahng/video-learning-agent.git
cd video-learning-agent
python3 -m pip install -e '.[remote,mcp,test,yaml]'
```

需要系统里有：

```bash
ffmpeg
yt-dlp
python >= 3.10
```

macOS 可以这样装：

```bash
brew install ffmpeg yt-dlp
```

## 最简单用法：有字幕的视频

如果视频有字幕，不需要 GPU。

```bash
video-agent ingest "https://www.bilibili.com/video/BVxxx"
```

命令会创建一个任务目录：

```text
work/jobs/<job_id>/
```

查看状态：

```bash
video-agent status <job_id>
```

生成总结：

```bash
video-agent digest <job_id> --index
```

搜索：

```bash
video-agent search "文件系统"
```

## 没字幕怎么办：租 GPU 跑 ASR

如果视频没有字幕，或者字幕质量太差，就租一台带 NVIDIA GPU 的云主机跑 ASR。

这个项目不自动帮你买机器。你自己在云平台开好 GPU 实例，然后把 SSH 信息填到配置里。

推荐配置：

- GPU：RTX 4090 / A10 / A100 / L40S 都可以
- 系统：Ubuntu 20.04 / 22.04
- 磁盘：至少 50GB，可批量跑建议 100GB+
- 网络：能访问 B站 / YouTube / Hugging Face 模型下载地址
- 登录方式：SSH password 或 SSH key

### 1. 租 GPU 云主机

任选支持 SSH 的 GPU 云平台。流程通常是：

1. 选择 GPU 实例，比如 4090。
2. 选择 Ubuntu 镜像。
3. 开机。
4. 在控制台找到 SSH 连接信息：
   ```text
   host
   port
   user
   password 或 private key
   ```
5. 本地先确认能登录：
   ```bash
   ssh -p <port> <user>@<host>
   ```

只要这一步能登录，Agent 就能接管后面的安装依赖、上传任务、跑 ASR、拉回结果。

更多细节见：[GPU ASR 使用说明](docs/gpu-asr.md)

### 2. 配置 GPU SSH

复制配置文件：

```bash
cp video-agent.config.example.yaml video-agent.config.yaml
```

编辑 `video-agent.config.yaml`：

```yaml
jobs_root: work/jobs
data_root: data

gpu_profiles:
  my_4090:
    host: your.gpu.ssh.host
    port: 22
    user: root
    remote_root: /root/autodl-tmp/video-learning-agent
    password_env: VIDEO_GPU_PASSWORD
```

密码不要写进配置文件。放到环境变量：

```bash
export VIDEO_GPU_PASSWORD='你的 GPU SSH 密码'
```

如果用 SSH key：

```yaml
gpu_profiles:
  my_4090:
    host: your.gpu.ssh.host
    port: 22
    user: root
    remote_root: /root/autodl-tmp/video-learning-agent
    key_filename: /Users/you/.ssh/id_ed25519
```

### 3. 批量跑视频列表

TSV 格式示例：

```tsv
index	bv	title	url	duration
1	BVxxxx	第一节	https://www.bilibili.com/video/BVxxxx	
2	BVyyyy	第二节	https://www.bilibili.com/video/BVyyyy	
```

启动：

```bash
video-agent ingest ./videos.tsv \
  --gpu-profile my_4090 \
  --batch-size 20 \
  --asr-workers 3
```

如果你已经创建了 job，但还没启动远程 ASR：

```bash
video-agent run-remote-asr <job_id> \
  --gpu-profile my_4090 \
  --batch-size 20 \
  --asr-workers 3
```

### 4. 实时看进度

```bash
video-agent status <job_id> --gpu-profile my_4090 --watch
```

输出类似：

```text
进度：ASR 中
音频：51 / 73
转写：18 / 73
当前：BVxxxx
GPU：82%，显存 17.4G / 24.0G
音频占用：3.9G
数据盘剩余：46G
错误：无
```

### 5. 拉回结果

```bash
video-agent pull <job_id> --gpu-profile my_4090
```

本地结果会在：

```text
work/jobs/<job_id>/transcripts/
```

每个视频包含：

```text
transcript.md
segments.jsonl
```

### 6. 生成学习文档

```bash
video-agent digest <job_id> --index
```

输出：

```text
work/jobs/<job_id>/digests/
data/video_learning.sqlite
```

如果设置了 `OPENAI_API_KEY`，会调用大模型生成更丰富的总结：

```bash
export OPENAI_API_KEY='你的 OpenAI API Key'
video-agent digest <job_id> --index
```

没有 API Key 时，会生成一个结构完整的本地草稿。

## 总结文档模板

每个视频会生成一个 Markdown 文档：

```markdown
# 编号｜总结标题

## 0. 这节课的主线流程图
## 1. 知识点
## 2. 老师例子
## 3. 中间用了什么工具、命令、工作流，我们可以学什么
## 4. GitHub 可复现项目
## 5. 我们利用 AI 可以做什么项目
## 6. 今天可以动手做什么
## 7. 学完这节应该留下什么
```

第 7 节会尽量落到：

```text
落地产物
输入
步骤
命令
验收标准
效率提升
```

## MCP 用法

启动 MCP server：

```bash
video-agent-mcp
```

提供工具：

- `ingest_url`
- `job_status`
- `run_remote_asr`
- `pull_transcripts`
- `digest_transcripts`
- `search_notes`

Claude、Codex、WorkBuddy 只要支持 MCP，就可以调用这些工具。

## 可选 Chroma 向量库

默认搜索是 SQLite 中文 n-gram，离线可跑。

如果想做语义搜索：

```bash
python3 -m pip install chromadb
video-agent index --docs work/jobs/<job_id>/digests --chroma
video-agent search "能做什么 AI 项目" --chroma
```

## 安全说明

- 不要把 SSH 密码写进 `video-agent.config.yaml`。
- 不要提交 `.env`、`video-agent.config.yaml`、`work/jobs/`。
- GPU 云主机只负责下载音频和 ASR，总结默认在本地跑。
- 当前项目不会自动购买、停止、销毁云主机。

## 开发测试

```bash
python3 -m compileall video_learning_agent tests
python3 -m pytest -q
```

