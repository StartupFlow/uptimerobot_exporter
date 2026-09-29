FROM python:alpine
LABEL maintainer="LEKPA"

COPY files/exporter.py /exporter.py

RUN pip install --no-cache-dir --upgrade requests pip
RUN adduser -D -u 1000 app
USER 1000

EXPOSE 9705

CMD [ "python", "/exporter.py" ]
