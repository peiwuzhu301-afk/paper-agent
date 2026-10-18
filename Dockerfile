FROM python:3.12-slim
WORKDIR /app
# Non-editable installs place the package in site-packages, so point the app at
# the real project root explicitly (config/data/workspace live here).
ENV PAPER_AGENT_ROOT=/app
COPY pyproject.toml README.md ./
COPY backend ./backend
RUN pip install --no-cache-dir .
COPY config ./config
COPY data ./data
COPY workspace ./workspace
EXPOSE 8000
CMD ["paper-agent", "serve", "--host", "0.0.0.0", "--port", "8000"]
