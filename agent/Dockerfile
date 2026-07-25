FROM python:3.12-alpine

RUN apk add --no-cache docker-cli

COPY server.py /app/server.py

ENV SPACE_AGENT_PORT=9000
EXPOSE 9000

CMD ["python3", "/app/server.py"]
