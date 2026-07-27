# 使用与项目一致的 Python 主版本，避免本地/容器语法差异。
FROM python:3.12-slim
# 后续 COPY、CMD 都以此目录为基准。
WORKDIR /workspace
# 禁止 .pyc 并让日志实时输出，容器排错更方便。
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
# 先只复制依赖清单：代码变动时可以复用 pip 镜像层缓存。
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# 再复制应用代码；开发时会被 compose 的 bind mount 覆盖。
COPY app ./app
# 容器内对外监听 0.0.0.0，不能写 127.0.0.1。
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]