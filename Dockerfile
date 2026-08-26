FROM python:3.13-slim-trixie

WORKDIR /app

COPY pyproject.toml ./
COPY src ./src

RUN pip install --no-cache-dir .

ENV LB2TG_CONFIG=/etc/longbridge2tg/config.yaml

CMD ["python", "-m", "longbridge2tg"]
