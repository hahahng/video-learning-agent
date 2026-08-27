# Video Learning Agent

把视频学习流程自动化：

```text
B站/YouTube 链接或列表
-> 优先拿字幕
-> 无字幕走远程 GPU ASR
-> 拉回转写稿
-> 生成 Markdown 学习文档
-> 建本地 SQLite 搜索索引
```

## 安装

```bash
python3 -m pip install -e '.[remote,mcp,test,yaml]'
```

## GPU 配置

```bash
cp video-agent.config.example.yaml video-agent.config.yaml
export VIDEO_GPU_PASSWORD='你的密码'
```

密码只放环境变量，不写进配置文件。

## 常用命令

```bash
video-agent ingest "https://www.bilibili.com/video/BVxxx" \
  --gpu-profile my_4090 \
  --batch-size 20 \
  --asr-workers 3
```

```bash
video-agent status <job_id> --gpu-profile my_4090 --watch
video-agent pull <job_id> --gpu-profile my_4090
video-agent run-remote-asr <job_id> --gpu-profile my_4090 --batch-size 20 --asr-workers 3
video-agent digest <job_id> --index
video-agent search "二维码传文件"
```

本地 TSV 也可以直接跑：

```bash
video-agent ingest ./videos.tsv \
  --gpu-profile my_4090 \
  --batch-size 20 \
  --asr-workers 3
```

## MCP

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

## 可选 Chroma 向量库

默认搜索是 SQLite 中文 n-gram，离线可跑。要语义搜索再装 Chroma：

```bash
python3 -m pip install chromadb
video-agent index --docs work/jobs/<job_id>/digests --chroma
video-agent search "能做什么 AI 项目" --chroma
```
