FROM pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime

RUN apt-get update && apt-get install -y --no-install-recommends git libgl1 libglib2.0-0 wget && rm -rf /var/lib/apt/lists/*
WORKDIR /srv
COPY requirements.txt requirements-gpu.txt ./
RUN pip install --no-cache-dir -r requirements.txt && pip install --no-cache-dir -r requirements-gpu.txt
COPY . .
RUN bash scripts/download_sam2.sh
ENV WEB_ASSETS_DIR=/srv/web
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
