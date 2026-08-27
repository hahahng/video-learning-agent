# GPU ASR 使用说明

这份文档说明如何租一台 GPU 云主机，让 Video Learning Agent 自动跑 ASR。

## 工作方式

```text
本地机器
-> 解析视频列表
-> 上传 videos.tsv 和 remote_worker.py 到 GPU 机器
-> GPU 机器安装依赖
-> GPU 机器下载音频
-> GPU 机器用 faster-whisper 转写
-> 本地拉回 transcript.md / segments.jsonl
```

GPU 机器只负责重活：下载音频和 ASR。

总结、索引、搜索默认在本地完成。

## 选什么 GPU

推荐：

- RTX 4090：性价比高，适合批量课程视频。
- A10：稳定，显存够用。
- A100 / L40S：更强，但通常更贵。

不推荐：

- CPU 机器跑大量 ASR，太慢。
- 显存很小的 GPU 跑大模型并发，容易 OOM。

默认配置：

```text
ASR 引擎：faster-whisper
模型：medium
设备：cuda
计算类型：float16
批次：20 个视频
并发：3 个 worker
```

如果显存不够，把并发降到 2 或 1：

```bash
video-agent run-remote-asr <job_id> --gpu-profile my_4090 --asr-workers 1
```

## 租机器流程

大部分 GPU 云平台流程类似。以 AutoDL 为例，可以从实例列表进入：

```text
https://www.autodl.com/console/instance/list
```

通用步骤：

1. 新建 GPU 实例。
2. 选择 Ubuntu 镜像。
3. 选择数据盘，建议 50GB 起步。
4. 开机。
5. 从控制台复制 SSH 信息：
   ```text
   host
   port
   user
   password 或 key
   ```
6. 本地测试登录：
   ```bash
   ssh -p <port> <user>@<host>
   ```

能 SSH 登录后，Agent 就能工作。

## AutoDL 示例

如果使用 AutoDL：

1. 打开 [AutoDL 实例列表](https://www.autodl.com/console/instance/list)。
2. 新建一台 GPU 实例，或启动已有实例。
3. GPU 推荐选 4090；如果只是少量视频，A10 也可以。
4. 镜像选 Ubuntu。
5. 数据盘建议 50GB 起步，批量视频建议 100GB+。
6. 进入实例详情，找到 SSH 登录信息。
7. 记录这几项：
   ```text
   host
   port
   user
   password
   ```
8. 本地测试：
   ```bash
   ssh -p <port> <user>@<host>
   ```
9. 能登录后，把 SSH 信息写进 profile。

AutoDL 的页面可能会显示一整条 SSH 命令，例如：

```bash
ssh -p 12345 root@connect.example.com
```

对应到配置就是：

```yaml
gpu_profiles:
  autodl_4090:
    host: connect.example.com
    port: 12345
    user: root
    remote_root: /root/autodl-tmp/video-learning-agent
    password_env: AUTODL_PASSWORD
```

然后设置：

```bash
export AUTODL_PASSWORD='实例密码'
```

## 配置 profile

`video-agent.config.yaml`：

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

设置密码：

```bash
export VIDEO_GPU_PASSWORD='你的 SSH 密码'
```

不要把密码写进 YAML。

## 启动任务

```bash
video-agent ingest ./videos.tsv \
  --gpu-profile my_4090 \
  --batch-size 20 \
  --asr-workers 3
```

如果视频有字幕，会优先使用字幕。

如果没有字幕，会自动把需要 ASR 的视频发到 GPU。

## 看进度

```bash
video-agent status <job_id> --gpu-profile my_4090 --watch
```

关键字段：

```text
音频：已经下载的音频数 / 总数
转写：已经完成 ASR 的数量 / 总数
当前：当前视频 ID
GPU：GPU 利用率和显存
音频占用：远程 audio/ 占用
数据盘剩余：远程磁盘剩余
错误：最近错误
```

## 拉回结果

```bash
video-agent pull <job_id> --gpu-profile my_4090
```

拉回后看：

```text
work/jobs/<job_id>/transcripts/
```

## 常见问题

### CUDA 不可见

现象：

```text
CUDA requested but no GPU is visible
```

处理：

- 确认租的是 GPU 实例，不是 CPU 实例。
- 在远程执行：
  ```bash
  nvidia-smi
  ```
- 如果没有输出，说明驱动或实例类型不对。

### 模型下载慢

`faster-whisper medium` 第一次会下载模型。

处理：

- 确认 GPU 机器能访问 Hugging Face。
- 可以先跑一个小任务预热模型。
- 同一台机器后续会复用模型缓存。

### GPU 没跑满

可能原因：

- 正在下载音频，GPU 暂时空闲。
- 单个音频太短。
- ASR worker 数太低。
- IO 或网络慢。

可以尝试：

```bash
--asr-workers 3
```

如果 OOM，再降到：

```bash
--asr-workers 1
```

### 磁盘不够

建议：

- 云主机数据盘 50GB 起步。
- 大批量视频建议 100GB+。
- 已拉回的音频可以在远程清理。

当前版本不会自动销毁云主机，也不会自动删除你的远程目录。

## 成本建议

ASR 是短时重计算任务。建议：

1. 先本地跑 `ingest`，能拿字幕的不要走 GPU。
2. 只把无字幕视频发给 GPU。
3. GPU 机器开机后集中跑完。
4. 拉回结果确认无误。
5. 手动关机或释放云主机。

这样成本最低，也最不容易丢数据。
