FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg awscli \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md config.json.example ./
COPY src/ ./src/
COPY ["RC-Logo White Full - PNG.png", "./"]
COPY Montserrat-ExtraBold.ttf ./

RUN pip install --no-cache-dir .

EXPOSE 8081

CMD ["uvicorn", "f1_reels.webapp:APP", "--host", "0.0.0.0", "--port", "8081"]
