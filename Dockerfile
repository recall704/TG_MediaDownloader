FROM python:3.10.9-alpine

ENV TG_SESSION="tg_downloader"
ENV TG_MAX_PARALLEL=4
ENV TG_DL_TIMEOUT=5400

WORKDIR /app
COPY . /app/
RUN apk update && apk add build-base tzdata && pip install -r requirements.txt
RUN chmod +x tg_downloader.py

ENV TZ="Asia/Shanghai"

ENTRYPOINT ["python"]
CMD ["/app/tg_downloader.py"]
