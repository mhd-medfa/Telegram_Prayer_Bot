FROM python:3.10.13-alpine3.18
LABEL authors="Ilnur"

RUN adduser -D myuser

# Copy requirements to directory
COPY requirements.txt /app_data/requirements.txt

RUN python3 -m pip install -r /app_data/requirements.txt --no-cache-dir


# Copy files
COPY dbhelper.py /app_data/dbhelper.py
COPY bot.py /app_data/bot.py
COPY config.py /app_data/config.py
COPY client_secret /app_data/client_secret
COPY .env /app_data/.env

# Change project to read-only
RUN chmod -R 555 /app_data

USER myuser

WORKDIR /app_data

CMD ["python3", "bot.py"]
