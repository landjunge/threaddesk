FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
RUN groupadd --gid 10001 threaddesk \
    && useradd --uid 10001 --gid threaddesk --create-home threaddesk \
    && install -d -m 0700 -o threaddesk -g threaddesk /data
WORKDIR /opt/threaddesk
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN python -m pip install --no-cache-dir '.[server]'
USER 10001:10001
VOLUME ["/data"]
EXPOSE 8766
ENTRYPOINT ["threaddesk-server"]
CMD ["serve", "--data-dir", "/data", "--host", "127.0.0.1", "--port", "8766"]
