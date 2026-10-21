FROM mcr.microsoft.com/playwright/python:v1.48.0-noble

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV HEADLESS=1
ENV PORT=7860
EXPOSE 7860

CMD ["python", "tiktokscrapper.py"]