# 서버에서 계속 돌릴 때 (GitHub Actions 대신)
#
#   docker build -t semi-bot .
#   docker run -d --restart unless-stopped --name semi-bot \
#       --env-file .env -v semi-bot-data:/data semi-bot
#
# 이미지에는 .env 가 들어가지 않는다. 실행할 때 --env-file 로 넘긴다.
# 보낸 공시 기록은 /data 볼륨에 남아, 재시작해도 같은 공시를 다시 보내지 않는다.

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Seoul \
    BOT_STATE_PATH=/data/state.json

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot/ ./bot/
RUN mkdir -p /data
VOLUME ["/data"]

CMD ["python", "-m", "bot.watch", "--loop", "--every", "60"]
