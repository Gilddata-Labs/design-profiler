# GildData Design Data Profiler - hardened image. Standard library only; nothing is pip-installed.
FROM python:3.12-alpine

RUN adduser -D -u 10001 profiler
WORKDIR /app
COPY *.py ext_classes.csv UPSTREAM_COMMIT ./
COPY EDITION* README_FIRST.txt ./

ENV PROFILER_IN_DOCKER=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

USER profiler
# /data = the folder to measure (mount it read-only)   /out = where the metrics zip is written
ENTRYPOINT ["python", "/app/gilddesign.py", "extract", "/data", "--out", "/out"]
